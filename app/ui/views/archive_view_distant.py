"""Vue Archive distante (machine de facturation en mode étendu) : même UI que
`ArchiveView`, mais lecture/écriture **en direct par le réseau** (jamais de
cache local, jamais de mode hors ligne) via `application.api_admin`
(`ApiSyncClient`, rôle `role_facturation`). Voir CLAUDE.md, section « Machine
de facturation »."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.repositories.client_repository import ClientRepository
from app.sync.api_sync_client import ErreurApiSync
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.champ_date import ChampDate
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.formatting import format_fcfa, iso_vers_date, format_date, libelle_client, \
    parse_date_affichage


class ArchiveDistantView(ttk.Frame):
    """Sélection multiple de factures usine à archiver/désarchiver — données
    lues en direct sur la machine boss (jamais depuis le cache local)."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        # Autocomplétion client : référentiel déjà synchronisé dans le cache
        # local (ReferentielSyncWorker) — une simple commodité de saisie,
        # jamais utilisé pour les données de factures elles-mêmes.
        self._clients_repo = ClientRepository(application.conn)
        self._factures: list[dict] = []
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        ttk.Label(self, text=t("archive_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))
        tk.Label(self, text=t("archive_description"), bg=theme.COULEURS["fond"],
                 fg=theme.COULEURS["texte_secondaire"], font=theme.POLICES["petit"],
                 wraplength=940, justify="left").grid(
            row=1, column=0, sticky="w", padx=theme.PAD_L, pady=(0, theme.PAD))

        filtres = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                           highlightbackground=theme.COULEURS["bordure"])
        filtres.grid(row=2, column=0, sticky="ew", padx=theme.PAD_L)
        self.var_mode = tk.StringVar(value=t("archive_mode_actives"))
        self.var_du = tk.StringVar()
        self.var_au = tk.StringVar()
        self.var_client = tk.StringVar()
        self.var_numero = tk.StringVar()

        tk.Label(filtres, text=t("archive_afficher"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        ttk.Combobox(filtres, textvariable=self.var_mode, state="readonly", width=16,
                     values=[t("archive_mode_actives"), t("archive_mode_archivees")]).pack(
            side="left")
        self.var_mode.trace_add("write", lambda *_: self.rafraichir())
        tk.Label(filtres, text=t("ventes_numero"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        entree_numero = ttk.Entry(filtres, textvariable=self.var_numero, width=10)
        entree_numero.pack(side="left")
        entree_numero.bind("<Return>", lambda _e: self.rafraichir())
        tk.Label(filtres, text=t("du"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
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
        self._champ_client = AutocompleteEntry(filtres, largeur=22,
                                               textvariable=self.var_client,
                                               on_select=lambda _v: self.rafraichir())
        self._champ_client.pack(side="left")
        ttk.Button(filtres, text=t("filtrer"), style="Accent.TButton",
                   command=self.rafraichir).pack(side="left", padx=theme.PAD)
        ttk.Button(filtres, text=t("reinitialiser"),
                   command=self._reinitialiser).pack(side="left")

        self._table = DataTable(self, [
            ("numero", t("ventes_numero"), 90, "center"),
            ("date", t("date"), 100, "center"),
            ("client", t("fact_client"), 220, "w"),
            ("destination", t("fact_destination"), 150, "w"),
            ("lignes", t("ventes_lignes"), 70, "center"),
            ("total", t("total"), 130, "e"),
        ])
        self._table.grid(row=3, column=0, sticky="nsew", padx=theme.PAD_L, pady=theme.PAD)
        self._table.tree.configure(selectmode="extended")
        self._table.tree.bind("<<TreeviewSelect>>", self._maj_compteur_selection)

        barre = ttk.Frame(self)
        barre.grid(row=4, column=0, sticky="ew", padx=theme.PAD_L, pady=(0, theme.PAD_L))
        self._label_selection = ttk.Label(barre, text="")
        self._label_selection.pack(side="left")
        ttk.Button(barre, text=t("archive_tout_selectionner"),
                   command=self._tout_selectionner).pack(side="left", padx=theme.PAD)
        self._bouton_action = ttk.Button(barre, style="Accent.TButton",
                                         command=self._traiter_selection)
        self._bouton_action.pack(side="right")

    def _mode_archivees(self) -> bool:
        return self.var_mode.get() == t("archive_mode_archivees")

    def rafraichir(self) -> None:
        clients = self._clients_repo.lister()
        self._clients_par_libelle = {libelle_client(c): c for c in clients}
        self._champ_client.definir_valeurs(list(self._clients_par_libelle))

        mode_archivees = self._mode_archivees()
        self._bouton_action.configure(
            text=("♻ " + t("archive_bouton_desarchiver")) if mode_archivees
            else ("🗄 " + t("archive_bouton_archiver")))

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
            if client_correspondant:
                client_id = client_correspondant.id

        try:
            toutes = self.app.api_admin.lister_factures_admin(
                date_debut=date_debut, date_fin=date_fin, client_id=client_id)
        except ErreurApiSync as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return

        self._factures = [f for f in toutes if f["archivee"] == mode_archivees]
        numero_saisi = self.var_numero.get().strip()
        if numero_saisi:
            self._factures = [f for f in self._factures
                              if numero_saisi in str(f["numero"])]

        self._table.vider()
        for facture in self._factures:
            self._table.ajouter([
                facture["numero"], format_date(iso_vers_date(facture["date_facture"])),
                facture["client_nom"], facture["destination"],
                facture["nb_lignes"], format_fcfa(facture["total"], False),
            ])
        self._maj_compteur_selection()

    def _reinitialiser(self) -> None:
        self.var_du.set("")
        self.var_au.set("")
        self.var_client.set("")
        self.var_numero.set("")
        self.rafraichir()

    def _tout_selectionner(self) -> None:
        self._table.tree.selection_set(self._table.tree.get_children())

    def _maj_compteur_selection(self, _evenement=None) -> None:
        nb = len(self._table.tree.selection())
        self._label_selection.configure(
            text=t("archive_selection_compte").format(nb) if nb else "")

    def _traiter_selection(self) -> None:
        iids = self._table.tree.selection()
        if not iids:
            messagebox.showwarning(t("attention"), t("archive_selection_vide"))
            return
        ids_factures = [self._factures[self._table.tree.index(iid)]["id"] for iid in iids]

        try:
            if self._mode_archivees():
                nb = self.app.api_admin.desarchiver_ids(ids_factures)
                afficher_toast(self, t("desarchive_resultat").format(nb))
            else:
                if not messagebox.askyesno(
                    t("confirmer"), t("archive_confirmation").format(len(ids_factures))
                ):
                    return
                nb = self.app.api_admin.archiver_ids(ids_factures)
                afficher_toast(self, t("archive_resultat").format(nb))
        except ErreurApiSync as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        self.rafraichir()
