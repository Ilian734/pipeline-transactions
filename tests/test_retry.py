"""Etape 7 : politique de retry.

Une erreur transitoire (base verrouillee) est rejouee ; une erreur
deterministe (contrainte violee, schema absent) ne l'est jamais.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from fabriques import fabriquer_fichier, fabriquer_transaction
from pipeline.persistance import (
    compter_transactions,
    connecter,
    creer_schema,
    est_erreur_retryable,
    executer_avec_retry,
    inserer_fichier,
)


@pytest.fixture
def connexion() -> Iterator[sqlite3.Connection]:
    conn = connecter(":memory:")
    creer_schema(conn)
    yield conn
    conn.close()


@pytest.mark.parametrize(
    ("erreur", "retryable"),
    [
        (sqlite3.OperationalError("database is locked"), True),
        (sqlite3.OperationalError("database table is locked"), True),
        (sqlite3.OperationalError("database is busy"), True),
        (sqlite3.OperationalError("no such table: transactions"), False),
        (sqlite3.IntegrityError("UNIQUE constraint failed"), False),
        (sqlite3.IntegrityError("FOREIGN KEY constraint failed"), False),
        (sqlite3.ProgrammingError("Incorrect number of bindings"), False),
        (sqlite3.DatabaseError("file is not a database"), False),
        (ValueError("montant non representable"), False),
    ],
)
def test_classification_des_erreurs(erreur: Exception, retryable: bool) -> None:
    assert est_erreur_retryable(erreur) is retryable


def test_erreur_transitoire_rejouee_jusqu_au_succes() -> None:
    appels = 0

    def operation() -> str:
        nonlocal appels
        appels += 1
        if appels < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert executer_avec_retry(operation, tentatives=5, dormir=lambda _: None) == "ok"
    assert appels == 3


def test_erreur_deterministe_jamais_rejouee() -> None:
    appels = 0

    def operation() -> None:
        nonlocal appels
        appels += 1
        raise sqlite3.IntegrityError("UNIQUE constraint failed: fichiers.empreinte")

    with pytest.raises(sqlite3.IntegrityError):
        executer_avec_retry(operation, tentatives=5, dormir=lambda _: None)
    assert appels == 1, "une contrainte violee se reproduira a l'identique"


def test_abandon_apres_epuisement_des_tentatives() -> None:
    appels = 0

    def operation() -> None:
        nonlocal appels
        appels += 1
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        executer_avec_retry(operation, tentatives=3, dormir=lambda _: None)
    assert appels == 3


def test_backoff_exponentiel() -> None:
    delais: list[float] = []

    def operation() -> None:
        raise sqlite3.OperationalError("database is locked")

    with pytest.raises(sqlite3.OperationalError):
        executer_avec_retry(
            operation, tentatives=4, delai_initial=0.1, dormir=delais.append
        )
    assert delais == [0.1, 0.2, 0.4]


def test_tentatives_invalides() -> None:
    with pytest.raises(ValueError, match="au moins 1"):
        executer_avec_retry(lambda: None, tentatives=0)


def test_la_reinsertion_aboutit_apres_une_erreur_retryable(
    connexion: sqlite3.Connection,
) -> None:
    """Simule un verrou au premier essai, puis verifie que la donnee est bien la."""
    fichier = fabriquer_fichier(
        [fabriquer_transaction("100.00"), fabriquer_transaction("250.00")]
    )
    appels = 0

    def operation() -> int | None:
        nonlocal appels
        appels += 1
        if appels == 1:
            raise sqlite3.OperationalError("database is locked")
        return inserer_fichier(connexion, fichier)

    fichier_id = executer_avec_retry(operation, tentatives=3, dormir=lambda _: None)

    assert appels == 2
    assert fichier_id is not None
    assert compter_transactions(connexion) == 2


def test_verrou_reel_libere_pendant_le_retry(tmp_path: Path) -> None:
    """Cas concret : une autre connexion tient un verrou exclusif puis le rend.

    Chaque thread ouvre sa propre connexion : SQLite interdit de partager un
    objet connexion entre threads.
    """
    base = tmp_path / "verrou.db"
    preparation = connecter(base)
    try:
        creer_schema(preparation)
    finally:
        preparation.close()

    fichier = fabriquer_fichier([fabriquer_transaction("42.00")])
    resultat: list[int | None] = []
    souci: list[BaseException] = []

    def ecrire() -> None:
        ecrivain = connecter(base, timeout=0)
        try:
            resultat.append(
                executer_avec_retry(
                    lambda: inserer_fichier(ecrivain, fichier),
                    tentatives=10,
                    delai_initial=0.1,
                )
            )
        except BaseException as erreur:  # noqa: BLE001 - remonte au test
            souci.append(erreur)
        finally:
            ecrivain.close()

    bloqueur = connecter(base, timeout=0)
    bloqueur.execute("BEGIN EXCLUSIVE")

    travailleur = threading.Thread(target=ecrire)
    travailleur.start()
    time.sleep(0.4)
    bloqueur.execute("ROLLBACK")
    travailleur.join(timeout=15)
    bloqueur.close()

    assert not travailleur.is_alive()
    assert souci == []
    assert resultat == [1]

    relecture = connecter(base)
    try:
        assert compter_transactions(relecture) == 1
    finally:
        relecture.close()
