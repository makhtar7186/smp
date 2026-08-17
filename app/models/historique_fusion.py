"""Entrée du journal (boss, append-only) des fusions de clients rejouées
depuis une machine de facturation — y compris celles appliquées malgré un
conflit détecté. Voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class HistoriqueFusion:
    id: int | None = None
    machine_origine: str = ""
    demande_le: str = ""
    traite_le: str = ""
    client_a_garder_nom: str = ""
    client_a_garder_adresse: str = ""
    client_a_supprimer_nom: str = ""
    client_a_supprimer_adresse: str = ""
    client_a_garder_id_serveur: int | None = None
    client_a_supprimer_id_serveur: int | None = None
    conflit_detecte: bool = False
    etat_avant_json: str = ""
    etat_apres_json: str = ""
    resultat: str = "applique"  # 'applique' | 'echec'
