"""Conversion entre `Decimal` et entiers de centimes.

SQLite n'a pas de type decimal : stocker un montant en REAL reintroduirait
l'imprecision du binaire. Les montants sont donc persistes en centimes
(INTEGER) et reconvertis a la lecture.
"""

from __future__ import annotations

from decimal import Decimal

CENT: Decimal = Decimal("0.01")


def vers_centimes(montant: Decimal) -> int:
    """Convertit un montant en centimes.

    Leve `ValueError` si le montant a plus de deux decimales, ce qui signale
    une donnee hors du domaine monetaire attendu plutot qu'un arrondi silencieux.
    """
    quantifie = montant.quantize(CENT)
    if quantifie != montant:
        raise ValueError(f"montant non representable en centimes : {montant}")
    return int(quantifie.scaleb(2))


def depuis_centimes(centimes: int) -> Decimal:
    """Reconstruit un montant a partir de centimes."""
    return (Decimal(centimes) / 100).quantize(CENT)
