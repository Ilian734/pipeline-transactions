"""Exceptions du projet."""

from __future__ import annotations


class ErreurPipeline(Exception):
    """Racine de toutes les erreurs metier du projet."""


class LigneInvalideError(ErreurPipeline):
    """Une ligne du CSV n'a pas pu etre convertie en `Transaction`."""

    def __init__(self, numero_ligne: int, raison: str) -> None:
        self.numero_ligne = numero_ligne
        self.raison = raison
        super().__init__(f"ligne {numero_ligne} : {raison}")


class FichierInvalideError(ErreurPipeline):
    """Le fichier est rejete en bloc (strategie de rejet global)."""

    def __init__(self, nom: str, raison: str) -> None:
        self.nom = nom
        self.raison = raison
        super().__init__(f"fichier {nom} rejete : {raison}")
