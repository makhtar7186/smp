"""Repository du stock : journal des mouvements (append-only) et quantités
courantes (cache sur `produits.quantite_stock`)."""
from __future__ import annotations

import sqlite3

from app.models import MouvementStock
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import horodatage_sql


def _vers_mouvement(row: sqlite3.Row) -> MouvementStock:
    return MouvementStock(
        id=row["id"],
        produit_id=row["produit_id"],
        type_mouvement=row["type_mouvement"],
        quantite=row["quantite"],
        reference=row["reference"],
        source=row["source"],
        machine_id=row["machine_id"],
        cree_le=row["cree_le"],
    )


class StockRepository(BaseRepository):
    """Écritures manuelles de stock (entrée, ajustement) — les sorties liées
    à une vente sont écrites par `FactureRepository` dans la même transaction
    que la facture (voir CLAUDE.md, section « Gestion de stock »)."""

    def enregistrer_mouvement(
        self, produit_id: int, type_mouvement: str, quantite: int,
        reference: str = "", source: str = "manuel", machine_id: str = "",
    ) -> MouvementStock:
        """Enregistre un mouvement et met à jour `produits.quantite_stock`
        dans la même transaction. `quantite` est le delta signé (positif pour
        une entrée, positif ou négatif pour un ajustement correctif)."""
        try:
            cur = self.conn.execute(
                "INSERT INTO mouvements_stock (produit_id, type_mouvement, quantite,"
                " reference, source, machine_id, cree_le) VALUES (?,?,?,?,?,?,?)",
                (produit_id, type_mouvement, quantite, reference, source, machine_id,
                 horodatage_sql()),
            )
            self.conn.execute(
                "UPDATE produits SET quantite_stock = quantite_stock + ? WHERE id = ?",
                (quantite, produit_id),
            )
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        mouvement_id = cur.lastrowid
        return self.obtenir(mouvement_id)

    def obtenir(self, mouvement_id: int) -> MouvementStock | None:
        row = self.conn.execute(
            "SELECT * FROM mouvements_stock WHERE id = ?", (mouvement_id,)
        ).fetchone()
        return _vers_mouvement(row) if row else None

    def historique(self, produit_id: int, limite: int = 200) -> list[MouvementStock]:
        """Mouvements d'un produit, les plus récents d'abord."""
        rows = self.conn.execute(
            "SELECT * FROM mouvements_stock WHERE produit_id = ?"
            " ORDER BY id DESC LIMIT ?",
            (produit_id, limite),
        ).fetchall()
        return [_vers_mouvement(r) for r in rows]

    def stock_actuel(self, produit_id: int) -> int:
        row = self.conn.execute(
            "SELECT quantite_stock FROM produits WHERE id = ?", (produit_id,)
        ).fetchone()
        return row["quantite_stock"] if row else 0
