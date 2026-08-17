"""Vue « Vue client » (app principale) : synthèse d'un client sélectionné
(total dépensé, versé, restant dû, remises), liste de toutes ses factures sur
la période filtrée, et détail (contenu + versements) de la facture
sélectionnée — voir CLAUDE.md, section « Paiements »."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.ui import theme
from app.ui.components.champ_date import ChampDate
from app.ui.components.data_table import DataTable
from app.ui.components.kpi_card import KPICard
from app.utils.formatting import (
    format_date, format_fcfa, format_nombre, libelle_client, parse_date_affichage,
)


class VueClientView(ttk.Frame):
    """Recherche client puis affichage de sa synthèse de paiements, de la
    liste de ses factures et du détail (contenu + versements) de la facture
    sélectionnée."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._resultats = []
        self._client_id: int | None = None
        self._filtre_actif: dict = {}  # {} = toutes années ; sinon annee=.. ou date_debut/date_fin=..
        self._factures: list = []  # [(Facture, SoldeFacture), ...] du client filtré
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        ttk.Label(self, text=t("vue_client_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L,
            pady=(theme.PAD_L, theme.PAD))

        barre = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        barre.grid(row=1, column=0, sticky="ew", padx=theme.PAD_L)
        tk.Label(barre, text=t("rechercher"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        self.var_recherche = tk.StringVar()
        self.var_recherche.trace_add("write", lambda *_: self._rechercher())
        ttk.Entry(barre, textvariable=self.var_recherche, width=30).pack(side="left")
        tk.Label(barre, text=t("rem_annee"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD_L, 4))
        annee_courante = date.today().year
        self.var_annee = tk.StringVar(value=t("vue_client_toutes_annees"))
        self._combo_annee = ttk.Combobox(
            barre, textvariable=self.var_annee, state="readonly", width=18,
            values=[t("vue_client_toutes_annees")]
                  + [str(a) for a in range(annee_courante, annee_courante - 8, -1)],
        )
        self._combo_annee.pack(side="left")
        self._combo_annee.bind("<<ComboboxSelected>>", lambda _e: self._filtrer_par_annee())

        tk.Label(barre, text=t("vue_client_periode_precise"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD_L, 4))
        tk.Label(barre, text=t("du"), bg=theme.COULEURS["carte"]).pack(side="left")
        self._champ_du = ChampDate(barre, largeur=12)
        self._champ_du.pack(side="left", padx=(4, 8))
        self._champ_du.vider()
        tk.Label(barre, text=t("au"), bg=theme.COULEURS["carte"]).pack(side="left")
        self._champ_au = ChampDate(barre, largeur=12)
        self._champ_au.pack(side="left", padx=(4, 8))
        self._champ_au.vider()
        ttk.Button(barre, text=t("filtrer"), command=self._filtrer_periode).pack(side="left")
        ttk.Button(barre, text=t("reinitialiser"),
                  command=self._reinitialiser_periode).pack(side="left", padx=(6, 0))

        self._liste = tk.Listbox(self, height=6)
        self._liste.grid(row=2, column=0, sticky="ew", padx=theme.PAD_L, pady=(theme.PAD, 0))
        self._liste.bind("<<ListboxSelect>>", lambda _e: self._selectionner())

        cartes = ttk.Frame(self)
        cartes.grid(row=3, column=0, sticky="ew", padx=theme.PAD_L, pady=theme.PAD_L)
        for i in range(4):
            cartes.columnconfigure(i, weight=1)
        self._carte_depense = KPICard(cartes, t("vue_client_total_depense"))
        self._carte_verse = KPICard(cartes, t("vue_client_total_verse"))
        self._carte_restant = KPICard(cartes, t("vue_client_total_restant"))
        self._carte_remises = KPICard(cartes, t("vue_client_total_remises"))
        for i, carte in enumerate((self._carte_depense, self._carte_verse,
                                   self._carte_restant, self._carte_remises)):
            carte.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else theme.PAD, 0))

        # Factures du client (période filtrée) + détail (contenu + versements)
        corps = ttk.PanedWindow(self, orient="horizontal")
        corps.grid(row=4, column=0, sticky="nsew", padx=theme.PAD_L, pady=(0, theme.PAD_L))

        cadre_factures = ttk.Frame(corps)
        ttk.Label(cadre_factures, text=t("vue_client_factures"),
                  style="SousTitre.TLabel").pack(anchor="w", pady=(0, 4))
        self._table_factures = DataTable(cadre_factures, [
            ("numero", t("ventes_numero"), 80, "center"),
            ("date", t("date"), 100, "center"),
            ("telephone", t("fact_telephone"), 100, "center"),
            ("total", t("total"), 110, "e"),
            ("verse", t("paie_verse"), 110, "e"),
            ("restant", t("paie_restant"), 110, "e"),
        ])
        self._table_factures.pack(fill="both", expand=True)
        for tag, couleur in (("restant_du", theme.COULEURS["danger"]),
                            ("restant_solde", theme.COULEURS["succes"]),
                            ("restant_trop_percu", theme.COULEURS["info"])):
            self._table_factures.tree.tag_configure(tag, foreground=couleur)
        self._table_factures.tree.bind(
            "<<TreeviewSelect>>", lambda _e: self._afficher_detail_facture())
        corps.add(cadre_factures, weight=2)

        cadre_detail = ttk.Frame(corps, padding=(theme.PAD, 0))
        ttk.Label(cadre_detail, text=t("vue_client_contenu_facture"),
                  style="SousTitre.TLabel").pack(anchor="w")
        self._table_contenu = DataTable(cadre_detail, [
            ("quantite", t("fact_quantite"), 70, "center"),
            ("designation", t("fact_designation"), 260, "w"),
            ("pu", t("fact_prix_unitaire"), 90, "e"),
            ("total", t("fact_prix_total"), 100, "e"),
        ], hauteur=6)
        self._table_contenu.pack(fill="both", expand=True, pady=(4, theme.PAD))
        ttk.Label(cadre_detail, text=t("paie_historique_versements"),
                  style="SousTitre.TLabel").pack(anchor="w")
        self._liste_versements = tk.Listbox(cadre_detail, height=8)
        self._liste_versements.pack(fill="both", expand=True, pady=(4, 0))
        corps.add(cadre_detail, weight=1)

    def rafraichir(self) -> None:
        self._liste.delete(0, "end")
        self._resultats = []
        self._client_id = None
        self._factures = []
        self._table_factures.vider()
        self._table_contenu.vider()
        self._liste_versements.delete(0, "end")
        for carte in (self._carte_depense, self._carte_verse, self._carte_restant,
                     self._carte_remises):
            carte.definir("—")

    def _rechercher(self) -> None:
        q = self.var_recherche.get().strip()
        self._liste.delete(0, "end")
        if not q:
            self._resultats = []
            return
        self._resultats = self.app.paiements.rechercher_clients(q)
        for client in self._resultats:
            self._liste.insert("end", libelle_client(client))

    def _selectionner(self) -> None:
        selection = self._liste.curselection()
        if not selection:
            return
        client = self._resultats[selection[0]]
        self._client_id = client.id
        self._rafraichir_synthese()

    def _annee_selectionnee(self) -> int | None:
        """Année choisie dans le filtre période, ou None pour « Toutes »."""
        valeur = self.var_annee.get()
        return int(valeur) if valeur.isdigit() else None

    def _parse_champ_date(self, champ: ttk.Entry) -> date | None:
        texte = champ.get().strip()
        if not texte:
            return None
        try:
            return parse_date_affichage(texte)
        except ValueError:
            messagebox.showerror(t("erreur"), t("date_invalide"))
            return None

    def _filtrer_par_annee(self) -> None:
        """Le sélecteur d'année est prioritaire uniquement si aucune période
        précise (Du/Au) n'est déjà saisie — sinon, réinitialise Du/Au."""
        self._champ_du.delete(0, "end")
        self._champ_au.delete(0, "end")
        self._filtre_actif = {"annee": self._annee_selectionnee()}
        self._rafraichir_synthese()

    def _filtrer_periode(self) -> None:
        """Filtre sur une période précise (Du/Au) — prioritaire sur le
        sélecteur d'année, pour bien définir n'importe quelle période
        (ex. un mois précis) plutôt qu'une année entière."""
        date_debut = self._parse_champ_date(self._champ_du)
        date_fin = self._parse_champ_date(self._champ_au)
        if date_debut is None and date_fin is None:
            return
        self._filtre_actif = {"date_debut": date_debut, "date_fin": date_fin}
        self._rafraichir_synthese()

    def _reinitialiser_periode(self) -> None:
        self._champ_du.delete(0, "end")
        self._champ_au.delete(0, "end")
        self.var_annee.set(t("vue_client_toutes_annees"))
        self._filtre_actif = {}
        self._rafraichir_synthese()

    def _lister_factures_filtrees(self) -> list:
        """Factures usine du client sélectionné correspondant au filtre de
        période actif (même logique que `total_depense_par_client` : une
        période précise, sinon une année, sinon tout l'historique)."""
        if self._client_id is None:
            return []
        if "date_debut" in self._filtre_actif or "date_fin" in self._filtre_actif:
            return self.app.paiements.lister_avec_solde(
                client_id=self._client_id,
                date_debut=self._filtre_actif.get("date_debut"),
                date_fin=self._filtre_actif.get("date_fin"),
                inclure_archivees=True,
            )
        resultat = self.app.paiements.lister_avec_solde(
            client_id=self._client_id, inclure_archivees=True)
        annee = self._filtre_actif.get("annee")
        if annee is not None:
            resultat = [(f, s) for f, s in resultat if f.date_facture.year == annee]
        return resultat

    def _rafraichir_synthese(self) -> None:
        self._table_contenu.vider()
        self._liste_versements.delete(0, "end")
        if self._client_id is None:
            return
        synthese = self.app.paiements.total_depense_par_client(
            self._client_id, **self._filtre_actif)
        self._carte_depense.definir(format_fcfa(synthese.total_facture))
        self._carte_verse.definir(format_fcfa(synthese.total_verse))
        self._carte_restant.definir(format_fcfa(synthese.total_restant))
        self._carte_remises.definir(format_fcfa(synthese.total_remises))

        self._factures = self._lister_factures_filtrees()
        self._table_factures.vider()
        for facture, solde in self._factures:
            tag_couleur = ("restant_du" if solde.restant > 0
                          else "restant_solde" if solde.restant == 0
                          else "restant_trop_percu")
            self._table_factures.tree.insert(
                "", "end", iid=str(facture.id),
                tags=(theme.tag_alternance(len(self._table_factures.tree.get_children())),
                     tag_couleur),
                values=(facture.numero, format_date(facture.date_facture),
                       facture.telephone, format_fcfa(solde.total),
                       format_fcfa(solde.verse), format_fcfa(solde.restant)),
            )

    def _afficher_detail_facture(self) -> None:
        self._table_contenu.vider()
        self._liste_versements.delete(0, "end")
        iid = self._table_factures.selection_iid()
        if iid is None:
            return
        facture_id = int(iid)
        complete = self.app.paiements.obtenir_facture(facture_id)
        if complete is not None:
            for ligne in complete.lignes:
                self._table_contenu.ajouter([
                    format_nombre(ligne.quantite), ligne.designation,
                    format_fcfa(ligne.prix_unitaire, False),
                    format_fcfa(ligne.total, False),
                ])
        versements = self.app.paiements.historique_versements(facture_id)
        if not versements:
            self._liste_versements.insert("end", t("paie_aucun_versement"))
        for v in versements:
            texte = (f"{format_date(v.date_versement)}  "
                    f"{format_fcfa(v.montant)}  ({v.role_origine or 'local'})")
            if v.remarque:
                texte += f"   — {v.remarque}"
            self._liste_versements.insert("end", texte)
