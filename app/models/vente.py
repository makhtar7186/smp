"""Entité LigneVente (une ligne de facture)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LigneVente:
    """Ligne d'une facture : snapshot de la désignation et du prix pratiqué."""

    id: int | None = None
    facture_id: int | None = None
    produit_id: int | None = None
    designation: str = ""      # snapshot texte (ex. "BIDON 5L")
    quantite: float = 0        # décimales acceptées
    prix_unitaire: int = 0     # FCFA
    remarque: str = ""
    ref_externe: int | None = None  # hérité, inutilisé (ancien import Excel)

    @property
    def total(self) -> int:
        """Total de la ligne : quantité × prix unitaire, arrondi à l'entier
        FCFA le plus proche (quantité éventuellement décimale)."""
        return round(self.quantite * self.prix_unitaire)
