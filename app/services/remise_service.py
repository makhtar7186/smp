"""Service des remises annuelles par client."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.models import Remise
from app.repositories.remise_repository import RemiseRepository
from app.services.stats_service import StatsService


@dataclass
class LigneRemise:
    """Ligne du tableau des remises : client, CA de l'année et remise éventuelle."""

    client_id: int
    client_nom: str
    client_adresse: str
    ca_annuel: int
    taux: float = 0.0
    montant: int = 0
    note: str = ""


class RemiseService:
    """Calcule et enregistre les remises de fin d'année (CA annuel × taux)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._remises = RemiseRepository(conn)
        self._stats = StatsService(conn)

    @staticmethod
    def calculer_montant(ca_annuel: int, taux: float) -> int:
        """Montant de remise = CA annuel × taux %, arrondi au FCFA."""
        return round(ca_annuel * taux / 100)

    def tableau_annee(self, annee: int) -> list[LigneRemise]:
        """CA annuel de chaque client, fusionné avec les remises déjà saisies."""
        remises_existantes = self._remises.lister_annee(annee)
        lignes: list[LigneRemise] = []
        for client_id, nom, adresse, ca in self._stats.ca_par_client(annee):
            remise = remises_existantes.get(client_id)
            lignes.append(
                LigneRemise(
                    client_id=client_id or 0,
                    client_nom=nom,
                    client_adresse=adresse,
                    ca_annuel=ca,
                    taux=remise.taux if remise else 0.0,
                    montant=remise.montant if remise else 0,
                    note=remise.note if remise else "",
                )
            )
        return lignes

    def enregistrer(
        self, client_id: int, annee: int, ca_annuel: int, taux: float, note: str = "",
        modifie_par: str = "local",
    ) -> Remise:
        """Enregistre (ou met à jour) la remise d'un client pour une année.
        `modifie_par` trace qui écrit (role_principal/role_client/local) —
        voir CLAUDE.md, section « Paiements »."""
        remise = Remise(
            client_id=client_id,
            annee=annee,
            ca_annuel=ca_annuel,
            taux=taux,
            montant=self.calculer_montant(ca_annuel, taux),
            note=note,
        )
        return self._remises.enregistrer(remise, modifie_par=modifie_par)
