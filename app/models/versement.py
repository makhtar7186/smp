"""Entité Versement (paiement partiel ou complet reçu sur une facture)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Versement:
    """Versement lié à une facture. Append-only strict : jamais de mise à
    jour ni de suppression — une correction s'effectue en ajoutant un
    versement négatif compensatoire."""

    id: int | None = None
    facture_id: int = 0
    date_versement: date = field(default_factory=date.today)
    montant: int = 0            # FCFA entier, peut être négatif (correction)
    machine_origine: str = ""   # identifiant libre de la machine cliente d'origine
    role_origine: str = ""      # 'role_client' | 'role_principal' | 'local'
    remarque: str = ""          # note libre expliquant la nature du versement
    created_at: str = ""        # horodatage serveur (ISO datetime), rempli par le repository
