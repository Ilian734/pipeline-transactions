"""Types du domaine.

Un montant est une somme d'argent : il est represente par un `Decimal` en
memoire et par un entier de centimes en base. `float` est volontairement
absent de tout le projet (0.1 + 0.2 != 0.3).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final, NamedTuple, TypedDict

SEUIL_ALERTE: Final[Decimal] = Decimal("5000")
"""Au-dela de ce montant (strictement) une transaction est marquee."""

COLONNES_ATTENDUES: Final[tuple[str, ...]] = (
    "datetime_transaction",
    "iban_origine",
    "pays_source",
    "banque_source",
    "iban_destinataire",
    "pays_destinataire",
    "montant",
    "devise",
)


class Transaction(TypedDict):
    """Une transaction validee. `montant` est toujours strictement positif."""

    datetime_transaction: str
    iban_origine: str
    pays_source: str
    banque_source: str
    iban_destinataire: str
    pays_destinataire: str
    montant: Decimal
    devise: str


class TransactionMarquee(TypedDict):
    """Une transaction accompagnee du drapeau « montant > SEUIL_ALERTE »."""

    transaction: Transaction
    au_dessus_du_seuil: bool


class CleAgregat(NamedTuple):
    """Cle d'agregation.

    La devise fait partie de la cle : additionner des EUR et des USD dans un
    meme total serait un bug, meme si le jeu de donnees genere est mono-devise.
    """

    valeur: str
    devise: str


Agregats = dict[CleAgregat, Decimal]


class FichierCharge(TypedDict):
    """Le contenu valide d'un fichier CSV, plus son empreinte de contenu."""

    nom: str
    empreinte: str
    transactions: list[Transaction]
