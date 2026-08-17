"""Instantané de statut de synchronisation, consommé par l'UI (bandeau/badge
de la machine de facturation) — voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StatutSync:
    """Snapshot immuable communiqué à l'UI à chaque changement (callback
    `on_statut_change` de `SyncWorker`) — jamais muté après construction."""

    en_ligne: bool = False
    en_attente: int = 0
    erreur: int = 0
    derniere_synchro: str = ""
