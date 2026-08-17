"""Entité Client."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Client:
    """Client de la société. Identifié pour l'affichage par son nom, mais
    son identité/unicité réelle est le couple (téléphone, adresse) — voir
    ClientRepository. Seuls nom et adresse figurent sur une facture."""

    id: int | None = None
    nom: str = ""          # prénom et nom
    adresse: str = ""
    telephone: str = ""
    modifie_le: str = ""  # ISO datetime, écrit par ClientRepository.creer/modifier
