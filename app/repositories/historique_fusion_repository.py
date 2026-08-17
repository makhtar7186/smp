"""Journal (boss) des fusions de clients rejouées depuis une machine de
facturation. Append-only strict, comme `versements` : aucune méthode
`modifier`/`supprimer` — voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

import sqlite3

from app.models import HistoriqueFusion
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import horodatage_sql


def _vers_historique(row: sqlite3.Row) -> HistoriqueFusion:
    return HistoriqueFusion(
        id=row["id"],
        machine_origine=row["machine_origine"],
        demande_le=row["demande_le"],
        traite_le=row["traite_le"],
        client_a_garder_nom=row["client_a_garder_nom"],
        client_a_garder_adresse=row["client_a_garder_adresse"],
        client_a_supprimer_nom=row["client_a_supprimer_nom"],
        client_a_supprimer_adresse=row["client_a_supprimer_adresse"],
        client_a_garder_id_serveur=row["client_a_garder_id_serveur"],
        client_a_supprimer_id_serveur=row["client_a_supprimer_id_serveur"],
        conflit_detecte=bool(row["conflit_detecte"]),
        etat_avant_json=row["etat_avant_json"],
        etat_apres_json=row["etat_apres_json"],
        resultat=row["resultat"],
    )


class HistoriqueFusionRepository(BaseRepository):
    """Append-only : `enregistrer` (INSERT) et `lister` (lecture) uniquement."""

    def enregistrer(self, historique: HistoriqueFusion) -> HistoriqueFusion:
        horodatage = horodatage_sql()
        cur = self.conn.execute(
            "INSERT INTO historique_fusions_clients"
            " (machine_origine, demande_le, traite_le, client_a_garder_nom,"
            " client_a_garder_adresse, client_a_supprimer_nom,"
            " client_a_supprimer_adresse, client_a_garder_id_serveur,"
            " client_a_supprimer_id_serveur, conflit_detecte, etat_avant_json,"
            " etat_apres_json, resultat) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (historique.machine_origine, historique.demande_le, horodatage,
             historique.client_a_garder_nom, historique.client_a_garder_adresse,
             historique.client_a_supprimer_nom, historique.client_a_supprimer_adresse,
             historique.client_a_garder_id_serveur,
             historique.client_a_supprimer_id_serveur,
             int(historique.conflit_detecte), historique.etat_avant_json,
             historique.etat_apres_json, historique.resultat),
        )
        historique.id = cur.lastrowid
        historique.traite_le = horodatage
        self.conn.commit()
        return historique

    def lister(self) -> list[HistoriqueFusion]:
        rows = self.conn.execute(
            "SELECT * FROM historique_fusions_clients ORDER BY traite_le DESC, id DESC"
        ).fetchall()
        return [_vers_historique(r) for r in rows]
