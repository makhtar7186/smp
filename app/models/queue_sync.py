"""Entité d'une opération en file d'attente de synchronisation (machine de
facturation → machine boss). Voir CLAUDE.md, section « Machine de
facturation (offline-first) »."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OperationSync:
    """Une opération montante en attente, en cours, synchronisée ou en erreur."""

    id: int | None = None
    type_operation: str = ""  # creation_facture | modification_facture |
                               # creation_client | creation_produit | fusion_client
    cle_correlation: str = ""
    payload: dict = field(default_factory=dict)
    statut: str = "en_attente"  # en_attente | en_cours | synchronise | erreur
    tentatives: int = 0
    derniere_erreur: str = ""
    cree_le: str = ""
    traite_le: str = ""
    machine_id: str = ""
