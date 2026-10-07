"""Etape 3 : schema, atomicite de l'insertion, idempotence."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from fabriques import IBAN_A, IBAN_B, fabriquer_fichier, fabriquer_transaction
from pipeline.modeles import CleAgregat
from pipeline.persistance import (
    agregats_consolides,
    compter_au_dessus_du_seuil,
    compter_fichiers,
    compter_transactions,
    connecter,
    creer_schema,
    fichier_deja_traite,
    inserer_fichier,
)


@pytest.fixture
def connexion() -> Iterator[sqlite3.Connection]:
    """Base en memoire, recreee pour chaque test."""
    conn = connecter(":memory:")
    creer_schema(conn)
    yield conn
    conn.close()


def test_creer_schema_est_idempotent(connexion: sqlite3.Connection) -> None:
    creer_schema(connexion)
    creer_schema(connexion)
    tables = {
        str(ligne["name"])
        for ligne in connexion.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"fichiers", "transactions", "agregats"} <= tables


def test_insertion_nominale(connexion: sqlite3.Connection) -> None:
    fichier = fabriquer_fichier(
        [
            fabriquer_transaction("1250.00"),
            fabriquer_transaction("7400.50", iban_destinataire=IBAN_B),
        ]
    )
    fichier_id = inserer_fichier(connexion, fichier)

    assert fichier_id is not None
    assert compter_fichiers(connexion) == 1
    assert compter_transactions(connexion) == 2
    assert compter_au_dessus_du_seuil(connexion) == 1


def test_montants_stockes_en_centimes(connexion: sqlite3.Connection) -> None:
    """Aucun REAL en base : le montant est un entier exact."""
    inserer_fichier(connexion, fabriquer_fichier([fabriquer_transaction("7400.50")]))
    ligne = connexion.execute("SELECT montant_centimes FROM transactions").fetchone()
    assert ligne["montant_centimes"] == 740050
    assert isinstance(ligne["montant_centimes"], int)


def test_agregats_persistes(connexion: sqlite3.Connection) -> None:
    inserer_fichier(
        connexion,
        fabriquer_fichier(
            [fabriquer_transaction("100.00"), fabriquer_transaction("25.50")]
        ),
    )
    assert agregats_consolides(connexion, "envoye_par_iban") == {
        CleAgregat(IBAN_A, "EUR"): Decimal("125.50")
    }


def test_type_agregat_inconnu_refuse(connexion: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="type d'agregat inconnu"):
        agregats_consolides(connexion, "inexistant")


def test_idempotence_meme_contenu(connexion: sqlite3.Connection) -> None:
    fichier = fabriquer_fichier([fabriquer_transaction("100.00")])

    assert inserer_fichier(connexion, fichier) is not None
    assert inserer_fichier(connexion, fichier) is None

    assert compter_fichiers(connexion) == 1
    assert compter_transactions(connexion) == 1


def test_idempotence_meme_contenu_nom_different(connexion: sqlite3.Connection) -> None:
    """Un meme contenu sous deux noms ne doit etre traite qu'une fois."""
    transactions = [fabriquer_transaction("100.00")]
    empreinte = "b" * 64
    inserer_fichier(connexion, fabriquer_fichier(transactions, "lot1.csv", empreinte))
    second = inserer_fichier(
        connexion, fabriquer_fichier(transactions, "lot1_copie.csv", empreinte)
    )

    assert second is None
    assert compter_fichiers(connexion) == 1


def test_contenus_differents_meme_nom_sont_deux_fichiers(
    connexion: sqlite3.Connection,
) -> None:
    """Un meme nom peut designer deux contenus : les deux doivent passer."""
    inserer_fichier(
        connexion,
        fabriquer_fichier([fabriquer_transaction("100.00")], "lot.csv", "c" * 64),
    )
    inserer_fichier(
        connexion,
        fabriquer_fichier([fabriquer_transaction("200.00")], "lot.csv", "d" * 64),
    )
    assert compter_fichiers(connexion) == 2
    assert compter_transactions(connexion) == 2


def test_fichier_deja_traite(connexion: sqlite3.Connection) -> None:
    empreinte = "e" * 64
    assert fichier_deja_traite(connexion, empreinte) is False
    inserer_fichier(
        connexion, fabriquer_fichier([fabriquer_transaction("1.00")], "x.csv", empreinte)
    )
    assert fichier_deja_traite(connexion, empreinte) is True


def test_insertion_atomique_rien_ne_reste_en_cas_d_echec(
    connexion: sqlite3.Connection,
) -> None:
    """Le montant a trois decimales fait echouer l'insertion en cours de route.

    La ligne de la table `fichiers`, deja inseree a ce moment-la, doit avoir
    disparu : pas d'insertion partielle.
    """
    valide = fabriquer_transaction("100.00")
    invalide = fabriquer_transaction("100.00")
    invalide["montant"] = Decimal("10.123")

    with pytest.raises(ValueError, match="non representable"):
        inserer_fichier(connexion, fabriquer_fichier([valide, invalide]))

    assert compter_fichiers(connexion) == 0
    assert compter_transactions(connexion) == 0
    assert connexion.execute("SELECT COUNT(*) AS n FROM agregats").fetchone()["n"] == 0


def test_la_base_reste_utilisable_apres_un_echec(connexion: sqlite3.Connection) -> None:
    invalide = fabriquer_transaction("100.00")
    invalide["montant"] = Decimal("10.123")
    with pytest.raises(ValueError):
        inserer_fichier(connexion, fabriquer_fichier([invalide], "ko.csv", "f" * 64))

    inserer_fichier(
        connexion, fabriquer_fichier([fabriquer_transaction("50.00")], "ok.csv", "0" * 64)
    )
    assert compter_transactions(connexion) == 1


def test_fichier_sans_transaction_refuse(connexion: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="sans transaction"):
        inserer_fichier(connexion, fabriquer_fichier([]))


def test_cles_etrangeres_actives(connexion: sqlite3.Connection) -> None:
    """PRAGMA foreign_keys = ON : une transaction orpheline est refusee."""
    with pytest.raises(sqlite3.IntegrityError):
        connexion.execute(
            "INSERT INTO transactions (fichier_id, datetime_transaction, iban_origine,"
            " pays_source, banque_source, iban_destinataire, pays_destinataire,"
            " montant_centimes, devise, au_dessus_du_seuil)"
            " VALUES (999, '2024-03-01T09:00:00', ?, 'FR', 'BNP', ?, 'DE', 100, 'EUR', 0)",
            (IBAN_A, IBAN_B),
        )


def test_empreinte_unique_en_base(connexion: sqlite3.Connection) -> None:
    """Filet de securite : la contrainte UNIQUE double la verification Python."""
    connexion.execute(
        "INSERT INTO fichiers (nom, empreinte, date_traitement, nb_transactions)"
        " VALUES ('a.csv', 'meme', '2024-01-01T00:00:00', 1)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connexion.execute(
            "INSERT INTO fichiers (nom, empreinte, date_traitement, nb_transactions)"
            " VALUES ('b.csv', 'meme', '2024-01-01T00:00:00', 1)"
        )


def test_insertion_sur_fichier_reel(tmp_path: Path) -> None:
    """La meme insertion fonctionne sur une base fichier, pas seulement en memoire."""
    base = tmp_path / "test.db"
    connexion = connecter(base)
    try:
        creer_schema(connexion)
        inserer_fichier(
            connexion, fabriquer_fichier([fabriquer_transaction("12.34")])
        )
    finally:
        connexion.close()

    relecture = connecter(base)
    try:
        assert compter_transactions(relecture) == 1
    finally:
        relecture.close()
