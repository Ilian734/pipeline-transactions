"""Etape 1 : generation des fichiers CSV de transactions.

Les donnees sont **en dur**, donc strictement reproductibles d'une execution a
l'autre : les totaux attendus par les tests d'integration ne bougent jamais.
Aucun `random` n'est utilise, pas meme avec une graine fixee.

Le jeu de donnees respecte les minima demandes :
  - 3 fichiers de 6, 7 et 5 transactions ;
  - 5 transactions dont le montant depasse 5000 ;
  - les ibans FR76...0189 et FR76...8765 reviennent sur plusieurs lignes,
    dans plusieurs fichiers ;
  - une transaction a exactement 5000.00, pour verrouiller la comparaison
    stricte du seuil ;
  - une seule devise (EUR), le multi-devises restant gere par le typage.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Final

from pipeline.modeles import COLONNES_ATTENDUES

LigneCsv = tuple[str, str, str, str, str, str, str, str]

IBAN_BNP: Final[str] = "FR7630006000011234567890189"
IBAN_SG: Final[str] = "FR7630003000507654321098765"
IBAN_DE: Final[str] = "DE89370400440532013000"
IBAN_ES: Final[str] = "ES9121000418450200051332"
IBAN_IT: Final[str] = "IT60X0542811101000000123456"
IBAN_BE: Final[str] = "BE68539007547034000000"
IBAN_NL: Final[str] = "NL91ABNA0417164300000"

FICHIERS: Final[dict[str, tuple[LigneCsv, ...]]] = {
    "transactions_2024-03-01.csv": (
        (
            "2024-03-01T09:12:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_DE, "DE", "1250.00", "EUR",
        ),
        (
            "2024-03-01T10:45:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_ES, "ES", "7400.50", "EUR",
        ),
        (
            "2024-03-01T11:30:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_IT, "IT", "320.75", "EUR",
        ),
        (
            "2024-03-01T14:05:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_DE, "DE", "980.25", "EUR",
        ),
        (
            "2024-03-01T15:20:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_BE, "BE", "5000.00", "EUR",
        ),
        (
            "2024-03-01T16:55:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_NL, "NL", "6250.80", "EUR",
        ),
    ),
    "transactions_2024-03-02.csv": (
        (
            "2024-03-02T08:05:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_IT, "IT", "2100.00", "EUR",
        ),
        (
            "2024-03-02T09:40:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_DE, "DE", "450.10", "EUR",
        ),
        (
            "2024-03-02T10:15:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_NL, "NL", "15000.00", "EUR",
        ),
        (
            "2024-03-02T11:50:00", IBAN_ES, "ES", "CAIXABANK",
            IBAN_BNP, "FR", "780.00", "EUR",
        ),
        (
            "2024-03-02T13:25:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_ES, "ES", "3300.00", "EUR",
        ),
        (
            "2024-03-02T15:10:00", IBAN_DE, "DE", "DEUTSCHEBANK",
            IBAN_SG, "FR", "5200.00", "EUR",
        ),
        (
            "2024-03-02T17:35:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_BE, "BE", "99.99", "EUR",
        ),
    ),
    "transactions_2024-03-03.csv": (
        (
            "2024-03-03T09:00:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_NL, "NL", "1000.00", "EUR",
        ),
        (
            "2024-03-03T10:20:00", IBAN_SG, "FR", "SOCIETEGENERALE",
            IBAN_DE, "DE", "2500.50", "EUR",
        ),
        (
            "2024-03-03T12:45:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_ES, "ES", "8750.00", "EUR",
        ),
        (
            "2024-03-03T14:30:00", IBAN_IT, "IT", "INTESASANPAOLO",
            IBAN_BNP, "FR", "640.40", "EUR",
        ),
        (
            "2024-03-03T16:05:00", IBAN_BNP, "FR", "BNPPARIBAS",
            IBAN_IT, "IT", "4999.99", "EUR",
        ),
    ),
}

NOM_FICHIER_CORROMPU: Final[str] = "transactions_2024-03-04_corrompu.csv"

FICHIER_CORROMPU: Final[tuple[LigneCsv, ...]] = (
    (
        "2024-03-04T09:00:00", IBAN_BNP, "FR", "BNPPARIBAS",
        IBAN_DE, "DE", "1500.00", "EUR",
    ),
    (
        "2024-03-04T10:00:00", IBAN_SG, "FR", "SOCIETEGENERALE",
        IBAN_ES, "ES", "mille euros", "EUR",
    ),
    (
        "2024-03-04T11:00:00", IBAN_BNP, "FR", "BNPPARIBAS",
        IBAN_NL, "NL", "6000.00", "EUR",
    ),
)
"""Fichier volontairement defectueux (montant non numerique sur la 2e ligne).

Il sert l'etape 6 : la premiere ligne est valide et la troisieme depasse le
seuil, donc un traitement partiel laisserait des traces visibles en base.
"""


def ecrire_csv(chemin: Path, lignes: tuple[LigneCsv, ...]) -> None:
    """Ecrit un CSV avec en-tete.

    `lineterminator="\\n"` est impose pour que l'empreinte SHA-256 du fichier
    soit identique sous Windows et sous Linux.
    """
    with chemin.open("w", encoding="utf-8", newline="") as flux:
        redacteur = csv.writer(flux, lineterminator="\n")
        redacteur.writerow(COLONNES_ATTENDUES)
        redacteur.writerows(lignes)


def generer_fichiers(dossier: Path, injecter_erreur: bool = False) -> list[Path]:
    """Ecrit les CSV dans `dossier` et renvoie leurs chemins, tries.

    Si `injecter_erreur` est vrai, un quatrieme fichier invalide est ajoute
    pour declencher le scenario d'echec de l'etape 6.
    """
    dossier.mkdir(parents=True, exist_ok=True)
    a_ecrire = dict(FICHIERS)
    if injecter_erreur:
        a_ecrire[NOM_FICHIER_CORROMPU] = FICHIER_CORROMPU
    chemins: list[Path] = []
    for nom, lignes in a_ecrire.items():
        chemin = dossier / nom
        ecrire_csv(chemin, lignes)
        chemins.append(chemin)
    return sorted(chemins)
