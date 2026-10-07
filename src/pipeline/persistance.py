"""Persistance SQLite : schema, insertion atomique, idempotence, retry."""

from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Final, TypeVar

from pipeline.modeles import SEUIL_ALERTE, Agregats, CleAgregat, FichierCharge
from pipeline.montants import depuis_centimes, vers_centimes
from pipeline.traitement import (
    est_au_dessus_du_seuil,
    total_envoye_par_banque,
    total_envoye_par_iban,
    total_recu_par_iban,
)

_journal = logging.getLogger(__name__)

T = TypeVar("T")

TYPES_AGREGAT: Final[tuple[str, ...]] = (
    "envoye_par_iban",
    "envoye_par_banque",
    "recu_par_iban",
)

SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS fichiers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nom             TEXT    NOT NULL,
    empreinte       TEXT    NOT NULL UNIQUE,
    date_traitement TEXT    NOT NULL,
    nb_transactions INTEGER NOT NULL CHECK (nb_transactions > 0)
);

CREATE TABLE IF NOT EXISTS transactions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier_id           INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    datetime_transaction TEXT    NOT NULL,
    iban_origine         TEXT    NOT NULL,
    pays_source          TEXT    NOT NULL,
    banque_source        TEXT    NOT NULL,
    iban_destinataire    TEXT    NOT NULL,
    pays_destinataire    TEXT    NOT NULL,
    montant_centimes     INTEGER NOT NULL CHECK (montant_centimes > 0),
    devise               TEXT    NOT NULL,
    au_dessus_du_seuil   INTEGER NOT NULL CHECK (au_dessus_du_seuil IN (0, 1))
);

CREATE TABLE IF NOT EXISTS agregats (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    fichier_id     INTEGER NOT NULL REFERENCES fichiers(id) ON DELETE CASCADE,
    type_agregat   TEXT    NOT NULL
        CHECK (type_agregat IN ('envoye_par_iban', 'envoye_par_banque', 'recu_par_iban')),
    cle            TEXT    NOT NULL,
    devise         TEXT    NOT NULL,
    total_centimes INTEGER NOT NULL,
    UNIQUE (fichier_id, type_agregat, cle, devise)
);

CREATE INDEX IF NOT EXISTS idx_transactions_fichier ON transactions(fichier_id);
CREATE INDEX IF NOT EXISTS idx_transactions_origine ON transactions(iban_origine);
CREATE INDEX IF NOT EXISTS idx_agregats_type ON agregats(type_agregat, cle, devise);
"""


def connecter(chemin: Path | str, timeout: float = 5.0) -> sqlite3.Connection:
    """Ouvre une connexion configuree pour le projet.

    `isolation_level=None` desactive la gestion implicite des transactions de
    `sqlite3` : les BEGIN/COMMIT/ROLLBACK sont ecrits explicitement, ce qui est
    indispensable pour garantir l'atomicite par fichier.
    """
    connexion = sqlite3.connect(chemin, timeout=timeout, isolation_level=None)
    connexion.row_factory = sqlite3.Row
    connexion.execute("PRAGMA foreign_keys = ON")
    return connexion


def creer_schema(connexion: sqlite3.Connection) -> None:
    """Cree les tables si elles n'existent pas (operation idempotente)."""
    connexion.executescript(SCHEMA)


def est_erreur_retryable(erreur: BaseException) -> bool:
    """Distingue les erreurs transitoires des erreurs deterministes.

    Seule une `OperationalError` de contention (base verrouillee / occupee)
    est retryable : l'etat de la base changera peut-etre tout seul. Une
    `IntegrityError`, une `ProgrammingError` ou une `OperationalError` de
    schema ("no such table") se reproduiront a l'identique.
    """
    if not isinstance(erreur, sqlite3.OperationalError):
        return False
    message = str(erreur).lower()
    return "locked" in message or "busy" in message


def executer_avec_retry(
    operation: Callable[[], T],
    tentatives: int = 3,
    delai_initial: float = 0.1,
    dormir: Callable[[float], None] = time.sleep,
) -> T:
    """Rejoue `operation` tant que l'erreur rencontree est transitoire.

    Le delai double a chaque essai (backoff exponentiel). Une erreur non
    retryable est relancee immediatement, sans consommer d'essai.
    """
    if tentatives < 1:
        raise ValueError("tentatives doit valoir au moins 1")
    delai = delai_initial
    for essai in range(1, tentatives + 1):
        try:
            return operation()
        except sqlite3.Error as erreur:
            if not est_erreur_retryable(erreur) or essai == tentatives:
                raise
            _journal.warning(
                "erreur transitoire (essai %d/%d) : %s", essai, tentatives, erreur
            )
            dormir(delai)
            delai *= 2
    raise AssertionError("boucle de retry sortie sans resultat")


