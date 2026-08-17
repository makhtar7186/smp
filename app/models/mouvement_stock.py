"""Entité MouvementStock : une ligne du journal de stock (append-only)."""
from __future__ import annotations

from dataclasses import dataclass

TYPE_ENTREE = "entree"
TYPE_SORTIE = "sortie"
TYPE_AJUSTEMENT = "ajustement"

SOURCE_VENTE = "vente"
SOURCE_MANUEL = "manuel"


@dataclass
class MouvementStock:
    """Mouvement de stock : delta signé (positif = entrée, négatif = sortie
    ou ajustement correctif) appliqué à `Produit.quantite_stock`. Append-only,
    comme `Versement` — une correction s'effectue via un nouveau mouvement,
    jamais par modification/suppression d'un mouvement existant."""

    id: int | None = None
    produit_id: int | None = None
    type_mouvement: str = TYPE_ENTREE
    quantite: int = 0
    reference: str = ""   # n° de facture (sortie liée à une vente) ou note libre
    source: str = SOURCE_MANUEL
    machine_id: str = ""
    cree_le: str = ""
