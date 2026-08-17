"""Repository des brouillons de facture (proformas) — jamais de numéro."""
from __future__ import annotations

import sqlite3

from app.models import LigneVente, Proforma
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import date_vers_iso, iso_vers_date


def _vers_ligne(row: sqlite3.Row) -> LigneVente:
    return LigneVente(
        id=row["id"],
        designation=row["designation"],
        quantite=row["quantite"],
        prix_unitaire=row["prix_unitaire"],
        remarque=row["remarque"],
    )


def _vers_proforma(row: sqlite3.Row) -> Proforma:
    return Proforma(
        id=row["id"],
        date_creation=iso_vers_date(row["date_creation"]),
        client_nom=row["client_nom"],
        destination=row["destination"],
        telephone=row["telephone"],
        matricule=row["matricule"],
        etabli_par=row["etabli_par"],
        remise_taux=row["remise_taux"],
    )


class ProformaRepository(BaseRepository):
    """Persistance des brouillons ; en-tête + lignes écrits atomiquement."""

    def enregistrer(self, proforma: Proforma) -> Proforma:
        """Insère un brouillon et ses lignes dans une transaction unique."""
        try:
            cur = self.conn.execute(
                "INSERT INTO proformas (date_creation, client_nom, destination,"
                " telephone, matricule, etabli_par, remise_taux)"
                " VALUES (?,?,?,?,?,?,?)",
                (date_vers_iso(proforma.date_creation), proforma.client_nom,
                 proforma.destination, proforma.telephone, proforma.matricule,
                 proforma.etabli_par, proforma.remise_taux),
            )
            proforma.id = cur.lastrowid
            self._inserer_lignes(proforma)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        return proforma

    def modifier(self, proforma: Proforma) -> Proforma:
        """Remplace intégralement un brouillon déjà enregistré (en-tête et
        lignes), comme `FactureRepository.modifier`."""
        try:
            self.conn.execute(
                "UPDATE proformas SET date_creation=?, client_nom=?, destination=?,"
                " telephone=?, matricule=?, etabli_par=?, remise_taux=? WHERE id=?",
                (date_vers_iso(proforma.date_creation), proforma.client_nom,
                 proforma.destination, proforma.telephone, proforma.matricule,
                 proforma.etabli_par, proforma.remise_taux, proforma.id),
            )
            self.conn.execute(
                "DELETE FROM lignes_proforma WHERE proforma_id = ?", (proforma.id,))
            self._inserer_lignes(proforma)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        return proforma

    def _inserer_lignes(self, proforma: Proforma) -> None:
        for ligne in proforma.lignes:
            cur = self.conn.execute(
                "INSERT INTO lignes_proforma (proforma_id, designation,"
                " quantite, prix_unitaire, remarque) VALUES (?,?,?,?,?)",
                (proforma.id, ligne.designation, ligne.quantite,
                 ligne.prix_unitaire, ligne.remarque),
            )
            ligne.id = cur.lastrowid

    def obtenir(self, proforma_id: int) -> Proforma | None:
        """Brouillon complet (avec lignes)."""
        row = self.conn.execute(
            "SELECT * FROM proformas WHERE id = ?", (proforma_id,)
        ).fetchone()
        if not row:
            return None
        proforma = _vers_proforma(row)
        proforma.lignes = [
            _vers_ligne(r)
            for r in self.conn.execute(
                "SELECT * FROM lignes_proforma WHERE proforma_id = ? ORDER BY id",
                (proforma_id,),
            ).fetchall()
        ]
        return proforma

    def lister(self) -> list[Proforma]:
        """Tous les brouillons, avec total agrégé, récents d'abord."""
        sql = (
            "SELECT p.*, COALESCE(SUM(l.quantite * l.prix_unitaire), 0) AS total_calc,"
            " COUNT(l.id) AS nb_lignes"
            " FROM proformas p LEFT JOIN lignes_proforma l ON l.proforma_id = p.id"
            " GROUP BY p.id ORDER BY p.date_creation DESC, p.id DESC"
        )
        resultat = []
        for row in self.conn.execute(sql).fetchall():
            proforma = _vers_proforma(row)
            proforma.total_liste = row["total_calc"]
            proforma.nb_lignes = row["nb_lignes"]
            resultat.append(proforma)
        return resultat

    def supprimer(self, proforma_id: int) -> None:
        """Supprime un brouillon et ses lignes (cascade)."""
        self.conn.execute("DELETE FROM proformas WHERE id = ?", (proforma_id,))
        self.conn.commit()
