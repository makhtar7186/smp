"""Registre (boss) des blocs de numéros déjà distribués à une machine de
facturation — consommés ou non. Empêche la facturation directe du boss de
réémettre un numéro déjà remis à un poste hors ligne (voir CLAUDE.md, section
« Machine de facturation »). Numérotation continue (jamais de remise à zéro
annuelle) : `annee` reste stockée à titre indicatif/historique
(colonne additive existante, jamais retirée) mais n'intervient plus dans le
calcul du plancher, qui est désormais global."""
from __future__ import annotations

from datetime import date

from app.repositories.base_repository import BaseRepository
from app.utils.formatting import horodatage_sql


class ReservationNumeroRepository(BaseRepository):
    """Lecture/écriture de `reservations_numeros` (boss uniquement)."""

    def dernier_max_reserve(self, type_facture: str = "usine") -> int | None:
        """Plus haut `numero_max` jamais distribué, toutes années confondues
        (bloc entièrement consommé ou non — peu importe, on ne réémet jamais
        un numéro appartenant à un bloc distribué)."""
        row = self.conn.execute(
            "SELECT MAX(numero_max) AS m FROM reservations_numeros WHERE type_facture = ?",
            (type_facture,),
        ).fetchone()
        return row["m"]

    def derniere_reservation(self, type_facture: str = "usine") -> tuple[int, int, str] | None:
        """`(numero_min, numero_max, machine_id)` de la toute dernière
        réservation jamais faite (toutes machines confondues), ou `None`
        s'il n'y en a jamais eu — sert à la reprise d'un numéro JIT
        abandonné (voir `FacturationService.reserver_numero_jit`)."""
        row = self.conn.execute(
            "SELECT numero_min, numero_max, machine_id FROM reservations_numeros"
            " WHERE type_facture = ? ORDER BY id DESC LIMIT 1",
            (type_facture,),
        ).fetchone()
        return (row["numero_min"], row["numero_max"], row["machine_id"]) if row else None

    def reserver_bloc(self, type_facture: str, numero_min: int, numero_max: int,
                       machine_id: str = "") -> None:
        """Enregistre un bloc [numero_min, numero_max] comme distribué."""
        self.conn.execute(
            "INSERT INTO reservations_numeros"
            " (type_facture, annee, numero_min, numero_max, machine_id, reserve_le)"
            " VALUES (?,?,?,?,?,?)",
            (type_facture, date.today().year % 100, numero_min, numero_max, machine_id,
             horodatage_sql()),
        )
        self.conn.commit()
