"""Etape 4 : la pipeline, derriere une seule commande.

Enchaine generation des CSV, chargement, traitement, creation de la base et
insertion. Sort avec un code de retour non nul des qu'un fichier a echoue.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

from pipeline.chargement import charger_fichier, lister_fichiers_csv
from pipeline.erreurs import ErreurPipeline
from pipeline.generation import generer_fichiers
from pipeline.modeles import SEUIL_ALERTE
from pipeline.persistance import (
    TYPES_AGREGAT,
    agregats_consolides,
    compter_au_dessus_du_seuil,
    compter_transactions,
    connecter,
    creer_schema,
    executer_avec_retry,
    inserer_fichier,
)

_journal = logging.getLogger("pipeline")

DOSSIER_DONNEES_PAR_DEFAUT = Path("donnees")
BASE_PAR_DEFAUT = Path("transactions.db")


class EchecFichier(NamedTuple):
    """Un fichier qui n'a pas pu etre traite, et pourquoi."""

    nom: str
    raison: str


class ResultatPipeline(NamedTuple):
    """Bilan d'une execution complete."""

    inseres: list[str]
    ignores: list[str]
    echecs: list[EchecFichier]

    @property
    def code_retour(self) -> int:
        """0 si tout est passe, 1 des qu'un fichier a echoue."""
        return 1 if self.echecs else 0


def traiter_fichier(
    connexion: sqlite3.Connection,
    chemin: Path,
    seuil: Decimal = SEUIL_ALERTE,
    tentatives: int = 3,
) -> int | None:
    """Charge puis insere un fichier, avec retry sur erreur transitoire.

    Le chargement est volontairement hors du retry : une erreur de parsing est
    deterministe, la rejouer ne changerait rien.
    """
    fichier = charger_fichier(chemin)
    return executer_avec_retry(
        lambda: inserer_fichier(connexion, fichier, seuil), tentatives=tentatives
    )


def executer_pipeline(
    dossier_donnees: Path = DOSSIER_DONNEES_PAR_DEFAUT,
    base: Path = BASE_PAR_DEFAUT,
    generer: bool = True,
    injecter_erreur: bool = False,
    seuil: Decimal = SEUIL_ALERTE,
) -> ResultatPipeline:
    """Deroule la pipeline complete et renvoie son bilan.

    Un fichier en echec n'interrompt pas les suivants : chaque fichier est une
    unite de travail independante et atomique. Le bilan final porte le code de
    retour.
    """
    if generer:
        generer_fichiers(dossier_donnees, injecter_erreur=injecter_erreur)
        _journal.info("fichiers generes dans %s", dossier_donnees)

    inseres: list[str] = []
    ignores: list[str] = []
    echecs: list[EchecFichier] = []

    base.parent.mkdir(parents=True, exist_ok=True)
    connexion = connecter(base)
    try:
        creer_schema(connexion)
        for chemin in lister_fichiers_csv(dossier_donnees):
            try:
                fichier_id = traiter_fichier(connexion, chemin, seuil)
            except (ErreurPipeline, sqlite3.Error, ValueError) as erreur:
                _journal.error("echec sur %s : %s", chemin.name, erreur)
                echecs.append(EchecFichier(nom=chemin.name, raison=str(erreur)))
                continue
            if fichier_id is None:
                _journal.info("%s deja traite, ignore", chemin.name)
                ignores.append(chemin.name)
            else:
                _journal.info("%s insere (id=%d)", chemin.name, fichier_id)
                inseres.append(chemin.name)
    finally:
        connexion.close()

    return ResultatPipeline(inseres=inseres, ignores=ignores, echecs=echecs)


def afficher_rapport(base: Path) -> None:
    """Affiche les agregats consolides, tous fichiers confondus."""
    connexion = connecter(base)
    try:
        print(f"transactions en base       : {compter_transactions(connexion)}")
        print(f"transactions > {SEUIL_ALERTE} : {compter_au_dessus_du_seuil(connexion)}")
        for type_agregat in TYPES_AGREGAT:
            print(f"\n--- {type_agregat} (consolide) ---")
            for cle, total in sorted(agregats_consolides(connexion, type_agregat).items()):
                print(f"  {cle.valeur:<32} {total:>12} {cle.devise}")
    finally:
        connexion.close()


def construire_parseur() -> argparse.ArgumentParser:
    """Definit les options de la ligne de commande."""
    parseur = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Pipeline de traitement de transactions financieres.",
    )
    parseur.add_argument(
        "--donnees",
        type=Path,
        default=DOSSIER_DONNEES_PAR_DEFAUT,
        help="dossier des fichiers CSV (defaut: %(default)s)",
    )
    parseur.add_argument(
        "--base",
        type=Path,
        default=BASE_PAR_DEFAUT,
        help="chemin de la base SQLite (defaut: %(default)s)",
    )
    parseur.add_argument(
        "--sans-generation",
        action="store_true",
        help="ne pas regenerer les CSV, traiter ceux deja presents",
    )
    parseur.add_argument(
        "--injecter-erreur",
        action="store_true",
        help="ajouter un CSV invalide pour demontrer le comportement en echec",
    )
    parseur.add_argument(
        "--rapport",
        action="store_true",
        help="afficher les agregats consolides a la fin",
    )
    parseur.add_argument(
        "--verbeux",
        action="store_true",
        help="passer le journal en niveau DEBUG",
    )
    return parseur


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entree. Renvoie le code de retour du processus."""
    options = construire_parseur().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if options.verbeux else logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    resultat = executer_pipeline(
        dossier_donnees=options.donnees,
        base=options.base,
        generer=not options.sans_generation,
        injecter_erreur=options.injecter_erreur,
    )

    print(
        f"fichiers inseres : {len(resultat.inseres)} | "
        f"deja traites : {len(resultat.ignores)} | "
        f"en echec : {len(resultat.echecs)}"
    )
    for echec in resultat.echecs:
        print(f"ECHEC {echec.nom} : {echec.raison}", file=sys.stderr)

    if options.rapport:
        afficher_rapport(options.base)

    return resultat.code_retour
