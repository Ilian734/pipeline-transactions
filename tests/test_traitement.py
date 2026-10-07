"""Etape 2 : tests unitaires des fonctions de traitement.

Aucun de ces tests ne lit de fichier ni ne touche la base : les donnees sont
construites directement ici.
"""

from __future__ import annotations

from decimal import Decimal

from fabriques import IBAN_A, IBAN_B, IBAN_C, fabriquer_transaction
from pipeline.modeles import CleAgregat, Transaction
from pipeline.traitement import (
    compter_au_dessus_du_seuil,
    est_au_dessus_du_seuil,
    fusionner_agregats,
    marquer_transactions,
    total_envoye_par_banque,
    total_envoye_par_iban,
    total_recu_par_iban,
)


def jeu_de_base() -> list[Transaction]:
    return [
        fabriquer_transaction("1250.00", iban_origine=IBAN_A, iban_destinataire=IBAN_B),
        fabriquer_transaction("7400.50", iban_origine=IBAN_A, iban_destinataire=IBAN_C),
        fabriquer_transaction(
            "320.75",
            iban_origine=IBAN_B,
            iban_destinataire=IBAN_C,
            banque_source="DEUTSCHEBANK",
        ),
        fabriquer_transaction("980.25", iban_origine=IBAN_A, iban_destinataire=IBAN_B),
    ]


def test_total_envoye_par_iban() -> None:
    totaux = total_envoye_par_iban(jeu_de_base())
    assert totaux == {
        CleAgregat(IBAN_A, "EUR"): Decimal("9630.75"),
        CleAgregat(IBAN_B, "EUR"): Decimal("320.75"),
    }


def test_total_envoye_par_banque() -> None:
    totaux = total_envoye_par_banque(jeu_de_base())
    assert totaux == {
        CleAgregat("BNPPARIBAS", "EUR"): Decimal("9630.75"),
        CleAgregat("DEUTSCHEBANK", "EUR"): Decimal("320.75"),
    }


def test_total_recu_par_iban() -> None:
    totaux = total_recu_par_iban(jeu_de_base())
    assert totaux == {
        CleAgregat(IBAN_B, "EUR"): Decimal("2230.25"),
        CleAgregat(IBAN_C, "EUR"): Decimal("7721.25"),
    }


def test_agregats_sur_liste_vide() -> None:
    assert total_envoye_par_iban([]) == {}
    assert total_recu_par_iban([]) == {}
    assert compter_au_dessus_du_seuil([]) == 0


def test_seuil_est_une_comparaison_stricte() -> None:
    """Exactement 5000 n'est pas « au-dessus de 5000 »."""
    assert est_au_dessus_du_seuil(fabriquer_transaction("4999.99")) is False
    assert est_au_dessus_du_seuil(fabriquer_transaction("5000.00")) is False
    assert est_au_dessus_du_seuil(fabriquer_transaction("5000.01")) is True


def test_seuil_personnalise() -> None:
    transaction = fabriquer_transaction("150.00")
    assert est_au_dessus_du_seuil(transaction, Decimal("100")) is True
    assert est_au_dessus_du_seuil(transaction, Decimal("200")) is False


def test_marquer_transactions() -> None:
    transactions = [
        fabriquer_transaction("10.00"),
        fabriquer_transaction("9000.00"),
        fabriquer_transaction("5000.00"),
    ]
    assert [marque for _, marque in marquer_transactions(transactions)] == [
        False,
        True,
        False,
    ]
    assert compter_au_dessus_du_seuil(transactions) == 1


def test_les_fonctions_de_traitement_sont_pures() -> None:
    """Les arguments ne doivent etre ni modifies ni partages avec le resultat."""
    transactions = jeu_de_base()
    avant = [dict(t) for t in transactions]

    total_envoye_par_iban(transactions)
    total_envoye_par_banque(transactions)
    total_recu_par_iban(transactions)
    marquer_transactions(transactions)

    assert [dict(t) for t in transactions] == avant


def test_les_devises_ne_sont_jamais_melangees() -> None:
    """Sommer des EUR et des USD dans un meme total serait un bug."""
    transactions = [
        fabriquer_transaction("100.00", devise="EUR"),
        fabriquer_transaction("100.00", devise="USD"),
        fabriquer_transaction("50.00", devise="USD"),
    ]
    assert total_envoye_par_iban(transactions) == {
        CleAgregat(IBAN_A, "EUR"): Decimal("100.00"),
        CleAgregat(IBAN_A, "USD"): Decimal("150.00"),
    }


def test_sommes_sans_erreur_de_representation() -> None:
    """Dix fois 0.10 font exactement 1.00, ce que `float` ne garantit pas."""
    transactions = [fabriquer_transaction("0.10") for _ in range(10)]
    totaux = total_envoye_par_iban(transactions)
    assert totaux[CleAgregat(IBAN_A, "EUR")] == Decimal("1.00")


def test_fusionner_agregats() -> None:
    premier = {
        CleAgregat(IBAN_A, "EUR"): Decimal("100.00"),
        CleAgregat(IBAN_B, "EUR"): Decimal("50.00"),
    }
    second = {
        CleAgregat(IBAN_A, "EUR"): Decimal("25.50"),
        CleAgregat(IBAN_C, "EUR"): Decimal("10.00"),
    }
    assert fusionner_agregats([premier, second]) == {
        CleAgregat(IBAN_A, "EUR"): Decimal("125.50"),
        CleAgregat(IBAN_B, "EUR"): Decimal("50.00"),
        CleAgregat(IBAN_C, "EUR"): Decimal("10.00"),
    }
    assert premier[CleAgregat(IBAN_A, "EUR")] == Decimal("100.00")


def test_fusionner_agregats_vide() -> None:
    assert fusionner_agregats([]) == {}
