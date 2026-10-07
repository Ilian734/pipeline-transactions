"""Chargement, validation et strategie de rejet global."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from fabriques import IBAN_A, IBAN_B
from pipeline.chargement import (
    charger_fichier,
    empreinte_contenu,
    lister_fichiers_csv,
    parser_lignes,
    parser_transaction,
)
from pipeline.erreurs import FichierInvalideError, LigneInvalideError
from pipeline.generation import ecrire_csv

LIGNE_VALIDE: dict[str, str | None] = {
    "datetime_transaction": "2024-03-01T09:12:00",
    "iban_origine": IBAN_A,
    "pays_source": "FR",
    "banque_source": "BNPPARIBAS",
    "iban_destinataire": IBAN_B,
    "pays_destinataire": "DE",
    "montant": "1250.00",
    "devise": "EUR",
}


def ligne(**remplacements: str | None) -> dict[str, str | None]:
    """Copie la ligne valide en remplacant quelques champs."""
    copie = dict(LIGNE_VALIDE)
    copie.update(remplacements)
    return copie


def test_parser_transaction_nominal() -> None:
    transaction = parser_transaction(LIGNE_VALIDE, numero=2)
    assert transaction["montant"] == Decimal("1250.00")
    assert transaction["iban_origine"] == IBAN_A
    assert transaction["devise"] == "EUR"


def test_parser_transaction_ne_modifie_pas_son_argument() -> None:
    entree = dict(LIGNE_VALIDE)
    parser_transaction(entree, numero=2)
    assert entree == LIGNE_VALIDE


@pytest.mark.parametrize(
    ("remplacement", "fragment_attendu"),
    [
        ({"montant": "mille euros"}, "non numerique"),
        ({"montant": ""}, "colonne vide"),
        ({"montant": None}, "colonne manquante"),
        ({"montant": "-10.00"}, "non strictement positif"),
        ({"montant": "0.00"}, "non strictement positif"),
        ({"montant": "10.123"}, "plus de deux decimales"),
        ({"montant": "NaN"}, "non fini"),
        ({"datetime_transaction": "pas une date"}, "date illisible"),
        ({"datetime_transaction": "2024-13-45"}, "date illisible"),
        ({"devise": "EURO"}, "devise mal formee"),
        ({"pays_source": "FRA"}, "pays_source mal forme"),
        ({"iban_origine": "XX"}, "iban_origine mal forme"),
        ({"banque_source": "   "}, "colonne vide"),
    ],
)
def test_lignes_invalides(
    remplacement: dict[str, str | None], fragment_attendu: str
) -> None:
    with pytest.raises(LigneInvalideError) as capture:
        parser_transaction(ligne(**remplacement), numero=7)
    assert fragment_attendu in str(capture.value)
    assert capture.value.numero_ligne == 7


def test_iban_origine_et_destinataire_identiques_refuses() -> None:
    with pytest.raises(LigneInvalideError, match="identiques"):
        parser_transaction(ligne(iban_destinataire=IBAN_A), numero=3)


def test_parser_lignes_numerote_a_partir_de_deux() -> None:
    """La ligne 1 est l'en-tete : la premiere transaction est la ligne 2."""
    with pytest.raises(LigneInvalideError) as capture:
        parser_lignes([LIGNE_VALIDE, ligne(montant="xxx")])
    assert capture.value.numero_ligne == 3


def test_empreinte_depend_du_contenu_pas_du_nom() -> None:
    assert empreinte_contenu(b"abc") == empreinte_contenu(b"abc")
    assert empreinte_contenu(b"abc") != empreinte_contenu(b"abd")


def test_charger_fichier_nominal(tmp_path: Path) -> None:
    chemin = tmp_path / "ok.csv"
    ecrire_csv(
        chemin,
        (
            (
                "2024-03-01T09:12:00", IBAN_A, "FR", "BNPPARIBAS",
                IBAN_B, "DE", "1250.00", "EUR",
            ),
        ),
    )
    fichier = charger_fichier(chemin)
    assert fichier["nom"] == "ok.csv"
    assert len(fichier["transactions"]) == 1
    assert len(fichier["empreinte"]) == 64


def test_rejet_global_une_ligne_invalide_fait_tomber_le_fichier(tmp_path: Path) -> None:
    """Strategie documentee : rien du fichier n'est conserve."""
    chemin = tmp_path / "melange.csv"
    ecrire_csv(
        chemin,
        (
            (
                "2024-03-01T09:12:00", IBAN_A, "FR", "BNPPARIBAS",
                IBAN_B, "DE", "1250.00", "EUR",
            ),
            (
                "2024-03-01T10:12:00", IBAN_A, "FR", "BNPPARIBAS",
                IBAN_B, "DE", "pas un montant", "EUR",
            ),
        ),
    )
    with pytest.raises(FichierInvalideError) as capture:
        charger_fichier(chemin)
    assert "non numerique" in str(capture.value)
    assert capture.value.nom == "melange.csv"


def test_entete_incomplete_rejetee(tmp_path: Path) -> None:
    chemin = tmp_path / "entete.csv"
    chemin.write_text("datetime_transaction,montant\n2024-03-01T09:00:00,10.00\n", "utf-8")
    with pytest.raises(FichierInvalideError, match="colonnes absentes"):
        charger_fichier(chemin)


def test_fichier_vide_rejete(tmp_path: Path) -> None:
    chemin = tmp_path / "vide.csv"
    chemin.write_text("", encoding="utf-8")
    with pytest.raises(FichierInvalideError, match="pas d'en-tete"):
        charger_fichier(chemin)


def test_fichier_sans_transaction_rejete(tmp_path: Path) -> None:
    chemin = tmp_path / "entete_seule.csv"
    ecrire_csv(chemin, ())
    with pytest.raises(FichierInvalideError, match="aucune transaction"):
        charger_fichier(chemin)


def test_lister_fichiers_csv_est_trie(tmp_path: Path) -> None:
    for nom in ("c.csv", "a.csv", "b.csv", "notes.txt"):
        (tmp_path / nom).write_text("", encoding="utf-8")
    assert [c.name for c in lister_fichiers_csv(tmp_path)] == ["a.csv", "b.csv", "c.csv"]
