"""Pool local (cache de la machine de facturation) des numéros (numérotation
continue) réservés auprès de la machine boss — consommés un par un, jamais de
numéro généré ad hoc hors ligne. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

from app.repositories.base_repository import BaseRepository


class NumeroReservationRepository(BaseRepository):
    """Lecture/écriture de `numeros_reserves` (cache de la machine de
    facturation uniquement)."""

    def prochain_disponible(self, type_facture: str = "usine") -> int | None:
        """Plus petit numéro encore disponible dans le pool, ou `None` si le
        pool est épuisé — ne génère jamais de numéro par défaut."""
        row = self.conn.execute(
            "SELECT MIN(numero) AS m FROM numeros_reserves"
            " WHERE statut = 'disponible' AND type_facture = ?",
            (type_facture,),
        ).fetchone()
        return row["m"]

    def est_disponible(self, numero: int) -> bool:
        """Vrai si ce numéro appartient au pool réservé et n'a pas encore été
        consommé — garde-fou contre un numéro saisi manuellement qui
        n'aurait jamais été réservé (jamais de numéro ad hoc hors ligne)."""
        row = self.conn.execute(
            "SELECT 1 FROM numeros_reserves WHERE numero = ? AND statut = 'disponible'",
            (numero,),
        ).fetchone()
        return row is not None

    def marquer_utilise(self, numero: int) -> None:
        self.conn.execute(
            "UPDATE numeros_reserves SET statut = 'utilise',"
            " utilise_le = datetime('now') WHERE numero = ?",
            (numero,),
        )
        self.conn.commit()

    def ajouter_bloc(self, type_facture: str, numeros: list[int]) -> None:
        """Ajoute un bloc de numéros fraîchement réservés auprès du serveur.
        `INSERT OR IGNORE` : si le worker rejoue un bloc déjà reçu (ex. après
        une coupure pendant la confirmation), les doublons sont silencieusement
        ignorés plutôt que de lever une erreur d'unicité."""
        self.conn.executemany(
            "INSERT OR IGNORE INTO numeros_reserves (type_facture, numero) VALUES (?,?)",
            [(type_facture, numero) for numero in numeros],
        )
        self.conn.commit()

    def compter_disponibles(self, type_facture: str = "usine") -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM numeros_reserves"
            " WHERE statut = 'disponible' AND type_facture = ?",
            (type_facture,),
        ).fetchone()
        return row["n"]