def fichier_deja_traite(connexion: sqlite3.Connection, empreinte: str) -> bool:
    """Vrai si un fichier de meme *contenu* a deja ete insere."""
    curseur = connexion.execute(
        "SELECT 1 FROM fichiers WHERE empreinte = ?", (empreinte,)
    )
    return curseur.fetchone() is not None


def _inserer_agregats(
    connexion: sqlite3.Connection,
    fichier_id: int,
    type_agregat: str,
    agregats: Agregats,
) -> None:
    connexion.executemany(
        "INSERT INTO agregats (fichier_id, type_agregat, cle, devise, total_centimes)"
        " VALUES (?, ?, ?, ?, ?)",
        [
            (fichier_id, type_agregat, cle.valeur, cle.devise, vers_centimes(total))
            for cle, total in sorted(agregats.items())
        ],
    )


def inserer_fichier(
    connexion: sqlite3.Connection,
    fichier: FichierCharge,
    seuil: Decimal = SEUIL_ALERTE,
) -> int | None:
    """Insere un fichier, ses transactions et ses agregats, de facon atomique.

    Renvoie l'identifiant du fichier insere, ou `None` si ce contenu avait
    deja ete traite (idempotence). En cas d'erreur, un ROLLBACK ramene la base
    a son etat initial : aucune insertion partielle n'est possible.
    """
    transactions = fichier["transactions"]
    if not transactions:
        raise ValueError("un fichier sans transaction ne doit pas etre insere")

    connexion.execute("BEGIN IMMEDIATE")
    try:
        if fichier_deja_traite(connexion, fichier["empreinte"]):
            connexion.execute("ROLLBACK")
            _journal.info(
                "fichier %s deja traite (empreinte %s), ignore",
                fichier["nom"],
                fichier["empreinte"][:12],
            )
            return None

        curseur = connexion.execute(
            "INSERT INTO fichiers (nom, empreinte, date_traitement, nb_transactions)"
            " VALUES (?, ?, ?, ?)",
            (
                fichier["nom"],
                fichier["empreinte"],
                datetime.now(UTC).isoformat(),
                len(transactions),
            ),
        )
        fichier_id = curseur.lastrowid
        if fichier_id is None:
            raise sqlite3.DatabaseError("insertion du fichier sans identifiant")

        connexion.executemany(
            "INSERT INTO transactions ("
            " fichier_id, datetime_transaction, iban_origine, pays_source,"
            " banque_source, iban_destinataire, pays_destinataire,"
            " montant_centimes, devise, au_dessus_du_seuil"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    fichier_id,
                    t["datetime_transaction"],
                    t["iban_origine"],
                    t["pays_source"],
                    t["banque_source"],
                    t["iban_destinataire"],
                    t["pays_destinataire"],
                    vers_centimes(t["montant"]),
                    t["devise"],
                    int(est_au_dessus_du_seuil(t, seuil)),
                )
                for t in transactions
            ],
        )

        _inserer_agregats(
            connexion, fichier_id, "envoye_par_iban", total_envoye_par_iban(transactions)
        )
        _inserer_agregats(
            connexion,
            fichier_id,
            "envoye_par_banque",
            total_envoye_par_banque(transactions),
        )
        _inserer_agregats(
            connexion, fichier_id, "recu_par_iban", total_recu_par_iban(transactions)
        )

        connexion.execute("COMMIT")
    except BaseException:
        connexion.execute("ROLLBACK")
        raise
    return fichier_id


def compter_transactions(connexion: sqlite3.Connection) -> int:
    """Nombre total de transactions en base."""
    ligne = connexion.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()
    return int(ligne["n"])


def compter_fichiers(connexion: sqlite3.Connection) -> int:
    """Nombre de fichiers distincts deja traites."""
    ligne = connexion.execute("SELECT COUNT(*) AS n FROM fichiers").fetchone()
    return int(ligne["n"])


def compter_au_dessus_du_seuil(connexion: sqlite3.Connection) -> int:
    """Nombre de transactions marquees en base."""
    ligne = connexion.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE au_dessus_du_seuil = 1"
    ).fetchone()
    return int(ligne["n"])


def agregats_consolides(connexion: sqlite3.Connection, type_agregat: str) -> Agregats:
    """Agregats recalcules tous fichiers confondus, directement en SQL."""
    if type_agregat not in TYPES_AGREGAT:
        raise ValueError(f"type d'agregat inconnu : {type_agregat!r}")
    lignes = connexion.execute(
        "SELECT cle, devise, SUM(total_centimes) AS total FROM agregats"
        " WHERE type_agregat = ? GROUP BY cle, devise ORDER BY cle, devise",
        (type_agregat,),
    ).fetchall()
    return {
        CleAgregat(
            valeur=str(ligne["cle"]), devise=str(ligne["devise"])
        ): depuis_centimes(int(ligne["total"]))
        for ligne in lignes
    }
