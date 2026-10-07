"""Fabriques de donnees pour les tests.

Les tests unitaires de traitement ne lisent aucun fichier : leurs donnees
d'entree sont construites ici, en memoire.
"""

from __future__ import annotations

from decimal import Decimal

from pipeline.modeles import FichierCharge, Transaction

IBAN_A = "FR7630006000011234567890189"
IBAN_B = "DE89370400440532013000"
IBAN_C = "ES9121000418450200051332"
IBAN_D = "IT60X0542811101000000123456"


def fabriquer_transaction(
    montant: str,
    iban_origine: str = IBAN_A,
    iban_destinataire: str = IBAN_B,
    banque_source: str = "BNPPARIBAS",
    devise: str = "EUR",
    datetime_transaction: str = "2024-03-01T09:00:00",
    pays_source: str = "FR",
    pays_destinataire: str = "DE",
) -> Transaction:
    """Construit une transaction valide, montant donne sous forme de chaine."""
    return Transaction(
        datetime_transaction=datetime_transaction,
        iban_origine=iban_origine,
        pays_source=pays_source,
        banque_source=banque_source,
        iban_destinataire=iban_destinataire,
        pays_destinataire=pays_destinataire,
        montant=Decimal(montant),
        devise=devise,
    )


def fabriquer_fichier(
    transactions: list[Transaction],
    nom: str = "test.csv",
    empreinte: str = "a" * 64,
) -> FichierCharge:
    """Construit un `FichierCharge` sans passer par le disque."""
    return FichierCharge(nom=nom, empreinte=empreinte, transactions=transactions)
