"""Repository des factures et de leurs lignes de vente."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.models import Facture, LigneVente
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import date_vers_iso, horodatage_sql, iso_vers_date


def _vers_ligne(row: sqlite3.Row) -> LigneVente:
    return LigneVente(
        id=row["id"],
        facture_id=row["facture_id"],
        produit_id=row["produit_id"],
        designation=row["designation"],
        quantite=row["quantite"],
        prix_unitaire=row["prix_unitaire"],
        remarque=row["remarque"],
        ref_externe=row["ref_externe"],
    )


def _vers_facture(row: sqlite3.Row) -> Facture:
    return Facture(
        id=row["id"],
        numero=row["numero"],
        date_facture=iso_vers_date(row["date_facture"]),
        client_id=row["client_id"],
        client_nom=row["client_nom"],
        destination=row["destination"],
        telephone=row["telephone"],
        matricule=row["matricule"],
        etabli_par=row["etabli_par"],
        archivee=bool(row["archivee"]),
        remise_taux=row["remise_taux"],
        remise_modifiee_par=row["remise_modifiee_par"],
        remise_modifiee_le=row["remise_modifiee_le"],
        tva_taux=row["tva_taux"],
    )


class FactureRepository(BaseRepository):
    """Persistance des factures ; toute écriture facture + lignes (+ mouvements
    de stock associés) est atomique."""

    def enregistrer(self, facture: Facture, *, queue=None, payload: dict | None = None,
                    type_operation: str = "", cle_correlation: str = "",
                    ventes_stock: list[tuple[int, float]] | None = None,
                    machine_id: str = "") -> Facture:
        """Insère une facture et ses lignes dans une transaction unique.

        `queue`/`payload`/`type_operation`/`cle_correlation` (optionnels,
        utilisés uniquement sur la machine de facturation par
        `FacturationServiceHorsLigne`) enfilent l'opération de synchro dans
        la MÊME transaction physique que l'écriture de la facture — jamais de
        facture locale sans son entrée de queue, ni l'inverse.

        `ventes_stock` (optionnel, liste de (produit_id, quantite vendue))
        décrémente le stock des produits vendus dans la MÊME transaction —
        voir CLAUDE.md, section « Gestion de stock »."""
        try:
            cur = self.conn.execute(
                "INSERT INTO factures (numero, date_facture, client_id, client_nom,"
                " destination, telephone, matricule, etabli_par, remise_taux, tva_taux)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (facture.numero, date_vers_iso(facture.date_facture),
                 facture.client_id, facture.client_nom, facture.destination,
                 facture.telephone, facture.matricule,
                 facture.etabli_par, facture.remise_taux, facture.tva_taux),
            )
            facture.id = cur.lastrowid
            for ligne in facture.lignes:
                ligne.facture_id = facture.id
                cur = self.conn.execute(
                    "INSERT INTO lignes_vente (facture_id, produit_id, designation,"
                    " quantite, prix_unitaire, remarque, ref_externe)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (ligne.facture_id, ligne.produit_id, ligne.designation,
                     ligne.quantite, ligne.prix_unitaire, ligne.remarque,
                     ligne.ref_externe),
                )
                ligne.id = cur.lastrowid
            if ventes_stock:
                self._appliquer_sorties_stock(facture.id, ventes_stock, machine_id)
            if queue is not None and payload is not None:
                queue.enfiler_sans_commit(type_operation, cle_correlation, payload)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        if queue is not None and payload is not None:
            # Après coup, seulement une fois CE commit effectué : le
            # `SyncWorker` lit la file sur une connexion séparée, donc une
            # notification avant commit le réveillerait pour rien (ligne pas
            # encore visible) — voir `QueueSyncRepository.notifier_immediat`.
            queue.notifier_immediat()
        return facture

    def modifier(self, facture: Facture, *, queue=None, payload: dict | None = None,
                type_operation: str = "", cle_correlation: str = "",
                ventes_stock: list[tuple[int, float]] | None = None,
                machine_id: str = "") -> Facture:
        """Remplace intégralement une facture déjà enregistrée (en-tête et
        lignes) — corrige une erreur de saisie sans supprimer/ressaisir.
        `archivee` n'est pas touché (une modification ne désarchive pas).
        Mêmes paramètres optionnels de synchro qu'`enregistrer`.

        `ventes_stock`, si fourni, annule les mouvements de stock de la
        version précédente de cette facture (via un mouvement d'ajustement
        compensatoire — jamais de suppression, le journal reste append-only)
        puis applique les nouveaux, dans la même transaction."""
        try:
            self.conn.execute(
                "UPDATE factures SET numero=?, date_facture=?, client_id=?,"
                " client_nom=?, destination=?, telephone=?, matricule=?,"
                " etabli_par=?, remise_taux=?, tva_taux=? WHERE id=?",
                (facture.numero, date_vers_iso(facture.date_facture),
                 facture.client_id, facture.client_nom, facture.destination,
                 facture.telephone, facture.matricule,
                 facture.etabli_par, facture.remise_taux,
                 facture.tva_taux, facture.id),
            )
            self.conn.execute("DELETE FROM lignes_vente WHERE facture_id = ?",
                              (facture.id,))
            for ligne in facture.lignes:
                ligne.id = None
                ligne.facture_id = facture.id
                cur = self.conn.execute(
                    "INSERT INTO lignes_vente (facture_id, produit_id, designation,"
                    " quantite, prix_unitaire, remarque, ref_externe)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (ligne.facture_id, ligne.produit_id, ligne.designation,
                     ligne.quantite, ligne.prix_unitaire, ligne.remarque,
                     ligne.ref_externe),
                )
                ligne.id = cur.lastrowid
            if ventes_stock is not None:
                self._reverser_sorties_stock(facture.id, machine_id)
                if ventes_stock:
                    self._appliquer_sorties_stock(facture.id, ventes_stock, machine_id)
            if queue is not None and payload is not None:
                queue.enfiler_sans_commit(type_operation, cle_correlation, payload)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        if queue is not None and payload is not None:
            queue.notifier_immediat()
        return facture

    def _appliquer_sorties_stock(
        self, facture_id: int, ventes_stock: list[tuple[int, float]], machine_id: str,
    ) -> None:
        """Enregistre une sortie de stock (mouvement négatif) par produit
        vendu et décrémente `produits.quantite_stock` — pas de blocage si le
        stock devient négatif (jamais de blocage métier sur la facturation)."""
        for produit_id, quantite in ventes_stock:
            if not produit_id or not quantite:
                continue
            delta = -round(quantite)
            self.conn.execute(
                "INSERT INTO mouvements_stock (produit_id, type_mouvement, quantite,"
                " reference, source, machine_id, cree_le)"
                " VALUES (?, 'sortie', ?, ?, 'vente', ?, ?)",
                (produit_id, delta, str(facture_id), machine_id, horodatage_sql()),
            )
            self.conn.execute(
                "UPDATE produits SET quantite_stock = quantite_stock + ? WHERE id = ?",
                (delta, produit_id),
            )

    def _reverser_sorties_stock(self, facture_id: int, machine_id: str) -> None:
        """Annule (par mouvement d'ajustement compensatoire, jamais par
        suppression) les sorties de stock déjà enregistrées pour cette
        facture — utilisé avant de ré-appliquer les sorties correspondant aux
        nouvelles lignes d'une facture modifiée."""
        rows = self.conn.execute(
            "SELECT produit_id, SUM(quantite) AS total FROM mouvements_stock"
            " WHERE source = 'vente' AND reference = ? GROUP BY produit_id",
            (str(facture_id),),
        ).fetchall()
        for row in rows:
            total = row["total"] or 0
            if not total:
                continue
            self.conn.execute(
                "INSERT INTO mouvements_stock (produit_id, type_mouvement, quantite,"
                " reference, source, machine_id, cree_le)"
                " VALUES (?, 'ajustement', ?, ?, 'vente', ?, ?)",
                (row["produit_id"], -total, str(facture_id), machine_id, horodatage_sql()),
            )
            self.conn.execute(
                "UPDATE produits SET quantite_stock = quantite_stock + ? WHERE id = ?",
                (-total, row["produit_id"]),
            )

    def enregistrer_remise_facture(
        self, facture_id: int, remise_taux: float, modifie_par: str,
    ) -> None:
        """Met à jour uniquement remise_taux et sa traçabilité (ne touche pas le
        reste de la facture) — utilisé par PaiementService.appliquer_remise_facture,
        seule voie d'écriture de remise pour l'accès distant (role_client et
        role_principal)."""
        self.conn.execute(
            "UPDATE factures SET remise_taux=?, remise_modifiee_par=?,"
            " remise_modifiee_le=? WHERE id=?",
            (remise_taux, modifie_par, horodatage_sql(), facture_id),
        )
        self.conn.commit()

    def obtenir(self, facture_id: int) -> Facture | None:
        """Facture complète (avec lignes)."""
        row = self.conn.execute(
            "SELECT * FROM factures WHERE id = ?", (facture_id,)
        ).fetchone()
        if not row:
            return None
        facture = _vers_facture(row)
        facture.lignes = [
            _vers_ligne(r)
            for r in self.conn.execute(
                "SELECT * FROM lignes_vente WHERE facture_id = ? ORDER BY id",
                (facture_id,),
            ).fetchall()
        ]
        return facture

    def numero_existe(self, numero: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM factures WHERE numero = ? LIMIT 1", (numero,),
        ).fetchone()
        return row is not None

    def dernier_numero(self) -> int | None:
        """Plus grand numéro de facture enregistré (numérotation continue,
        toutes années confondues)."""
        row = self.conn.execute("SELECT MAX(numero) AS m FROM factures").fetchone()
        return row["m"]

    def chercher_par_numero(self, numero: int) -> Facture | None:
        """Dernière facture (en-tête seul) portant ce numéro."""
        row = self.conn.execute(
            "SELECT * FROM factures WHERE numero = ? ORDER BY id DESC LIMIT 1",
            (numero,),
        ).fetchone()
        return _vers_facture(row) if row else None

    def lister(
        self,
        date_debut: date | None = None,
        date_fin: date | None = None,
        client_id: int | None = None,
        inclure_archivees: bool = False,
    ) -> list[Facture]:
        """Factures filtrées par période et/ou client, avec total agrégé, récentes
        d'abord. Les factures archivées sont exclues par défaut (masquage de fin
        de mois) — sans effet sur les statistiques, qui ne passent jamais par
        cette méthode."""
        sql = (
            "SELECT f.*, COALESCE(SUM(l.quantite * l.prix_unitaire), 0) AS total_calc,"
            " COUNT(l.id) AS nb_lignes"
            " FROM factures f LEFT JOIN lignes_vente l ON l.facture_id = f.id"
            " WHERE 1 = 1"
        )
        params: list = []
        if not inclure_archivees:
            sql += " AND f.archivee = 0"
        if date_debut:
            sql += " AND f.date_facture >= ?"
            params.append(date_vers_iso(date_debut))
        if date_fin:
            sql += " AND f.date_facture <= ?"
            params.append(date_vers_iso(date_fin))
        if client_id:
            sql += " AND f.client_id = ?"
            params.append(client_id)
        sql += " GROUP BY f.id ORDER BY f.date_facture DESC, f.numero DESC"
        factures = []
        for row in self.conn.execute(sql, params).fetchall():
            facture = _vers_facture(row)
            facture.total_liste = row["total_calc"]
            facture.nb_lignes = row["nb_lignes"]
            factures.append(facture)
        return factures

    def archiver(
        self, date_debut: date, date_fin: date, client_id: int | None = None,
    ) -> int:
        """Masque (archive) les factures de la période de l'historique des ventes
        et des statistiques (dashboard, analyse produits). Retourne le nombre
        archivé."""
        sql = "UPDATE factures SET archivee = 1 WHERE archivee = 0 AND date_facture BETWEEN ? AND ?"
        params: list = [date_vers_iso(date_debut), date_vers_iso(date_fin)]
        if client_id:
            sql += " AND client_id = ?"
            params.append(client_id)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount

    def archiver_ids(self, ids: list[int]) -> int:
        """Archive une sélection précise de factures (page Archive)."""
        if not ids:
            return 0
        marques = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE factures SET archivee = 1 WHERE archivee = 0 AND id IN ({marques})",
            ids,
        )
        self.conn.commit()
        return cur.rowcount

    def desarchiver_ids(self, ids: list[int]) -> int:
        """Réaffiche une sélection précise de factures archivées."""
        if not ids:
            return 0
        marques = ",".join("?" * len(ids))
        cur = self.conn.execute(
            f"UPDATE factures SET archivee = 0 WHERE archivee = 1 AND id IN ({marques})",
            ids,
        )
        self.conn.commit()
        return cur.rowcount

    def desarchiver(
        self, date_debut: date, date_fin: date, client_id: int | None = None,
    ) -> int:
        """Réaffiche des factures archivées de la période. Retourne le nombre."""
        sql = "UPDATE factures SET archivee = 0 WHERE archivee = 1 AND date_facture BETWEEN ? AND ?"
        params: list = [date_vers_iso(date_debut), date_vers_iso(date_fin)]
        if client_id:
            sql += " AND client_id = ?"
            params.append(client_id)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount

    def numeros_connus(self) -> list[int]:
        """Tous les numéros présents localement — sert de base à la
        synchronisation descendante du statut d'archivage (machine de
        facturation) : on ne demande au boss que ce qu'on connaît déjà."""
        rows = self.conn.execute("SELECT numero FROM factures").fetchall()
        return [r["numero"] for r in rows]

    def numeros_archives(self, numeros: list[int]) -> list[int]:
        """Parmi ces numéros, ceux actuellement archivés — utilisé côté boss
        pour répondre à une machine de facturation qui vérifie le statut de
        ses propres factures."""
        if not numeros:
            return []
        marques = ",".join("?" * len(numeros))
        rows = self.conn.execute(
            f"SELECT numero FROM factures WHERE archivee = 1 AND numero IN ({marques})",
            numeros,
        ).fetchall()
        return [r["numero"] for r in rows]

    def synchroniser_archivage(self, tous_numeros: list[int], numeros_archives: list[int]) -> None:
        """Aligne le statut d'archivage local sur celui du boss, par
        **numéro** (clé naturelle — jamais l'id, qui diffère entre le cache
        local et la base boss). `tous_numeros` doit couvrir exactement les
        numéros vérifiés ce passage (jamais désarchivé localement un numéro
        qu'on n'a pas vérifié)."""
        archives = set(numeros_archives)
        a_archiver = list(archives)
        a_desarchiver = [n for n in tous_numeros if n not in archives]
        if a_archiver:
            marques = ",".join("?" * len(a_archiver))
            self.conn.execute(
                f"UPDATE factures SET archivee = 1 WHERE numero IN ({marques})",
                a_archiver,
            )
        if a_desarchiver:
            marques = ",".join("?" * len(a_desarchiver))
            self.conn.execute(
                f"UPDATE factures SET archivee = 0 WHERE numero IN ({marques})",
                a_desarchiver,
            )
        self.conn.commit()

    def supprimer(self, facture_id: int, machine_id: str = "", *, queue=None,
                 payload: dict | None = None, type_operation: str = "",
                 cle_correlation: str = "") -> None:
        """Supprime une facture et ses lignes (cascade). Restitue d'abord le
        stock des produits vendus — comme si les articles n'avaient jamais
        quitté le stock — via le même mouvement d'ajustement compensatoire
        que `modifier` (`_reverser_sorties_stock`, jamais une suppression du
        journal append-only).

        `queue`/`payload`/`type_operation`/`cle_correlation` (optionnels,
        utilisés uniquement sur la machine de facturation par
        `FacturationServiceHorsLigne`) enfilent l'opération de synchro dans
        la MÊME transaction physique que la suppression — sans quoi le boss
        continuerait de voir une facture qui n'existe plus localement."""
        try:
            self._reverser_sorties_stock(facture_id, machine_id)
            self.conn.execute("DELETE FROM factures WHERE id = ?", (facture_id,))
            if queue is not None and payload is not None:
                queue.enfiler_sans_commit(type_operation, cle_correlation, payload)
            self.conn.commit()
        except sqlite3.Error:
            self.conn.rollback()
            raise
        if queue is not None and payload is not None:
            queue.notifier_immediat()

    def compter_destinations(self, client_id: int) -> list[tuple[str, int]]:
        """Destinations distinctes utilisées sur les factures de ce client, avec
        leur nombre — sert à repérer une simple faute de saisie."""
        rows = self.conn.execute(
            "SELECT destination, COUNT(*) AS n FROM factures"
            " WHERE client_id = ? GROUP BY destination ORDER BY n DESC",
            (client_id,),
        ).fetchall()
        return [(row["destination"], row["n"]) for row in rows]

    def reattribuer_client(
        self, ancien_id: int, nouveau_id: int, nouveau_nom: str,
        destination: str | None = None,
    ) -> int:
        """Réattribue les factures (et le nom client dénormalisé) d'un client à
        un autre, éventuellement limité à une destination précise. Retourne le
        nombre de factures modifiées."""
        sql = "UPDATE factures SET client_id = ?, client_nom = ? WHERE client_id = ?"
        params: list = [nouveau_id, nouveau_nom, ancien_id]
        if destination is not None:
            sql += " AND destination = ?"
            params.append(destination)
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur.rowcount
