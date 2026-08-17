"""Vue Historique des ventes : liste filtrable, détail, réimpression.

Les factures archivées (page dédiée « Archive ») n'apparaissent plus ici —
voir archive_view.py pour l'archivage/désarchivage par lot.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from app.i18n.translations import t
from app.repositories.client_repository import ClientRepository
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.champ_date import ChampDate
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.fichiers import ouvrir_fichier
from app.utils.formatting import (
    format_date,
    format_fcfa,
    format_nombre,
    libelle_client,
    parse_date_affichage,
)


_LIBELLES_STATUT_SYNCHRO = {
    None: "sync_statut_locale",
    "en_attente": "sync_statut_en_attente",
    "en_cours": "sync_statut_en_attente",
    "synchronise": "sync_statut_synchronise",
    "erreur": "sync_statut_erreur",
}


class VentesView(ttk.Frame):
    """Historique des factures, filtrable par période et par client."""

    def __init__(self, parent: tk.Misc, application,
                 cle_titre: str = "ventes_titre",
                 statut_synchro_provider: Callable[[int], str | None] | None = None,
                 ) -> None:
        super().__init__(parent)
        self.app = application
        self._cle_titre = cle_titre
        # Machine de facturation uniquement (offline-first) : badge « Synchronisé »/
        # « En attente »/« Erreur » par facture — jamais construit côté boss.
        self._statut_synchro_provider = statut_synchro_provider
        self._clients_repo = ClientRepository(application.conn)
        self._factures = []
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(3, weight=2)

        ttk.Label(self, text=t(self._cle_titre), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD))

        # Filtres
        filtres = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                           highlightbackground=theme.COULEURS["bordure"])
        filtres.grid(row=1, column=0, sticky="ew", padx=theme.PAD_L)
        self.var_du = tk.StringVar()
        self.var_au = tk.StringVar()
        self.var_client = tk.StringVar()
        self.var_numero = tk.StringVar()

        tk.Label(filtres, text=t("ventes_numero"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        entree_numero = ttk.Entry(filtres, textvariable=self.var_numero, width=10)
        entree_numero.pack(side="left")
        entree_numero.bind("<Return>", lambda _e: self.rafraichir())
        tk.Label(filtres, text=t("du"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        # Champs vidés après construction (DateEntry pré-remplit sinon avec la
        # date du jour) — un filtre Du/Au vide signifie « tous les clients ».
        champ_du = ChampDate(filtres, largeur=12, textvariable=self.var_du)
        champ_du.pack(side="left")
        champ_du.vider()
        tk.Label(filtres, text=t("au"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        champ_au = ChampDate(filtres, largeur=12, textvariable=self.var_au)
        champ_au.pack(side="left")
        champ_au.vider()
        tk.Label(filtres, text=t("fact_client"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        self._champ_client = AutocompleteEntry(filtres, largeur=24,
                                               textvariable=self.var_client,
                                               on_select=lambda _v: self.rafraichir())
        self._champ_client.pack(side="left")
        ttk.Button(filtres, text=t("filtrer"), style="Accent.TButton",
                   command=self.rafraichir).pack(side="left", padx=theme.PAD)
        ttk.Button(filtres, text=t("reinitialiser"),
                   command=self._reinitialiser).pack(side="left")
        ttk.Button(filtres, text="📤 " + t("ventes_export_excel"),
                   command=self._exporter_excel).pack(side="right", padx=theme.PAD)

        # Liste des factures
        colonnes = [
            ("numero", t("ventes_numero"), 90, "center"),
            ("date", t("date"), 100, "center"),
            ("client", t("fact_client"), 220, "w"),
            ("destination", t("fact_destination"), 150, "w"),
            ("lignes", t("ventes_lignes"), 70, "center"),
            ("total", t("total"), 130, "e"),
            ("remise", t("ventes_remise"), 90, "center"),
        ]
        if self._statut_synchro_provider is not None:
            colonnes.append(("synchro", t("sync_colonne_statut"), 130, "center"))
        self._table = DataTable(self, colonnes)
        self._table.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_L,
                         pady=theme.PAD)
        self._table.tree.bind("<<TreeviewSelect>>", self._afficher_detail)

        # Détail + actions
        bas = ttk.Frame(self)
        bas.grid(row=3, column=0, sticky="nsew", padx=theme.PAD_L,
                 pady=(0, theme.PAD_L))
        bas.columnconfigure(0, weight=1)
        bas.rowconfigure(1, weight=1)
        entete_bas = ttk.Frame(bas)
        entete_bas.grid(row=0, column=0, sticky="ew")
        ttk.Label(entete_bas, text=t("ventes_detail"),
                  style="SousTitre.TLabel", background=theme.COULEURS["fond"]).pack(
            side="left")
        self._label_remise_detail = tk.Label(
            entete_bas, text="", bg=theme.COULEURS["fond"],
            fg=theme.COULEURS["danger"], font=theme.POLICES["petit"])
        self._label_remise_detail.pack(side="left", padx=(theme.PAD, 0))
        ttk.Button(entete_bas, text="🗑 " + t("supprimer"), style="Danger.TButton",
                   command=self._supprimer).pack(side="right", padx=(8, 0))
        ttk.Button(entete_bas, text="✎ " + t("ventes_modifier"),
                   command=self._modifier).pack(side="right", padx=(8, 0))
        ttk.Button(entete_bas, text=t("ventes_bordereau"),
                   command=self._bordereau).pack(side="right", padx=(8, 0))
        ttk.Button(entete_bas, text=t("ventes_reimprimer"), style="Accent.TButton",
                   command=self._reimprimer).pack(side="right")
        self._detail = DataTable(bas, [
            ("quantite", t("fact_quantite"), 80, "center"),
            ("designation", t("fact_designation"), 320, "w"),
            ("pu", t("fact_prix_unitaire"), 110, "e"),
            ("total", t("fact_prix_total"), 120, "e"),
        ], hauteur=6)
        self._detail.grid(row=1, column=0, sticky="nsew", pady=(theme.PAD_S, 0))

    # Données -----------------------------------------------------------------
    def rafraichir(self) -> None:
        """Recharge la liste selon les filtres courants (jamais les archivées)."""
        clients = self._clients_repo.lister()
        self._clients = clients
        # Étiquette "NOM — adresse" pour distinguer les clients homonymes
        self._clients_par_libelle = {libelle_client(c): c for c in clients}
        self._champ_client.definir_valeurs(list(self._clients_par_libelle))

        date_debut = date_fin = None
        try:
            if self.var_du.get().strip():
                date_debut = parse_date_affichage(self.var_du.get())
            if self.var_au.get().strip():
                date_fin = parse_date_affichage(self.var_au.get())
        except ValueError:
            messagebox.showerror(t("erreur"), t("date_invalide"))
            return
        # Champ vide = tous les clients. Sinon : suggestion choisie (étiquette
        # exacte, désambiguïsée) ou, à défaut, repli sur le 1er nom correspondant.
        client_id = None
        texte_saisi = self.var_client.get().strip()
        if texte_saisi:
            client_correspondant = self._clients_par_libelle.get(texte_saisi)
            if client_correspondant is None:
                nom_normalise = texte_saisi.upper()
                client_correspondant = next(
                    (c for c in clients if c.nom == nom_normalise), None)
            if client_correspondant:
                client_id = client_correspondant.id

        self._factures = self.app.facturation.lister_factures(
            date_debut, date_fin, client_id)
        # Filtre numéro : garde les factures dont le n° contient les chiffres saisis
        numero_saisi = self.var_numero.get().strip()
        if numero_saisi:
            self._factures = [f for f in self._factures
                              if numero_saisi in str(f.numero)]
        self._table.vider()
        self._detail.vider()
        for facture in self._factures:
            # "Total" affiché = net facturé (après remise éventuelle) — c'est
            # le montant réellement dû ; la colonne Remise signale son taux.
            total_net = facture.total_liste
            if facture.remise_taux:
                total_net -= round(facture.total_liste * facture.remise_taux / 100)
            ligne = [
                facture.numero, format_date(facture.date_facture),
                facture.client_nom, facture.destination,
                facture.nb_lignes, format_fcfa(total_net, False),
                f"{facture.remise_taux:g}%" if facture.remise_taux else "—",
            ]
            if self._statut_synchro_provider is not None:
                statut = self._statut_synchro_provider(facture.numero)
                ligne.append(t(_LIBELLES_STATUT_SYNCHRO.get(statut, "sync_statut_inconnu")))
            self._table.ajouter(ligne)

    def _reinitialiser(self) -> None:
        self.var_du.set("")
        self.var_au.set("")
        self.var_client.set("")
        self.var_numero.set("")
        self.rafraichir()

    def _facture_selectionnee(self):
        iid = self._table.selection_iid()
        if iid is None:
            return None
        return self._factures[self._table.tree.index(iid)]

    def _afficher_detail(self, _evenement) -> None:
        facture = self._facture_selectionnee()
        self._detail.vider()
        self._label_remise_detail.configure(text="")
        if facture is None:
            return
        complete = self.app.facturation.obtenir_facture(facture.id)
        for ligne in complete.lignes:
            self._detail.ajouter([
                format_nombre(ligne.quantite), ligne.designation,
                format_fcfa(ligne.prix_unitaire, False),
                format_fcfa(ligne.total, False),
            ])
        if complete.remise_taux:
            self._label_remise_detail.configure(text=t("ventes_remise_appliquee").format(
                f"{complete.remise_taux:g}", format_fcfa(complete.remise_montant)))

    # Actions -----------------------------------------------------------------
    def _reimprimer(self) -> None:
        facture = self._facture_selectionnee()
        if facture is None:
            return
        complete = self.app.facturation.obtenir_facture(facture.id)
        chemin = self.app.pdf.generer_facture(complete)
        afficher_toast(self, t("fact_pdf_genere") + chemin.name)
        ouvrir_fichier(chemin)

    def _bordereau(self) -> None:
        facture = self._facture_selectionnee()
        if facture is None:
            return
        complete = self.app.facturation.obtenir_facture(facture.id)
        chemin = self.app.pdf.generer_bordereau(complete)
        afficher_toast(self, t("fact_pdf_genere") + chemin.name)
        ouvrir_fichier(chemin)

    def _modifier(self) -> None:
        """Bascule sur la page Facturation avec cette facture chargée pour
        correction (en-tête + lignes), au lieu de la supprimer et la ressaisir."""
        facture = self._facture_selectionnee()
        if facture is None:
            return
        complete = self.app.facturation.obtenir_facture(facture.id)
        self.app.afficher_vue("facturation")
        self.app.obtenir_vue("facturation").charger_pour_edition(complete)

    def _exporter_excel(self) -> None:
        """Exporte l'ensemble de l'historique en .xlsx et l'ouvre."""
        chemin = self.app.export_excel.exporter_historique()
        afficher_toast(self, t("ventes_excel_genere") + chemin.name)
        ouvrir_fichier(chemin)

    def _supprimer(self) -> None:
        facture = self._facture_selectionnee()
        if facture is None:
            return
        if not messagebox.askyesno(t("confirmer"), t("confirmation_suppression")):
            return
        self.app.facturation.supprimer_facture(facture.id)
        afficher_toast(self, t("ventes_supprimee"))
        self.rafraichir()
