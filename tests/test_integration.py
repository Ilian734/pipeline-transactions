"""Etape 5 : test d'integration de bout en bout.

Verifie que ce qui est reellement en base a les bonnes valeurs : nombre de
lignes, totaux par iban, nombre de transactions marquees, et absence de
doublons quand la pipeline est relancee.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import pytest

from pipeline.cli import ResultatPipeline, executer_pipeline
from pipeline.generation import (
    IBAN_BE,
    IBAN_BNP,
    IBAN_DE,
    IBAN_ES,
    IBAN_IT,
    IBAN_NL,
    IBAN_SG,
)
from pipeline.modeles import CleAgregat
from pipeline.persistance import (
    agregats_consolides,
    compter_au_dessus_du_seuil,
    compter_fichiers,
    compter_transactions,
    connecter,
)

NB_TRANSACTIONS_ATTENDU = 18
NB_FICHIERS_ATTENDU = 3
NB_AU_DESSUS_DU_SEUIL_ATTENDU = 5

ENVOYE_PAR_IBAN_ATTENDU = {
    CleAgregat(IBAN_BNP, "EUR"): Decimal("40580.73"),
    CleAgregat(IBAN_SG, "EUR"): Decimal("18822.15"),
    CleAgregat(IBAN_ES, "EUR"): Decimal("780.00"),
    CleAgregat(IBAN_DE, "EUR"): Decimal("5200.00"),
    CleAgregat(IBAN_IT, "EUR"): Decimal("640.40"),
}

ENVOYE_PAR_BANQUE_ATTENDU = {
    CleAgregat("BNPPARIBAS", "EUR"): Decimal("40580.73"),
    CleAgregat("SOCIETEGENERALE", "EUR"): Decimal("18822.15"),
    CleAgregat("CAIXABANK", "EUR"): Decimal("780.00"),
    CleAgregat("DEUTSCHEBANK", "EUR"): Decimal("5200.00"),
    CleAgregat("INTESASANPAOLO", "EUR"): Decimal("640.40"),
}

RECU_PAR_IBAN_ATTENDU = {
    CleAgregat(IBAN_BNP, "EUR"): Decimal("1420.40"),
    CleAgregat(IBAN_SG, "EUR"): Decimal("5200.00"),
    CleAgregat(IBAN_DE, "EUR"): Decimal("5180.85"),
    CleAgregat(IBAN_ES, "EUR"): Decimal("19450.50"),
    CleAgregat(IBAN_IT, "EUR"): Decimal("7420.74"),
    CleAgregat(IBAN_BE, "EUR"): Decimal("5099.99"),
    CleAgregat(IBAN_NL, "EUR"): Decimal("22250.80"),
}

TOTAL_GENERAL = Decimal("66023.28")


class Contexte(NamedTuple):
    base: Path
    donnees: Path
    resultat: ResultatPipeline


@pytest.fixture
def pipeline_executee(tmp_path: Path) -> Iterator[Contexte]:
    """Execute la pipeline complete dans un repertoire temporaire."""
    donnees = tmp_path / "donnees"
    base = tmp_path / "transactions.db"
    resultat = executer_pipeline(dossier_donnees=donnees, base=base)
    yield Contexte(base=base, donnees=donnees, resultat=resultat)


def test_la_pipeline_reussit(pipeline_executee: Contexte) -> None:
    resultat = pipeline_executee.resultat
    assert resultat.echecs == []
    assert resultat.code_retour == 0
    assert len(resultat.inseres) == NB_FICHIERS_ATTENDU


def test_trois_fichiers_csv_generes(pipeline_executee: Contexte) -> None:
    csvs = sorted(pipeline_executee.donnees.glob("*.csv"))
    assert len(csvs) == NB_FICHIERS_ATTENDU
    for chemin in csvs:
        nb_lignes = len(chemin.read_text(encoding="utf-8").strip().splitlines()) - 1
        assert 5 <= nb_lignes <= 10


def test_nombre_de_lignes_inserees(pipeline_executee: Contexte) -> None:
    connexion = connecter(pipeline_executee.base)
    try:
        assert compter_transactions(connexion) == NB_TRANSACTIONS_ATTENDU
        assert compter_fichiers(connexion) == NB_FICHIERS_ATTENDU
    finally:
        connexion.close()


def test_totaux_envoyes_par_iban(pipeline_executee: Contexte) -> None:
    connexion = connecter(pipeline_executee.base)
    try:
        assert agregats_consolides(connexion, "envoye_par_iban") == ENVOYE_PAR_IBAN_ATTENDU
    finally:
        connexion.close()


def test_totaux_envoyes_par_banque(pipeline_executee: Contexte) -> None:
    connexion = connecter(pipeline_executee.base)
    try:
        assert (
            agregats_consolides(connexion, "envoye_par_banque")
            == ENVOYE_PAR_BANQUE_ATTENDU
        )
    finally:
        connexion.close()


def test_totaux_recus_par_iban(pipeline_executee: Contexte) -> None:
    connexion = connecter(pipeline_executee.base)
    try:
        assert agregats_consolides(connexion, "recu_par_iban") == RECU_PAR_IBAN_ATTENDU
    finally:
        connexion.close()


def test_envoye_et_recu_s_equilibrent(pipeline_executee: Contexte) -> None:
    """Tout ce qui est envoye est recu : les deux totaux doivent coincider."""
    assert sum(ENVOYE_PAR_IBAN_ATTENDU.values()) == TOTAL_GENERAL
    assert sum(RECU_PAR_IBAN_ATTENDU.values()) == TOTAL_GENERAL


def test_nombre_de_transactions_au_dessus_du_seuil(pipeline_executee: Contexte) -> None:
    connexion = connecter(pipeline_executee.base)
    try:
        assert compter_au_dessus_du_seuil(connexion) == NB_AU_DESSUS_DU_SEUIL_ATTENDU
    finally:
        connexion.close()


def test_la_transaction_a_exactement_5000_n_est_pas_marquee(
    pipeline_executee: Contexte,
) -> None:
    connexion = connecter(pipeline_executee.base)
    try:
        ligne = connexion.execute(
            "SELECT au_dessus_du_seuil FROM transactions WHERE montant_centimes = 500000"
        ).fetchone()
        assert ligne is not None
        assert ligne["au_dessus_du_seuil"] == 0
    finally:
        connexion.close()


def test_relancer_la_pipeline_ne_cree_pas_de_doublons(
    pipeline_executee: Contexte,
) -> None:
    deuxieme = executer_pipeline(
        dossier_donnees=pipeline_executee.donnees, base=pipeline_executee.base
    )
    troisieme = executer_pipeline(
        dossier_donnees=pipeline_executee.donnees, base=pipeline_executee.base
    )

    assert deuxieme.inseres == []
    assert len(deuxieme.ignores) == NB_FICHIERS_ATTENDU
    assert deuxieme.code_retour == 0
    assert troisieme.inseres == []

    connexion = connecter(pipeline_executee.base)
    try:
        assert compter_transactions(connexion) == NB_TRANSACTIONS_ATTENDU
        assert compter_fichiers(connexion) == NB_FICHIERS_ATTENDU
        assert agregats_consolides(connexion, "envoye_par_iban") == ENVOYE_PAR_IBAN_ATTENDU
    finally:
        connexion.close()


def test_un_fichier_renomme_n_est_pas_retraite(pipeline_executee: Contexte) -> None:
    """L'identification porte sur le contenu, pas sur le nom du fichier."""
    source = sorted(pipeline_executee.donnees.glob("*.csv"))[0]
    (pipeline_executee.donnees / "copie_sous_un_autre_nom.csv").write_bytes(
        source.read_bytes()
    )

    resultat = executer_pipeline(
        dossier_donnees=pipeline_executee.donnees,
        base=pipeline_executee.base,
        generer=False,
    )

    assert resultat.inseres == []
    connexion = connecter(pipeline_executee.base)
    try:
        assert compter_transactions(connexion) == NB_TRANSACTIONS_ATTENDU
    finally:
        connexion.close()


def test_generation_reproductible(tmp_path: Path) -> None:
    """Deux generations successives produisent des octets identiques."""
    premier = tmp_path / "a"
    second = tmp_path / "b"
    executer_pipeline(dossier_donnees=premier, base=tmp_path / "a.db")
    executer_pipeline(dossier_donnees=second, base=tmp_path / "b.db")

    for chemin in sorted(premier.glob("*.csv")):
        assert chemin.read_bytes() == (second / chemin.name).read_bytes()
