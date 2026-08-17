"""Vue Clients : répertoire des clients."""
from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.models import Client
from app.repositories.client_repository import ClientRepository
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.formatting import libelle_client
from app.utils.validation import ErreurValidation, valider_non_vide


class ClientsView(ttk.Frame):
    """Répertoire des clients."""

    def __init__(self, parent: tk.Misc, application,
                 repository: ClientRepository | None = None,
                 autoriser_dissociation: bool = True) -> None:
        super().__init__(parent)
        self.app = application
        # `repository` : la machine de facturation (offline-first) injecte
        # `ClientRepositoryHorsLigne` pour enfiler les créations en attente
        # de synchro — voir CLAUDE.md, section « Machine de facturation ».
        self._repo = repository or ClientRepository(application.conn)
        # Conservé pour compatibilité de signature (machine de facturation) —
        # sans effet : la dissociation n'existe plus dans cette vue.
        self._autoriser_dissociation = autoriser_dissociation
        self._clients: list[Client] = []
        self._affiches: list[Client] = []
        self._selection: Client | None = None
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text=t("cli_titre"), style="Titre.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w",
            padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD))

        # Recherche
        self.var_recherche = tk.StringVar()
        self.var_recherche.trace_add("write", lambda *_: self._filtrer())
        recherche = ttk.Entry(self, textvariable=self.var_recherche, width=36)
        recherche.grid(row=1, column=0, sticky="w", padx=theme.PAD_L)
        recherche.insert(0, "")

        self._table = DataTable(self, [
            ("nom", t("cli_nom"), 220, "w"),
            ("telephone", t("cli_telephone"), 130, "w"),
            ("adresse", t("cli_adresse"), 220, "w"),
        ])
        self._table.grid(row=2, column=0, sticky="nsew",
                         padx=(theme.PAD_L, theme.PAD), pady=theme.PAD)
        self._table.tree.bind("<<TreeviewSelect>>", self._charger_selection)

        # Formulaire
        forme = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        forme.grid(row=2, column=1, sticky="ns", padx=(0, theme.PAD_L),
                   pady=theme.PAD)
        self.var_nom = tk.StringVar()
        self.var_telephone = tk.StringVar()
        self.var_adresse = tk.StringVar()
        self._erreur = tk.StringVar()

        rang = 0
        for libelle, variable in [
            (t("cli_nom"), self.var_nom),
            (t("cli_telephone"), self.var_telephone),
            (t("cli_adresse"), self.var_adresse),
        ]:
            tk.Label(forme, text=libelle, bg=theme.COULEURS["carte"],
                     font=theme.POLICES["petit"],
                     fg=theme.COULEURS["texte_secondaire"]).grid(
                row=rang, column=0, sticky="w", padx=theme.PAD, pady=(theme.PAD_S, 0))
            ttk.Entry(forme, textvariable=variable, width=26).grid(
                row=rang + 1, column=0, sticky="ew", padx=theme.PAD)
            rang += 2

        tk.Label(forme, textvariable=self._erreur, bg=theme.COULEURS["carte"],
                 fg=theme.COULEURS["danger"], font=theme.POLICES["petit"],
                 wraplength=200, justify="left").grid(
            row=rang, column=0, sticky="w", padx=theme.PAD)
        ttk.Button(forme, text=t("enregistrer"), style="Accent.TButton",
                   command=self._enregistrer).grid(
            row=rang + 1, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD_S, 4))
        ttk.Button(forme, text=t("ajouter"), command=self._nouveau).grid(
            row=rang + 2, column=0, sticky="ew", padx=theme.PAD, pady=(0, 4))
        ttk.Button(forme, text=t("supprimer"), style="Danger.TButton",
                   command=self._supprimer).grid(
            row=rang + 3, column=0, sticky="ew", padx=theme.PAD, pady=(0, 4))
        rang += 4
        # Correction de données déjà en base : doublons à fusionner
        ttk.Button(forme, text="⇄ " + t("cli_fusionner"),
                   command=self._ouvrir_fusion).grid(
            row=rang, column=0, sticky="ew", padx=theme.PAD, pady=(0, theme.PAD))

    # Données -----------------------------------------------------------------
    def rafraichir(self) -> None:
        self._clients = self._repo.lister()
        self._filtrer()

    def _filtrer(self) -> None:
        terme = self.var_recherche.get().strip().upper()
        self._affiches = [c for c in self._clients if terme in c.nom.upper()]
        self._table.vider()
        for client in self._affiches:
            self._table.ajouter([client.nom, client.telephone, client.adresse])

    def _charger_selection(self, _evenement) -> None:
        iid = self._table.selection_iid()
        if iid is None:
            return
        self._selection = self._affiches[self._table.tree.index(iid)]
        self.var_nom.set(self._selection.nom)
        self.var_telephone.set(self._selection.telephone)
        self.var_adresse.set(self._selection.adresse)

    def _nouveau(self) -> None:
        self._selection = None
        for variable in (self.var_nom, self.var_telephone, self.var_adresse):
            variable.set("")
        self._erreur.set("")

    def _enregistrer(self) -> None:
        self._erreur.set("")
        try:
            nom = valider_non_vide(self.var_nom.get())
        except ErreurValidation as erreur:
            self._erreur.set(t(erreur.cle_message))
            return
        telephone = self.var_telephone.get().strip()
        adresse = self.var_adresse.get().strip()
        try:
            if self._selection:
                self._selection.nom = nom
                self._selection.telephone = telephone
                self._selection.adresse = adresse
                # Un même numéro de téléphone, une fois affecté, ne doit
                # jamais rester réparti sur deux fiches — fusionne d'abord
                # un éventuel doublon déjà titulaire de ce numéro (voir
                # ClientMaintenanceService.fusionner_doublon_telephone),
                # avant d'enregistrer la modification elle-même.
                self.app.clients_maintenance.fusionner_doublon_telephone(self._selection)
                self._repo.modifier(self._selection)
            else:
                # `obtenir_ou_creer` réutilise une fiche existante du même
                # téléphone au lieu de lever un conflit d'unicité — même
                # logique que la résolution client à la facturation.
                self._repo.obtenir_ou_creer(nom, telephone=telephone, adresse=adresse)
        except sqlite3.IntegrityError:
            self._erreur.set(t("cli_existe"))
            return
        afficher_toast(self, t("cli_enregistre"))
        self.rafraichir()

    def _supprimer(self) -> None:
        if self._selection is None:
            return
        if not messagebox.askyesno(t("confirmer"), t("confirmation_suppression")):
            return
        self._repo.supprimer(self._selection.id)
        self._nouveau()
        self.rafraichir()

    # Correction de données existantes : fusion --------------------------------
    def _ouvrir_fusion(self) -> None:
        """Fusionne un doublon (typo d'adresse, homonyme non voulu) dans le
        client actuellement sélectionné."""
        if self._selection is None:
            return
        cible = self._selection
        fenetre = tk.Toplevel(self)
        fenetre.title(t("cli_fusion_titre"))
        fenetre.configure(bg=theme.COULEURS["carte"])
        fenetre.transient(self.winfo_toplevel())
        fenetre.grab_set()

        tk.Label(fenetre, text=t("cli_fusion_titre"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["sous_titre"]).pack(
            anchor="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))
        tk.Label(fenetre, text=f"{t('fact_client')} : {libelle_client(cible)}",
                 bg=theme.COULEURS["carte"], font=theme.POLICES["normal"]).pack(
            anchor="w", padx=theme.PAD_L)
        tk.Label(fenetre, text=t("cli_fusion_description"),
                 bg=theme.COULEURS["carte"], fg=theme.COULEURS["texte_secondaire"],
                 font=theme.POLICES["petit"], wraplength=380, justify="left").pack(
            anchor="w", padx=theme.PAD_L, pady=(4, theme.PAD))
        tk.Label(fenetre, text=t("cli_fusion_choisir"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).pack(
            anchor="w", padx=theme.PAD_L)

        autres = {libelle_client(c): c for c in self._clients if c.id != cible.id}
        var_source = tk.StringVar()
        champ_source = AutocompleteEntry(fenetre, largeur=34,
                                         textvariable=var_source)
        champ_source.definir_valeurs(list(autres))
        champ_source.pack(fill="x", padx=theme.PAD_L, pady=(2, theme.PAD))

        def confirmer() -> None:
            source = autres.get(var_source.get())
            if source is None:
                messagebox.showwarning(t("attention"),
                                       t("cli_fusion_aucune_selection"))
                return
            message = t("cli_fusion_confirmation").format(
                libelle_client(source), libelle_client(cible))
            if not messagebox.askyesno(t("confirmer"), message):
                return
            self.app.clients_maintenance.fusionner(cible.id, source.id)
            fenetre.destroy()
            afficher_toast(self, t("cli_fusion_reussie"))
            self.rafraichir()

        boutons = ttk.Frame(fenetre)
        boutons.pack(fill="x", padx=theme.PAD_L, pady=(0, theme.PAD_L))
        ttk.Button(boutons, text=t("annuler"),
                   command=fenetre.destroy).pack(side="right")
        ttk.Button(boutons, text=t("cli_fusionner"), style="Accent.TButton",
                   command=confirmer).pack(side="right", padx=(0, 8))
