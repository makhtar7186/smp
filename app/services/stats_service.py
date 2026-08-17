"""Service de statistiques pour les dashboards."""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.utils.formatting import date_vers_iso, iso_vers_date


@dataclass
class KPI:
    """Indicateur avec valeur courante et valeur de la période précédente."""

    valeur: int
    precedent: int

    @property
    def variation_pct(self) -> float | None:
        """Variation en % vs période précédente (None si pas de référence)."""
        if self.precedent == 0:
            return None
        return (self.valeur - self.precedent) / self.precedent * 100


class StatsService:
    """Agrégations sur l'historique des ventes (lignes_vente × factures). Un
    seul type de facture existe désormais — plus de filtre `type_facture`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # Helpers -----------------------------------------------------------------
    def _ca(self, debut: date, fin: date) -> int:
        """Chiffre d'affaires FCFA sur [debut, fin] inclus."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(l.quantite * l.prix_unitaire), 0) AS ca"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0"
            " AND f.date_facture BETWEEN ? AND ?",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchone()
        return row["ca"]

    def _nb_factures(self, debut: date, fin: date) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM factures"
            " WHERE archivee = 0 AND date_facture BETWEEN ? AND ?",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchone()
        return row["n"]

    # KPI ---------------------------------------------------------------------
    def kpi_ca_jour(self, jour: date | None = None) -> KPI:
        """CA du jour vs veille."""
        jour = jour or date.today()
        veille = jour - timedelta(days=1)
        return KPI(self._ca(jour, jour), self._ca(veille, veille))

    def kpi_ca_mois(self, jour: date | None = None) -> KPI:
        """CA du mois en cours vs mois précédent."""
        jour = jour or date.today()
        debut_mois = jour.replace(day=1)
        fin_mois_prec = debut_mois - timedelta(days=1)
        debut_mois_prec = fin_mois_prec.replace(day=1)
        return KPI(
            self._ca(debut_mois, jour),
            self._ca(debut_mois_prec, fin_mois_prec),
        )

    def kpi_ca_annee(self, jour: date | None = None) -> KPI:
        """CA de l'année en cours vs année précédente complète."""
        jour = jour or date.today()
        debut = date(jour.year, 1, 1)
        return KPI(
            self._ca(debut, jour),
            self._ca(date(jour.year - 1, 1, 1), date(jour.year - 1, 12, 31)),
        )

    def kpi_nb_ventes_annee(self, jour: date | None = None) -> KPI:
        """Nombre de factures de l'année vs année précédente."""
        jour = jour or date.today()
        return KPI(
            self._nb_factures(date(jour.year, 1, 1), jour),
            self._nb_factures(date(jour.year - 1, 1, 1), date(jour.year - 1, 12, 31)),
        )

    def panier_moyen_annee(self, jour: date | None = None) -> int:
        """CA annuel / nombre de factures de l'année (FCFA)."""
        jour = jour or date.today()
        ca = self._ca(date(jour.year, 1, 1), jour)
        nb = self._nb_factures(date(jour.year, 1, 1), jour)
        return round(ca / nb) if nb else 0

    # Tops et répartitions ----------------------------------------------------
    def top_produits(
        self, debut: date, fin: date, par: str = "quantite", limite: int = 10
    ) -> list[tuple[str, int]]:
        """Top produits (désignation) par quantité ou par CA."""
        colonne = (
            "SUM(l.quantite)" if par == "quantite"
            else "SUM(l.quantite * l.prix_unitaire)"
        )
        rows = self._conn.execute(
            f"SELECT l.designation AS libelle, {colonne} AS v"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0"
            " AND f.date_facture BETWEEN ? AND ?"
            " GROUP BY libelle ORDER BY v DESC LIMIT ?",
            (date_vers_iso(debut), date_vers_iso(fin), limite),
        ).fetchall()
        return [(row["libelle"], row["v"]) for row in rows]

    def repartition_par_gamme(self, debut: date, fin: date) -> list[tuple[str, int]]:
        """CA par article (`produits.nom`, repli sur la désignation si produit
        inconnu). Le nom de méthode/paramètre historique (« gamme ») est
        conservé pour ne pas casser les couches UI/API qui l'appellent —
        seule la colonne source a changé (`produits.gamme` n'existe plus,
        remplacée par `produits.nom`)."""
        rows = self._conn.execute(
            "SELECT COALESCE(p.nom, l.designation) AS article,"
            " SUM(l.quantite * l.prix_unitaire) AS ca"
            " FROM lignes_vente l"
            " JOIN factures f ON f.id = l.facture_id"
            " LEFT JOIN produits p ON p.id = l.produit_id"
            " WHERE f.archivee = 0"
            " AND f.date_facture BETWEEN ? AND ?"
            # Regroupe sur l'expression complète, jamais sur l'alias "article"
            # seul : PostgreSQL résout un identifiant de GROUP BY en priorité
            # contre une VRAIE colonne du FROM avant de retomber sur un alias
            # de SELECT. SQLite, plus permissif, ne détectait pas cette
            # ambiguïté.
            " GROUP BY COALESCE(p.nom, l.designation) ORDER BY ca DESC",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchall()
        return [(row["article"], row["ca"]) for row in rows]

    def serie_ca(
        self, debut: date, fin: date, granularite: str = "jour"
    ) -> list[tuple[str, int]]:
        """Série temporelle du CA : granularité 'jour', 'semaine' ou 'mois'.

        Le groupement par période se fait côté Python (`date.strftime`,
        mêmes directives et même résultat que le `strftime` SQL utilisé
        auparavant) plutôt qu'en SQL : `strftime()` est une fonction SQLite,
        absente de PostgreSQL — voir CLAUDE.md, section « Bascule
        PostgreSQL »."""
        formats = {
            "jour": "%Y-%m-%d",
            "semaine": "%Y-S%W",
            "mois": "%Y-%m",
        }
        fmt = formats.get(granularite, formats["jour"])
        rows = self._conn.execute(
            "SELECT f.date_facture AS date_facture,"
            " l.quantite * l.prix_unitaire AS montant"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0"
            " AND f.date_facture BETWEEN ? AND ?",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchall()
        totaux: dict[str, int] = defaultdict(int)
        for row in rows:
            periode = iso_vers_date(row["date_facture"]).strftime(fmt)
            totaux[periode] += row["montant"]
        return sorted(totaux.items())

    def quantite_vendue_par_produit(self) -> dict[int, int]:
        """Quantité totale vendue de chaque produit du catalogue, toutes
        ventes non archivées confondues (pas de filtre de période) — sert la
        colonne « Quantité vendue » de la page Produits."""
        rows = self._conn.execute(
            "SELECT l.produit_id AS produit_id, SUM(l.quantite) AS quantite"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0 AND l.produit_id IS NOT NULL"
            " GROUP BY l.produit_id"
        ).fetchall()
        return {row["produit_id"]: row["quantite"] for row in rows}

    # Analyse produit -----------------------------------------------------
    # Libellé produit = désignation (plus d'épaisseur à concaténer, colonne
    # supprimée de lignes_vente).
    _LIBELLE = "l.designation"

    def liste_produits_vendus(self) -> list[str]:
        """Libellés distincts des produits présents dans l'historique."""
        rows = self._conn.execute(
            f"SELECT DISTINCT {self._LIBELLE} AS libelle"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0 ORDER BY libelle"
        ).fetchall()
        return [row["libelle"] for row in rows]

    def resume_produit(self, libelle: str, debut: date, fin: date) -> dict:
        """Quantité, CA, nb de factures et prix moyen d'un produit sur la période."""
        row = self._conn.execute(
            f"SELECT COALESCE(SUM(l.quantite), 0) AS quantite,"
            " COALESCE(SUM(l.quantite * l.prix_unitaire), 0) AS ca,"
            " COUNT(DISTINCT l.facture_id) AS nb_factures"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            f" WHERE f.archivee = 0"
            f" AND {self._LIBELLE} = ?"
            " AND f.date_facture BETWEEN ? AND ?",
            (libelle, date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchone()
        quantite = row["quantite"]
        return {
            "quantite": quantite,
            "ca": row["ca"],
            "nb_factures": row["nb_factures"],
            "prix_moyen": round(row["ca"] / quantite) if quantite else 0,
        }

    def serie_quantite_produit(
        self, libelle: str, debut: date, fin: date, granularite: str = "mois"
    ) -> list[tuple[str, int]]:
        """Quantités vendues d'un produit par période (jour/semaine/mois)."""
        formats = {"jour": "%Y-%m-%d", "semaine": "%Y-S%W", "mois": "%Y-%m"}
        fmt = formats.get(granularite, formats["mois"])
        rows = self._conn.execute(
            f"SELECT f.date_facture AS date_facture, l.quantite AS quantite"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            f" WHERE f.archivee = 0"
            f" AND {self._LIBELLE} = ?"
            " AND f.date_facture BETWEEN ? AND ?",
            (libelle, date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchall()
        totaux: dict[str, int] = defaultdict(int)
        for row in rows:
            periode = iso_vers_date(row["date_facture"]).strftime(fmt)
            totaux[periode] += row["quantite"]
        return sorted(totaux.items())

    # Aide à la décision production / habitudes clients --------------------
    def quantites_par_dimension(self, debut: date, fin: date) -> list[tuple[str, int]]:
        """Quantités vendues par valeur d'option 'dimension' (ex. 40x60), via
        le catalogue (`produits.type_option = 'dimension'`, remplace
        l'ancienne colonne `produits.dimensions`, supprimée)."""
        rows = self._conn.execute(
            "SELECT p.valeur_option AS dims, SUM(l.quantite) AS quantite"
            " FROM lignes_vente l"
            " JOIN factures f ON f.id = l.facture_id"
            " JOIN produits p ON p.id = l.produit_id"
            " WHERE f.archivee = 0"
            " AND p.type_option = 'dimension' AND p.valeur_option <> ''"
            " AND f.date_facture BETWEEN ? AND ?"
            " GROUP BY dims ORDER BY quantite DESC",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchall()
        return [(row["dims"], row["quantite"]) for row in rows]

    def quantites_par_litrage(self, debut: date, fin: date) -> list[tuple[str, int]]:
        """Quantités vendues par valeur d'option 'litrage' (ex. 5L) — même
        principe que `quantites_par_dimension` pour l'autre type d'option."""
        rows = self._conn.execute(
            "SELECT p.valeur_option AS litrage, SUM(l.quantite) AS quantite"
            " FROM lignes_vente l"
            " JOIN factures f ON f.id = l.facture_id"
            " JOIN produits p ON p.id = l.produit_id"
            " WHERE f.archivee = 0"
            " AND p.type_option = 'litrage' AND p.valeur_option <> ''"
            " AND f.date_facture BETWEEN ? AND ?"
            " GROUP BY litrage ORDER BY quantite DESC",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchall()
        return [(row["litrage"], row["quantite"]) for row in rows]

    def ca_par_jour_semaine(self, debut: date, fin: date) -> list[tuple[int, int]]:
        """CA par jour de la semaine (0 = dimanche, convention strftime %w —
        groupement calculé côté Python, voir `serie_ca`)."""
        rows = self._conn.execute(
            "SELECT f.date_facture AS date_facture,"
            " l.quantite * l.prix_unitaire AS montant"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0"
            " AND f.date_facture BETWEEN ? AND ?",
            (date_vers_iso(debut), date_vers_iso(fin)),
        ).fetchall()
        totaux: dict[int, int] = defaultdict(int)
        for row in rows:
            jour = (iso_vers_date(row["date_facture"]).weekday() + 1) % 7  # 0 = dimanche
            totaux[jour] += row["montant"]
        return sorted(totaux.items())

    def top_clients(self, debut: date, fin: date,
                    limite: int = 10) -> list[tuple[str, int]]:
        """Meilleurs clients par CA sur la période."""
        rows = self._conn.execute(
            "SELECT f.client_nom AS nom, SUM(l.quantite * l.prix_unitaire) AS ca"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " WHERE f.archivee = 0"
            " AND f.date_facture BETWEEN ? AND ?"
            " GROUP BY f.client_nom ORDER BY ca DESC LIMIT ?",
            (date_vers_iso(debut), date_vers_iso(fin), limite),
        ).fetchall()
        return [(row["nom"], row["ca"]) for row in rows]

    def ca_par_client(self, annee: int) -> list[tuple[int, str, str, int]]:
        """CA annuel par client : liste (client_id, nom, adresse, ca) triée
        décroissante. L'adresse vient de la fiche client — c'est elle qui
        distingue deux clients homonymes ayant des adresses différentes."""
        rows = self._conn.execute(
            "SELECT f.client_id AS cid, f.client_nom AS nom,"
            " COALESCE(c.adresse, '') AS adresse,"
            " SUM(l.quantite * l.prix_unitaire) AS ca"
            " FROM lignes_vente l JOIN factures f ON f.id = l.facture_id"
            " LEFT JOIN clients c ON c.id = f.client_id"
            " WHERE f.date_facture BETWEEN ? AND ?"
            # PostgreSQL exige que toute colonne du SELECT non agrégée
            # apparaisse dans GROUP BY (contrairement à SQLite, plus
            # permissif) — c.adresse ajoutée, sans effet sur le résultat
            # puisqu'un client_id détermine une seule adresse (LEFT JOIN).
            " GROUP BY f.client_id, f.client_nom, c.adresse ORDER BY ca DESC",
            # Comparaison de chaînes ISO (YYYY-MM-DD) plutôt que strftime('%Y', ...)
            # — fonction SQLite absente de PostgreSQL ; l'ordre lexical des
            # dates ISO couvre exactement l'année visée.
            (f"{annee:04d}-01-01", f"{annee:04d}-12-31"),
        ).fetchall()
        return [(row["cid"], row["nom"], row["adresse"], row["ca"]) for row in rows]
