"""Vue Paiements (app principale) : miroir en lecture seule de l'onglet
Paiements de l'app cliente — recherche, filtre période/client, solde par
facture, historique des versements, totaux. Aucun bouton d'ajout de
versement ni d'impression (voir CLAUDE.md, section « Paiements » :
role_principal est lecture seule ici, mais accède directement à
`PaiementService` sans passer par l'API, la base étant locale)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.repositories.client_repository import ClientRepository
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.champ_date import ChampDate
from app.ui.components.data_table import DataTable
from app.utils.fichiers import ouvrir_fichier
from app.utils.formatting import format_date, format_fcfa, libelle_client, parse_date_affichage


class PaiementsView(ttk.Frame):
    """Recherche + filtre période/client + liste des factures avec solde +
    historique versements."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._clients_repo = ClientRepository(application.conn)
        self._factures: list = []  # [(Facture, SoldeFacture), ...]
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text=t("paie_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L,
            pady=(theme.PAD_L, theme.PAD))

        # Barre de navigation : recherche libre + filtre période/client, pour
        # naviguer dans un historique de paiements potentiellement long sans
        # dépendre uniquement du texte libre (mêmes filtres que l'historique
        # des ventes — voir `VentesView`).
        barre = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        barre.grid(row=1, column=0, sticky="ew", padx=theme.PAD_L)
        tk.Label(barre, text=t("paie_rechercher"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        self.var_recherche = tk.StringVar()
        self.var_recherche.trace_add("write", lambda *_: self.rafraichir())
        ttk.Entry(barre, textvariable=self.var_recherche, width=22).pack(side="left")

        tk.Label(barre, text=t("du"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        self.var_du = tk.StringVar()
        champ_du = ChampDate(barre, largeur=11, textvariable=self.var_du)
        champ_du.pack(side="left")
        champ_du.vider()
        tk.Label(barre, text=t("au"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        self.var_au = tk.StringVar()
        champ_au = ChampDate(barre, largeur=11, textvariable=self.var_au)
        champ_au.pack(side="left")
        champ_au.vider()
        tk.Label(barre, text=t("fact_client"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        self.var_client = tk.StringVar()
        self._champ_client = AutocompleteEntry(barre, largeur=20,
                                               textvariable=self.var_client,
                                               on_select=lambda _v: self.rafraichir())
        self._champ_client.pack(side="left")
        ttk.Button(barre, text=t("filtrer"), style="Accent.TButton",
                  command=self.rafraichir).pack(side="left", padx=(theme.PAD, 0))
        ttk.Button(barre, text=t("reinitialiser"),
                  command=self._reinitialiser).pack(side="left", padx=(4, 0))
        ttk.Button(barre, text=t("paie_exporter_rapport"),
                  command=self._exporter_excel).pack(side="right", padx=theme.PAD)

        corps = ttk.PanedWindow(self, orient="horizontal")
        corps.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_L, pady=theme.PAD)

        self._table = DataTable(corps, [
            ("numero", "N°", 90, "center"),
            ("date", t("date"), 100, "center"),
            ("client", t("fact_client"), 220, "w"),
            ("telephone", t("fact_telephone"), 110, "center"),
            ("total", t("paie_total"), 120, "e"),
            ("verse", t("paie_verse"), 120, "e"),
            ("restant", t("paie_restant"), 120, "e"),
        ])
        for tag, couleur in (("restant_du", theme.COULEURS["danger"]),
                            ("restant_solde", theme.COULEURS["succes"]),
                            ("restant_trop_percu", theme.COULEURS["info"])):
            self._table.tree.tag_configure(tag, foreground=couleur)
        self._table.tree.bind("<<TreeviewSelect>>", lambda _e: self._afficher_detail())
        corps.add(self._table, weight=2)

        cadre_detail = ttk.Frame(corps, padding=(theme.PAD, 0))
        ttk.Label(cadre_detail, text=t("paie_historique_versements"),
                  style="SousTitre.TLabel").pack(anchor="w")
        self._liste_versements = tk.Listbox(cadre_detail, height=14)
        self._liste_versements.pack(fill="both", expand=True, pady=(4, 0))
        corps.add(cadre_detail, weight=1)

        self._label_totaux = ttk.Label(
            self, text="", font=theme.POLICES["total_gros"],
            foreground=theme.COULEURS["accent_sombre"],
            padding=(theme.PAD_L, theme.PAD_S))
        self._label_totaux.grid(row=3, column=0, sticky="w")

    def rafraichir(self) -> None:
        clients = self._clients_repo.lister()
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

        recherche = self.var_recherche.get().strip()
        self._factures = self.app.paiements.lister_avec_solde(
            recherche=recherche, client_id=client_id,
            date_debut=date_debut, date_fin=date_fin)
        self._table.vider()
        for indice, (facture, solde) in enumerate(self._factures):
            tag_couleur = ("restant_du" if solde.restant > 0
                          else "restant_solde" if solde.restant == 0
                          else "restant_trop_percu")
            self._table.tree.insert(
                "", "end", iid=str(facture.id),
                tags=(theme.tag_alternance(indice), tag_couleur),
                values=(facture.numero, format_date(facture.date_facture),
                       facture.client_nom, facture.telephone, format_fcfa(solde.total),
                       format_fcfa(solde.verse), format_fcfa(solde.restant)),
            )
        totaux = self.app.paiements.totaux_globaux(
            date_debut=date_debut, date_fin=date_fin, client_id=client_id)
        self._label_totaux.configure(
            text=(f"{t('paie_totaux_periode')} — {t('paie_total')} : "
                 f"{format_fcfa(totaux.total_facture)}   {t('paie_verse')} : "
                 f"{format_fcfa(totaux.total_verse)}   {t('paie_restant')} : "
                 f"{format_fcfa(totaux.total_restant)}"))
        self._liste_versements.delete(0, "end")

    def _reinitialiser(self) -> None:
        self.var_du.set("")
        self.var_au.set("")
        self.var_client.set("")
        self.var_recherche.set("")
        self.rafraichir()

    def _afficher_detail(self) -> None:
        iid = self._table.selection_iid()
        self._liste_versements.delete(0, "end")
        if iid is None:
            return
        versements = self.app.paiements.historique_versements(int(iid))
        if not versements:
            self._liste_versements.insert("end", t("paie_aucun_versement"))
        for v in versements:
            texte = (f"{v.date_versement.strftime('%d/%m/%Y')}  "
                    f"{format_fcfa(v.montant)}  ({v.role_origine or 'local'})")
            if v.remarque:
                texte += f"   — {v.remarque}"
            self._liste_versements.insert("end", texte)

    def _exporter_excel(self) -> None:
        """Exporte l'ensemble actuellement filtré en Excel (en-têtes fixes
        en chinois, une ligne par versement avec sa date et son montant —
        voir `ExportExcelService.exporter_paiements`) et l'ouvre."""
        lignes = [
            {"numero": facture.numero, "client_nom": facture.client_nom,
             "destination": facture.destination, "total": solde.total,
             "verse": solde.verse, "restant": solde.restant,
             "versements": [
                 {"date_versement": v.date_versement, "montant": v.montant}
                 for v in self.app.paiements.historique_versements(facture.id)
             ]}
            for facture, solde in self._factures
        ]
        chemin = self.app.export_excel.exporter_paiements(lignes)
        ouvrir_fichier(chemin)
