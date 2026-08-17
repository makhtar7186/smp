"""Repository des remises annuelles."""
from __future__ import annotations

import sqlite3

from app.models import Remise
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import horodatage_sql


def _vers_remise(row: sqlite3.Row) -> Remise:
    return Remise(
        id=row["id"],
        client_id=row["client_id"],
        annee=row["annee"],
        ca_annuel=row["ca_annuel"],
        taux=row["taux"],
        montant=row["montant"],
        note=row["note"],
        modifie_par=row["modifie_par"],
        modifie_le=row["modifie_le"],
    )


class RemiseRepository(BaseRepository):
    """Persistance des remises (une par client et par année, upsert)."""

    def enregistrer(self, remise: Remise, modifie_par: str = "local") -> Remise:
        """Insère ou met à jour la remise du couple (client, année), en
        enregistrant qui l'a écrite (traçabilité — voir CLAUDE.md, section
        « Paiements »)."""
        horodatage = horodatage_sql()
        self.conn.execute(
            "INSERT INTO remises (client_id, annee, ca_annuel, taux, montant, note,"
            " modifie_par, modifie_le)"
            " VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(client_id, annee) DO UPDATE SET"
            " ca_annuel=excluded.ca_annuel, taux=excluded.taux,"
            " montant=excluded.montant, note=excluded.note,"
            " modifie_par=excluded.modifie_par, modifie_le=?",
            (remise.client_id, remise.annee, remise.ca_annuel,
             remise.taux, remise.montant, remise.note, modifie_par, horodatage, horodatage),
        )
        row = self.conn.execute(
            "SELECT id, modifie_par, modifie_le FROM remises"
            " WHERE client_id = ? AND annee = ?",
            (remise.client_id, remise.annee),
        ).fetchone()
        remise.id = row["id"]
        remise.modifie_par = row["modifie_par"]
        remise.modifie_le = row["modifie_le"]
        self.conn.commit()
        return remise

    def somme_client(self, client_id: int) -> int:
        """Somme des remises annuelles (toutes années) accordées à un client —
        utilisé par PaiementService.total_depense_par_client."""
        row = self.conn.execute(
            "SELECT COALESCE(SUM(montant), 0) AS s FROM remises WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        return row["s"]

    def lister_annee(self, annee: int) -> dict[int, Remise]:
        """Remises de l'année, indexées par client_id."""
        rows = self.conn.execute(
            "SELECT * FROM remises WHERE annee = ?", (annee,)
        ).fetchall()
        return {row["client_id"]: _vers_remise(row) for row in rows}

    def reattribuer_client(self, ancien_id: int, nouveau_id: int) -> None:
        """Déplace les remises d'un client vers un autre (fusion). En cas de
        conflit sur une même année, celle du client conservé prime."""
        lignes = self.conn.execute(
            "SELECT * FROM remises WHERE client_id = ?", (ancien_id,)
        ).fetchall()
        for row in lignes:
            existe = self.conn.execute(
                "SELECT 1 FROM remises WHERE client_id = ? AND annee = ?",
                (nouveau_id, row["annee"]),
            ).fetchone()
            if existe:
                self.conn.execute("DELETE FROM remises WHERE id = ?", (row["id"],))
            else:
                self.conn.execute(
                    "UPDATE remises SET client_id = ? WHERE id = ?",
                    (nouveau_id, row["id"]),
                )
        self.conn.commit()
