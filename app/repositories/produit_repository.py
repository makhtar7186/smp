"""Repository des produits."""
from __future__ import annotations

import sqlite3

from app.models import Produit
from app.repositories.base_repository import BaseRepository


def _vers_produit(row: sqlite3.Row) -> Produit:
    return Produit(
        id=row["id"],
        nom=row["nom"],
        type_option=row["type_option"],
        valeur_option=row["valeur_option"],
        prix=row["prix"],
        actif=bool(row["actif"]),
        quantite_stock=row["quantite_stock"],
        id_serveur=row["id_serveur"],
    )


class ProduitRepository(BaseRepository):
    """CRUD produits. Unicité sur (nom, type_option, valeur_option)."""

    def lister(self, actifs_seulement: bool = False) -> list[Produit]:
        sql = "SELECT * FROM produits"
        if actifs_seulement:
            sql += " WHERE actif = 1"
        sql += " ORDER BY nom, valeur_option"
        return [_vers_produit(r) for r in self.conn.execute(sql).fetchall()]

    def obtenir(self, produit_id: int) -> Produit | None:
        row = self.conn.execute(
            "SELECT * FROM produits WHERE id = ?", (produit_id,)
        ).fetchone()
        return _vers_produit(row) if row else None

    def chercher(self, nom: str, type_option: str, valeur_option: str) -> Produit | None:
        row = self.conn.execute(
            "SELECT * FROM produits WHERE nom=? AND type_option=? AND valeur_option=?",
            (nom, type_option, valeur_option),
        ).fetchone()
        return _vers_produit(row) if row else None

    def chercher_par_id_serveur(self, id_serveur: int) -> Produit | None:
        """Retrouve un produit par son id côté boss — clé de corrélation
        stable pour la synchro descendante d'une machine de facturation,
        insensible à un renommage (nom/option modifiés depuis l'app Stock,
        voir CLAUDE.md). Sans objet (retourne toujours `None`) pour
        `id_serveur=0` (jamais encore lié à un produit distant)."""
        if not id_serveur:
            return None
        row = self.conn.execute(
            "SELECT * FROM produits WHERE id_serveur = ?", (id_serveur,)
        ).fetchone()
        return _vers_produit(row) if row else None

    def creer(self, produit: Produit) -> Produit:
        cur = self.conn.execute(
            "INSERT INTO produits (nom, type_option, valeur_option, prix, actif,"
            " quantite_stock, id_serveur) VALUES (?,?,?,?,?,?,?)",
            (produit.nom, produit.type_option, produit.valeur_option,
             produit.prix, int(produit.actif), produit.quantite_stock,
             produit.id_serveur),
        )
        produit.id = cur.lastrowid
        self.conn.commit()
        return produit

    def obtenir_ou_creer(
        self, nom: str, type_option: str = "", valeur_option: str = "", prix: int = 0
    ) -> Produit:
        """Retourne le produit correspondant, créé au besoin (auto-création à
        la facturation d'une désignation inconnue)."""
        existant = self.chercher(nom, type_option, valeur_option)
        if existant:
            return existant
        return self.creer(
            Produit(nom=nom, type_option=type_option, valeur_option=valeur_option,
                    prix=prix)
        )

    def modifier(self, produit: Produit) -> None:
        """Met aussi à jour `id_serveur` — sans risque pour les appelants qui
        l'ignorent (édition manuelle du catalogue) : `produit` est toujours
        d'abord relu (`obtenir`/`chercher`), donc sa valeur en mémoire est
        déjà celle en base, écrite ici à l'identique."""
        self.conn.execute(
            "UPDATE produits SET nom=?, type_option=?, valeur_option=?, prix=?,"
            " actif=?, id_serveur=? WHERE id=?",
            (produit.nom, produit.type_option, produit.valeur_option,
             produit.prix, int(produit.actif), produit.id_serveur, produit.id),
        )
        self.conn.commit()

    def definir_quantite_stock(self, produit_id: int, quantite_stock: int) -> None:
        """Écrit un instantané de `quantite_stock` — utilisé exclusivement par
        `ReferentielSyncWorker` pour répercuter le stock du boss vers le cache
        d'une machine de facturation hors ligne. Jamais appelé par une édition
        manuelle du catalogue (voir `modifier`, qui ne touche pas cette
        colonne)."""
        self.conn.execute(
            "UPDATE produits SET quantite_stock = ? WHERE id = ?",
            (quantite_stock, produit_id),
        )
        self.conn.commit()

    def supprimer(self, produit_id: int) -> None:
        self.conn.execute("DELETE FROM produits WHERE id = ?", (produit_id,))
        self.conn.commit()

    def fusionner(self, id_a_garder: int, id_a_supprimer: int) -> int:
        """Fusionne un doublon (typo de saisie sur le nom/la valeur) dans le
        produit conservé : les lignes de vente qui pointaient sur le doublon
        sont réattribuées, puis il est supprimé. Retourne le nombre de lignes
        réattribuées."""
        cur = self.conn.execute(
            "UPDATE lignes_vente SET produit_id = ? WHERE produit_id = ?",
            (id_a_garder, id_a_supprimer),
        )
        nb = cur.rowcount
        self.conn.execute("DELETE FROM produits WHERE id = ?", (id_a_supprimer,))
        self.conn.commit()
        return nb
