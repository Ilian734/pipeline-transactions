"""Conversion Decimal <-> centimes."""

from __future__ import annotations

from decimal import Decimal

import pytest

from pipeline.montants import depuis_centimes, vers_centimes


@pytest.mark.parametrize(
    ("montant", "centimes"),
    [
        ("0.01", 1),
        ("1.00", 100),
        ("1250.00", 125000),
        ("7400.50", 740050),
        ("99.99", 9999),
    ],
)
def test_aller_retour_centimes(montant: str, centimes: int) -> None:
    assert vers_centimes(Decimal(montant)) == centimes
    assert depuis_centimes(centimes) == Decimal(montant)


def test_montant_trop_precis_est_refuse() -> None:
    with pytest.raises(ValueError, match="non representable"):
        vers_centimes(Decimal("10.123"))


def test_somme_decimale_exacte() -> None:
    """La raison d'etre de Decimal : 0.1 + 0.2 == 0.3 doit etre vrai."""
    total = Decimal("0.10") + Decimal("0.20")
    assert total == Decimal("0.30")
    assert vers_centimes(total) == 30
