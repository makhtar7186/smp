"""Entité Remise annuelle par client."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Remise:
    """Remise de fin d'année accordée à un client, calculée sur son CA annuel."""

    id: int | None = None
    client_id: int = 0
    annee: int = 0
    ca_annuel: int = 0         # FCFA — CA constaté au moment du calcul
    taux: float = 0.0          # pourcentage, ex. 2.5
    montant: int = 0           # FCFA — arrondi de ca_annuel × taux / 100
    note: str = ""
    modifie_par: str = ""      # 'role_principal' | 'role_client' | 'local' — traçabilité
    modifie_le: str = ""       # ISO datetime de la dernière modification
