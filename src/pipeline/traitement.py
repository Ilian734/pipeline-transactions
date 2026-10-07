"""Traitements purs sur les transactions.

Toutes les fonctions de ce module sont pures : aucune lecture de fichier,
aucun `print`, aucune modification des arguments recus. Elles sont donc
testables sans toucher au disque ni a la base.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from decimal import Decimal

from pipeline.modeles import SEUIL_ALERTE, Agregats, CleAgregat, Transaction


def _agreger(
    transactions: Iterable[Transaction],
    cle: Callable[[Transaction], str],
) -> Agregats:
    totaux: Agregats = {}
    for transaction in transactions:
        index = CleAgregat(valeur=cle(transaction), devise=transaction["devise"])
        totaux[index] = totaux.get(index, Decimal(0)) + transaction["montant"]
    return totaux


def total_envoye_par_iban(transactions: Sequence[Transaction]) -> Agregats:
    """Somme des montants envoyes, par iban d'origine et par devise."""
    return _agreger(transactions, lambda t: t["iban_origine"])


def total_envoye_par_banque(transactions: Sequence[Transaction]) -> Agregats:
    """Somme des montants envoyes, par banque source et par devise."""
    return _agreger(transactions, lambda t: t["banque_source"])


def total_recu_par_iban(transactions: Sequence[Transaction]) -> Agregats:
    """Somme des montants recus, par iban destinataire et par devise."""
    return _agreger(transactions, lambda t: t["iban_destinataire"])


def est_au_dessus_du_seuil(
    transaction: Transaction, seuil: Decimal = SEUIL_ALERTE
) -> bool:
    """Vrai si le montant depasse *strictement* le seuil.

    Une transaction exactement egale au seuil n'est pas marquee.
    """
    return transaction["montant"] > seuil


def marquer_transactions(
    transactions: Sequence[Transaction], seuil: Decimal = SEUIL_ALERTE
) -> list[tuple[Transaction, bool]]:
    """Associe a chaque transaction son drapeau de depassement.

    Renvoie de nouveaux tuples : la sequence d'entree n'est pas modifiee.
    """
    return [(t, est_au_dessus_du_seuil(t, seuil)) for t in transactions]


def compter_au_dessus_du_seuil(
    transactions: Sequence[Transaction], seuil: Decimal = SEUIL_ALERTE
) -> int:
    """Nombre de transactions marquees."""
    return sum(1 for t in transactions if est_au_dessus_du_seuil(t, seuil))


def fusionner_agregats(agregats: Iterable[Agregats]) -> Agregats:
    """Consolide plusieurs agregats en un seul, sans modifier les entrees."""
    consolide: Agregats = {}
    for partiel in agregats:
        for cle, total in partiel.items():
            consolide[cle] = consolide.get(cle, Decimal(0)) + total
    return consolide
