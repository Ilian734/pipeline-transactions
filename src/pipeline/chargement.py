"""Chargement et validation des fichiers CSV.

Ce module est le seul a toucher le systeme de fichiers pour la lecture des
donnees d'entree. Les fonctions de `pipeline.traitement` n'en dependent pas.

Strategie retenue pour les lignes invalides : **rejet global**. Une seule
ligne invalide fait echouer tout le fichier. Voir le README pour la
justification.
"""

from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pipeline.erreurs import FichierInvalideError, LigneInvalideError
from pipeline.modeles import COLONNES_ATTENDUES, FichierCharge, Transaction

_MOTIF_IBAN = re.compile(r"^[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}$")
_MOTIF_PAYS = re.compile(r"^[A-Z]{2}$")
_MOTIF_DEVISE = re.compile(r"^[A-Z]{3}$")


def _champ_obligatoire(ligne: Mapping[str, str | None], colonne: str, numero: int) -> str:
    valeur = ligne.get(colonne)
    if valeur is None:
        raise LigneInvalideError(numero, f"colonne manquante : {colonne}")
    valeur = valeur.strip()
    if not valeur:
        raise LigneInvalideError(numero, f"colonne vide : {colonne}")
    return valeur


def parser_montant(brut: str, numero: int) -> Decimal:
    """Convertit la colonne `montant` en `Decimal` strictement positif."""
    try:
        montant = Decimal(brut)
    except InvalidOperation:
        raise LigneInvalideError(numero, f"montant non numerique : {brut!r}") from None
    if not montant.is_finite():
        raise LigneInvalideError(numero, f"montant non fini : {brut!r}")
    if montant <= 0:
        raise LigneInvalideError(numero, f"montant non strictement positif : {brut!r}")
    exposant = montant.as_tuple().exponent
    if not isinstance(exposant, int) or exposant < -2:
        raise LigneInvalideError(numero, f"montant a plus de deux decimales : {brut!r}")
    return montant


def parser_date(brut: str, numero: int) -> str:
    """Valide une date ISO 8601 et la renvoie sous forme canonique."""
    try:
        horodatage = datetime.fromisoformat(brut)
    except ValueError:
        raise LigneInvalideError(numero, f"date illisible : {brut!r}") from None
    return horodatage.isoformat()


def parser_transaction(ligne: Mapping[str, str | None], numero: int) -> Transaction:
    """Convertit une ligne brute de CSV en `Transaction` validee.

    Fonction pure : elle ne lit aucun fichier et ne modifie pas `ligne`.
    """
    iban_origine = _champ_obligatoire(ligne, "iban_origine", numero)
    iban_destinataire = _champ_obligatoire(ligne, "iban_destinataire", numero)
    for etiquette, iban in (
        ("iban_origine", iban_origine),
        ("iban_destinataire", iban_destinataire),
    ):
        if not _MOTIF_IBAN.match(iban):
            raise LigneInvalideError(numero, f"{etiquette} mal forme : {iban!r}")
    if iban_origine == iban_destinataire:
        raise LigneInvalideError(numero, "iban origine et destinataire identiques")

    pays_source = _champ_obligatoire(ligne, "pays_source", numero)
    pays_destinataire = _champ_obligatoire(ligne, "pays_destinataire", numero)
    for etiquette, pays in (
        ("pays_source", pays_source),
        ("pays_destinataire", pays_destinataire),
    ):
        if not _MOTIF_PAYS.match(pays):
            raise LigneInvalideError(numero, f"{etiquette} mal forme : {pays!r}")

    devise = _champ_obligatoire(ligne, "devise", numero)
    if not _MOTIF_DEVISE.match(devise):
        raise LigneInvalideError(numero, f"devise mal formee : {devise!r}")

    return Transaction(
        datetime_transaction=parser_date(
            _champ_obligatoire(ligne, "datetime_transaction", numero), numero
        ),
        iban_origine=iban_origine,
        pays_source=pays_source,
        banque_source=_champ_obligatoire(ligne, "banque_source", numero),
        iban_destinataire=iban_destinataire,
        pays_destinataire=pays_destinataire,
        montant=parser_montant(_champ_obligatoire(ligne, "montant", numero), numero),
        devise=devise,
    )


def parser_lignes(lignes: Sequence[Mapping[str, str | None]]) -> list[Transaction]:
    """Parse une sequence de lignes brutes. Pure, testable sans fichier.

    La premiere ligne invalide interrompt le parsing (rejet global).
    Le numero reporte est celui de la ligne dans le fichier, en-tete comprise.
    """
    return [parser_transaction(ligne, numero) for numero, ligne in enumerate(lignes, start=2)]


def empreinte_contenu(octets: bytes) -> str:
    """SHA-256 du contenu brut : c'est lui qui identifie un fichier, pas son nom."""
    return hashlib.sha256(octets).hexdigest()


def lire_lignes_brutes(chemin: Path) -> list[dict[str, str | None]]:
    """Lit un CSV et renvoie ses lignes telles quelles, sans validation."""
    with chemin.open("r", encoding="utf-8", newline="") as flux:
        lecteur = csv.DictReader(flux)
        if lecteur.fieldnames is None:
            raise FichierInvalideError(chemin.name, "fichier vide (pas d'en-tete)")
        manquantes = [c for c in COLONNES_ATTENDUES if c not in lecteur.fieldnames]
        if manquantes:
            raise FichierInvalideError(
                chemin.name, f"colonnes absentes de l'en-tete : {', '.join(manquantes)}"
            )
        return [dict(ligne) for ligne in lecteur]


def charger_fichier(chemin: Path) -> FichierCharge:
    """Charge un CSV complet.

    Leve `FichierInvalideError` si une seule ligne est invalide : aucune
    transaction du fichier n'est alors retournee.
    """
    octets = chemin.read_bytes()
    lignes = lire_lignes_brutes(chemin)
    if not lignes:
        raise FichierInvalideError(chemin.name, "aucune transaction")
    try:
        transactions = parser_lignes(lignes)
    except LigneInvalideError as erreur:
        raise FichierInvalideError(chemin.name, str(erreur)) from erreur
    return FichierCharge(
        nom=chemin.name,
        empreinte=empreinte_contenu(octets),
        transactions=transactions,
    )


def lister_fichiers_csv(dossier: Path) -> list[Path]:
    """Liste les CSV d'un dossier, dans un ordre stable."""
    return sorted(dossier.glob("*.csv"))
