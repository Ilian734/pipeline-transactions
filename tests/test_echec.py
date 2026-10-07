"""Etape 6 : comportement de la pipeline en cas d'echec.

Le code de retour doit etre non nul et la base doit rester propre : aucune
insertion partielle du fichier en echec.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pipeline.cli import executer_pipeline
from pipeline.generation import NOM_FICHIER_CORROMPU
from pipeline.persistance import (
    compter_au_dessus_du_seuil,
    compter_fichiers,
    compter_transactions,
    connecter,
)

RACINE = Path(__file__).resolve().parents[1]
NB_TRANSACTIONS_VALIDES = 18
NB_FICHIERS_VALIDES = 3


def test_code_de_retour_non_nul_en_cas_d_echec(tmp_path: Path) -> None:
    resultat = executer_pipeline(
        dossier_donnees=tmp_path / "donnees",
        base=tmp_path / "transactions.db",
        injecter_erreur=True,
    )

    assert resultat.code_retour != 0
    assert len(resultat.echecs) == 1
    assert resultat.echecs[0].nom == NOM_FICHIER_CORROMPU
    assert "non numerique" in resultat.echecs[0].raison


def test_la_base_reste_propre_apres_un_echec(tmp_path: Path) -> None:
    """Le fichier corrompu a une 1re ligne valide : elle ne doit pas etre en base."""
    base = tmp_path / "transactions.db"
    executer_pipeline(
        dossier_donnees=tmp_path / "donnees", base=base, injecter_erreur=True
    )

    connexion = connecter(base)
    try:
        assert compter_transactions(connexion) == NB_TRANSACTIONS_VALIDES
        assert compter_fichiers(connexion) == NB_FICHIERS_VALIDES
        assert compter_au_dessus_du_seuil(connexion) == 5

        noms = {
            str(ligne["nom"]) for ligne in connexion.execute("SELECT nom FROM fichiers")
        }
        assert NOM_FICHIER_CORROMPU not in noms

        orphelines = connexion.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE montant_centimes IN (150000, 600000)"
        ).fetchone()
        assert orphelines["n"] == 0
    finally:
        connexion.close()


def test_les_fichiers_valides_passent_malgre_l_echec(tmp_path: Path) -> None:
    """Un fichier en echec n'empeche pas les autres d'etre traites."""
    resultat = executer_pipeline(
        dossier_donnees=tmp_path / "donnees",
        base=tmp_path / "transactions.db",
        injecter_erreur=True,
    )
    assert len(resultat.inseres) == NB_FICHIERS_VALIDES


def test_relance_apres_echec_reste_coherente(tmp_path: Path) -> None:
    """Un retry complet ne duplique rien et echoue toujours sur le meme fichier."""
    donnees = tmp_path / "donnees"
    base = tmp_path / "transactions.db"
    executer_pipeline(dossier_donnees=donnees, base=base, injecter_erreur=True)
    second = executer_pipeline(dossier_donnees=donnees, base=base, injecter_erreur=True)

    assert second.code_retour != 0
    assert second.inseres == []
    assert len(second.ignores) == NB_FICHIERS_VALIDES

    connexion = connecter(base)
    try:
        assert compter_transactions(connexion) == NB_TRANSACTIONS_VALIDES
    finally:
        connexion.close()


def test_code_de_retour_du_processus(tmp_path: Path) -> None:
    """Le vrai processus `python -m pipeline` sort bien avec un statut non nul."""
    environnement = dict(os.environ)
    environnement["PYTHONPATH"] = str(RACINE / "src")

    def lancer(sous_dossier: str, *options: str) -> subprocess.CompletedProcess[str]:
        racine = tmp_path / sous_dossier
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pipeline",
                "--donnees",
                str(racine / "donnees"),
                "--base",
                str(racine / "transactions.db"),
                *options,
            ],
            capture_output=True,
            text=True,
            env=environnement,
            check=False,
        )

    echec = lancer("ko", "--injecter-erreur")
    assert echec.returncode == 1
    assert "ECHEC" in echec.stderr

    succes = lancer("ok")
    assert succes.returncode == 0
    assert "en echec : 0" in succes.stdout
