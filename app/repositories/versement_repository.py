"""Repository des versements (paiements reçus sur une facture)."""
from __future__ import annotations

import sqlite3

from app.models import Versement
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import date_vers_iso, horodatage_sql, iso_vers_date


def _vers_versement(row: sqlite3.Row) -> Versement:
    return Versement(
        id=row["id"],
        facture_id=row["facture_id"],
        date_versement=iso_vers_date(row["date_versement"]),
        montant=row["montant"],
        machine_origine=row["machine_origine"],
        role_origine=row["role_origine"],
        remarque=row["remarque"],
        created_at=row["created_at"],
    )


class VersementRepository(BaseRepository):
    """Persistance des versements. Append-only strict : aucune méthode
    `modifier`/`supprimer` n'existe ici — une correction s'effectue en
    enregistrant un nouveau versement au montant négatif."""

    def enregistrer(self, versement: Versement) -> Versement:
        """Insère un versement. Jamais d'UPDATE/DELETE."""
        horodatage = horodatage_sql()
        cur = self.conn.execute(
            "INSERT INTO versements (facture_id, date_versement, montant,"
            " machine_origine, role_origine, remarque, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (versement.facture_id, date_vers_iso(versement.date_versement),
             versement.montant, versement.machine_origine, versement.role_origine,
             versement.remarque, horodatage),
        )
        versement.id = cur.lastrowid
        versement.created_at = horodatage
        self.conn.commit()
        return versement

    def lister_par_facture(self, facture_id: int) -> list[Versement]:
        """Historique des versements d'une facture, du plus ancien au plus récent."""
        rows = self.conn.execute(
            "SELECT * FROM versements WHERE facture_id = ? ORDER BY created_at, id",
            (facture_id,),
        ).fetchall()
        return [_vers_versement(r) for r in rows]

    def somme_par_facture(self, facture_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(montant), 0) AS s FROM versements WHERE facture_id = ?",
            (facture_id,),
        ).fetchone()
        return row["s"]

    def sommes_par_factures(self, facture_ids: list[int]) -> dict[int, int]:
        """Somme des versements par facture, en une seule requête groupée
        (évite le N+1 dans les totaux/synthèses)."""
        if not facture_ids:
            return {}
        marques = ",".join("?" * len(facture_ids))
        rows = self.conn.execute(
            f"SELECT facture_id, COALESCE(SUM(montant), 0) AS s FROM versements"
            f" WHERE facture_id IN ({marques}) GROUP BY facture_id",
            facture_ids,
        ).fetchall()
        return {row["facture_id"]: row["s"] for row in rows}

    def somme_par_client(self, client_id: int) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(v.montant), 0) AS s FROM versements v"
            " JOIN factures f ON f.id = v.facture_id WHERE f.client_id = ?",
            (client_id,),
        ).fetchone()
        return row["s"]
