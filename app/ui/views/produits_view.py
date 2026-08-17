"""Vue Produits : catalogue et formulaire CRUD."""
from __future__ import annotations

import sqlite3
import tkinter as tk
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.models import Produit
from app.models.produit import TYPE_OPTION_DIMENSION, TYPE_OPTION_LITRAGE
from app.repositories.produit_repository import ProduitRepository
from app.services.stats_service import StatsService
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.formatting import format_fcfa, format_nombre
from app.utils.validation import ErreurValidation, valider_entier_positif, valider_non_vide


class ProduitsView(ttk.Frame):
    """Catalogue des produits : liste (avec quantité vendue et stock) +
    formulaire de modification/fusion. La création d'un nouvel article se
    fait désormais exclusivement depuis l'app Stock (voir CLAUDE.md, section
    « Gestion de stock ») — cette vue ne crée plus rien."""

    def __init__(self, parent: tk.Misc, application,
                 repository: ProduitRepository | None = None,
                 autoriser_fusion: bool = True) -> None:
        super().__init__(parent)
        self.app = application
        # `repository` : la machine de facturation (offline-first) injecte
        # `ProduitRepositoryHorsLigne`, dont la méthode `creer` n'est plus
        # jamais appelée depuis cette vue (conservée pour l'auto-création de
        # secours de `FacturationService`, inatteignable via l'interface).
        self._repo = repository or ProduitRepository(application.conn)
        self._stats = StatsService(application.conn)
        self._autoriser_fusion = autoriser_fusion
        self._produits: list[Produit] = []
        self._affiches: list[Produit] = []
        self._quantites_vendues: dict[int, int] = {}
        self._selection: Produit | None = None
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text=t("prod_titre"), style="Titre.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w",
            padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))

        # Recherche (filtre live sur nom/valeur d'option)
        barre = ttk.Frame(self)
        barre.grid(row=1, column=0, columnspan=2, sticky="ew",
                  padx=theme.PAD_L, pady=(0, theme.PAD))
        self.var_recherche = tk.StringVar()
        self.var_recherche.trace_add("write", lambda *_: self._filtrer())
        ttk.Entry(barre, textvariable=self.var_recherche, width=36).pack(side="left")
        if self._autoriser_fusion:
            ttk.Button(barre, text="⇄ " + t("prod_fusionner"),
                       command=self._ouvrir_fusion).pack(side="left", padx=theme.PAD)

        self._table = DataTable(self, [
            ("nom", t("prod_nom"), 200, "w"),
            ("type_option", t("prod_type_option"), 120, "center"),
            ("valeur_option", t("prod_valeur_option"), 120, "center"),
            ("prix", t("prod_prix"), 110, "e"),
            ("vendu", t("prod_quantite_vendue"), 90, "e"),
            ("stock", t("prod_stock"), 90, "e"),
            ("actif", t("prod_actif"), 60, "center"),
        ])
        self._table.grid(row=2, column=0, sticky="nsew", padx=(theme.PAD_L, theme.PAD),
                         pady=(0, theme.PAD_L))
        self._table.tree.bind("<<TreeviewSelect>>", self._charger_selection)

        # Formulaire
        forme = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        forme.grid(row=2, column=1, sticky="ns", padx=(0, theme.PAD_L),
                   pady=(0, theme.PAD_L))
        self.var_nom = tk.StringVar()
        self.var_type_option = tk.StringVar(value=t("prod_type_option_aucune"))
        self.var_valeur_option = tk.StringVar()
        self.var_prix = tk.StringVar()
        self.var_actif = tk.BooleanVar(value=True)
        self._erreur = tk.StringVar()

        # Correspondance libellé affiché <-> valeur stockée
        self._valeurs_type_option = {
            t("prod_type_option_aucune"): "",
            t("prod_type_option_dimension"): TYPE_OPTION_DIMENSION,
            t("prod_type_option_litrage"): TYPE_OPTION_LITRAGE,
        }
        self._libelles_type_option = {v: k for k, v in self._valeurs_type_option.items()}

        rang = 0
        tk.Label(forme, text=t("prod_nom"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).grid(
            row=rang, column=0, sticky="w", padx=theme.PAD, pady=(theme.PAD_S, 0))
        ttk.Entry(forme, textvariable=self.var_nom, width=24).grid(
            row=rang + 1, column=0, sticky="ew", padx=theme.PAD)
        rang += 2

        tk.Label(forme, text=t("prod_type_option"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).grid(
            row=rang, column=0, sticky="w", padx=theme.PAD, pady=(theme.PAD_S, 0))
        ttk.Combobox(forme, textvariable=self.var_type_option, state="readonly",
                     width=22, values=list(self._valeurs_type_option)).grid(
            row=rang + 1, column=0, sticky="ew", padx=theme.PAD)
        rang += 2

        tk.Label(forme, text=t("prod_valeur_option"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).grid(
            row=rang, column=0, sticky="w", padx=theme.PAD, pady=(theme.PAD_S, 0))
        ttk.Entry(forme, textvariable=self.var_valeur_option, width=24).grid(
            row=rang + 1, column=0, sticky="ew", padx=theme.PAD)
        rang += 2

        tk.Label(forme, text=t("prod_prix"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).grid(
            row=rang, column=0, sticky="w", padx=theme.PAD, pady=(theme.PAD_S, 0))
        ttk.Entry(forme, textvariable=self.var_prix, width=24).grid(
            row=rang + 1, column=0, sticky="ew", padx=theme.PAD)
        rang += 2

        # Stock : lecture seule, géré exclusivement par l'app Stock — jamais
        # de champ modifiable ici, juste un rappel informatif.
        self._label_stock = tk.Label(
            forme, text="", bg=theme.COULEURS["carte"],
            font=theme.POLICES["normal"], fg=theme.COULEURS["texte_secondaire"])
        self._label_stock.grid(row=rang, column=0, sticky="w", padx=theme.PAD,
                               pady=(theme.PAD_S, 0))
        rang += 1

        ttk.Checkbutton(forme, text=t("prod_actif"), variable=self.var_actif).grid(
            row=rang, column=0, sticky="w", padx=theme.PAD, pady=theme.PAD_S)
        tk.Label(forme, textvariable=self._erreur, bg=theme.COULEURS["carte"],
                 fg=theme.COULEURS["danger"], font=theme.POLICES["petit"],
                 wraplength=200, justify="left").grid(
            row=rang + 1, column=0, sticky="w", padx=theme.PAD)
        ttk.Button(forme, text=t("enregistrer"), style="Accent.TButton",
                   command=self._enregistrer).grid(
            row=rang + 2, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD_S, 4))
        ttk.Button(forme, text=t("supprimer"), style="Danger.TButton",
                   command=self._supprimer).grid(
            row=rang + 3, column=0, sticky="ew", padx=theme.PAD, pady=(0, theme.PAD))

    def rafraichir(self) -> None:
        self._produits = self._repo.lister()
        self._quantites_vendues = self._stats.quantite_vendue_par_produit()
        self._filtrer()

    def _filtrer(self) -> None:
        """Filtre live sur le nom ou la valeur d'option saisis."""
        terme = self.var_recherche.get().strip().upper()
        self._affiches = [
            p for p in self._produits
            if terme in p.nom.upper() or terme in p.valeur_option.upper()
        ] if terme else list(self._produits)
        self._table.vider()
        for produit in self._affiches:
            self._table.ajouter([
                produit.nom,
                self._libelles_type_option.get(produit.type_option, ""),
                produit.valeur_option,
                format_fcfa(produit.prix, False),
                format_nombre(self._quantites_vendues.get(produit.id, 0)),
                produit.quantite_stock,
                "✔" if produit.actif else "—",
            ])

    def _charger_selection(self, _evenement) -> None:
        iid = self._table.selection_iid()
        if iid is None:
            return
        self._selection = self._affiches[self._table.tree.index(iid)]
        self.var_nom.set(self._selection.nom)
        self.var_type_option.set(
            self._libelles_type_option.get(self._selection.type_option,
                                           t("prod_type_option_aucune")))
        self.var_valeur_option.set(self._selection.valeur_option)
        self.var_prix.set(str(self._selection.prix))
        self.var_actif.set(self._selection.actif)
        self._label_stock.configure(
            text=f"{t('prod_stock')} : {self._selection.quantite_stock} "
                 f"({t('prod_stock_info')})")

    def _nouveau(self) -> None:
        self._selection = None
        for variable in (self.var_nom, self.var_valeur_option, self.var_prix):
            variable.set("")
        self.var_type_option.set(t("prod_type_option_aucune"))
        self.var_actif.set(True)
        self._erreur.set("")
        self._label_stock.configure(text="")

    def _enregistrer(self) -> None:
        """Modifie le produit sélectionné — la création se fait désormais
        exclusivement depuis l'app Stock, cette vue n'en propose plus."""
        self._erreur.set("")
        if self._selection is None:
            self._erreur.set(t("prod_creation_via_stock"))
            return
        try:
            nom = valider_non_vide(self.var_nom.get()).upper()
            type_option = self._valeurs_type_option.get(self.var_type_option.get(), "")
            valeur_option = self.var_valeur_option.get().strip().upper()
            prix = (valider_entier_positif(self.var_prix.get())
                    if self.var_prix.get().strip() else 0)
        except ErreurValidation as erreur:
            self._erreur.set(t(erreur.cle_message))
            return
        try:
            self._selection.nom = nom
            self._selection.type_option = type_option
            self._selection.valeur_option = valeur_option
            self._selection.prix = prix
            self._selection.actif = self.var_actif.get()
            self._repo.modifier(self._selection)
        except sqlite3.IntegrityError:
            self._erreur.set(t("prod_existe"))
            return
        afficher_toast(self, t("prod_enregistre"))
        self.rafraichir()

    def _supprimer(self) -> None:
        if self._selection is None:
            return
        if not messagebox.askyesno(t("confirmer"), t("confirmation_suppression")):
            return
        try:
            self._repo.supprimer(self._selection.id)
        except sqlite3.IntegrityError:
            messagebox.showerror(t("erreur"), t("stock_produit_utilise"))
            return
        self._nouveau()
        self.rafraichir()

    # Fusion de doublons (typo de saisie créant un produit en trop) -----------
    def _ouvrir_fusion(self) -> None:
        if self._selection is None:
            messagebox.showwarning(t("attention"), t("prod_fusion_choisir_cible"))
            return
        cible = self._selection
        fenetre = tk.Toplevel(self)
        fenetre.title(t("prod_fusionner"))
        fenetre.configure(bg=theme.COULEURS["carte"])
        fenetre.transient(self.winfo_toplevel())
        fenetre.grab_set()

        tk.Label(fenetre, text=t("prod_fusionner"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["sous_titre"]).pack(
            anchor="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))
        tk.Label(fenetre, text=f"{t('prod_titre')} : {cible.designation}",
                 bg=theme.COULEURS["carte"], font=theme.POLICES["normal"]).pack(
            anchor="w", padx=theme.PAD_L)
        tk.Label(fenetre, text=t("prod_fusion_description"),
                 bg=theme.COULEURS["carte"], fg=theme.COULEURS["texte_secondaire"],
                 font=theme.POLICES["petit"], wraplength=380, justify="left").pack(
            anchor="w", padx=theme.PAD_L, pady=(4, theme.PAD))
        tk.Label(fenetre, text=t("prod_fusion_choisir"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).pack(
            anchor="w", padx=theme.PAD_L)

        # Libellé court pour la recherche, ex. "BIDON 5L"
        autres = {p.libelle_recherche: p for p in self._produits if p.id != cible.id}
        var_source = tk.StringVar()
        champ_source = AutocompleteEntry(fenetre, largeur=34, textvariable=var_source)
        champ_source.definir_valeurs(list(autres))
        champ_source.pack(fill="x", padx=theme.PAD_L, pady=(2, theme.PAD))

        def confirmer() -> None:
            source = autres.get(var_source.get())
            if source is None:
                messagebox.showwarning(t("attention"), t("prod_fusion_choisir_source"))
                return
            message = t("prod_fusion_confirmation").format(
                source.designation, cible.designation)
            if not messagebox.askyesno(t("confirmer"), message):
                return
            self._repo.fusionner(cible.id, source.id)
            fenetre.destroy()
            afficher_toast(self, t("prod_fusion_reussie"))
            self._nouveau()
            self.rafraichir()

        boutons = ttk.Frame(fenetre)
        boutons.pack(fill="x", padx=theme.PAD_L, pady=(0, theme.PAD_L))
        ttk.Button(boutons, text=t("annuler"),
                   command=fenetre.destroy).pack(side="right")
        ttk.Button(boutons, text=t("prod_fusionner"), style="Accent.TButton",
                   command=confirmer).pack(side="right", padx=(0, 8))
