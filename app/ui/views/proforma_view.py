"""Vue Proforma : liste des brouillons de facture — modifier, valider, supprimer."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.ui import theme
from app.ui.components.champ_date import ChampDate
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.fichiers import ouvrir_fichier
from app.utils.formatting import format_date, format_fcfa, parse_date_affichage
from app.utils.validation import ErreurValidation, valider_entier_positif


class FenetreValidation(tk.Toplevel):
    """Boîte de dialogue : numéro et date de la facture à créer à partir du
    brouillon (c'est ce moment précis qui lui attribue un numéro)."""

    def __init__(self, parent: tk.Misc, numero_suggere: int) -> None:
        super().__init__(parent)
        self.title(t("proforma_valider_titre"))
        self.geometry("360x200")
        self.resizable(False, False)
        self.configure(bg=theme.COULEURS["fond"])
        self.resultat: tuple[int, date] | None = None
        self.transient(parent)
        self.grab_set()

        cadre = ttk.Frame(self, padding=theme.PAD_L)
        cadre.pack(fill="both", expand=True)

        ttk.Label(cadre, text=t("proforma_valider_numero"),
                  style="SousTitre.TLabel").pack(anchor="w")
        self._champ_numero = ttk.Entry(cadre)
        self._champ_numero.insert(0, str(numero_suggere))
        self._champ_numero.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("proforma_valider_date"),
                  style="SousTitre.TLabel").pack(anchor="w")
        self._champ_date = ChampDate(cadre)
        self._champ_date.pack(fill="x", pady=(2, 16))

        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x")
        ttk.Button(boutons, text=t("annuler"), command=self.destroy).pack(side="right")
        ttk.Button(boutons, text=t("proforma_valider"), style="Accent.TButton",
                  command=self._valider).pack(side="right", padx=(0, 8))

    def _valider(self) -> None:
        try:
            numero = valider_entier_positif(self._champ_numero.get(), strict=True)
        except ErreurValidation:
            messagebox.showerror(t("erreur"), t("nombre_invalide"), parent=self)
            return
        try:
            date_facture = parse_date_affichage(self._champ_date.get())
        except ValueError:
            messagebox.showerror(t("erreur"), t("date_invalide"), parent=self)
            return
        self.resultat = (numero, date_facture)
        self.destroy()


class ProformaView(ttk.Frame):
    """Liste des brouillons de facture (proforma) : modifier, valider, supprimer."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._proformas: list = []
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text=t("proforma_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD))

        self._table = DataTable(self, [
            ("date", t("proforma_colonne_date"), 100, "center"),
            ("client", t("proforma_colonne_client"), 220, "w"),
            ("destination", t("proforma_colonne_destination"), 160, "w"),
            ("lignes", t("proforma_colonne_lignes"), 70, "center"),
            ("total", t("proforma_colonne_total"), 130, "e"),
        ])
        self._table.grid(row=1, column=0, sticky="nsew", padx=theme.PAD_L, pady=theme.PAD)

        actions = ttk.Frame(self)
        actions.grid(row=2, column=0, sticky="ew", padx=theme.PAD_L,
                     pady=(0, theme.PAD_L))
        ttk.Button(actions, text="🗑 " + t("supprimer"), style="Danger.TButton",
                   command=self._supprimer).pack(side="right")
        ttk.Button(actions, text="✎ " + t("proforma_modifier"),
                   command=self._modifier).pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="✔ " + t("proforma_valider"), style="Accent.TButton",
                   command=self._valider).pack(side="right", padx=(0, 8))
        ttk.Button(actions, text="🖶 " + t("proforma_imprimer"),
                   command=self._imprimer).pack(side="right", padx=(0, 8))

    def rafraichir(self) -> None:
        self._proformas = self.app.proformas.lister()
        self._table.vider()
        for proforma in self._proformas:
            self._table.ajouter([
                format_date(proforma.date_creation), proforma.client_nom,
                proforma.destination, proforma.nb_lignes,
                format_fcfa(proforma.total_liste, False),
            ])

    def _proforma_selectionnee(self):
        iid = self._table.selection_iid()
        if iid is None:
            messagebox.showinfo(t("attention"), t("proforma_aucune_selection"))
            return None
        return self._proformas[self._table.tree.index(iid)]

    def _modifier(self) -> None:
        """Bascule sur Facturation avec ce brouillon chargé pour correction."""
        proforma = self._proforma_selectionnee()
        if proforma is None:
            return
        complet = self.app.proformas.obtenir(proforma.id)
        self.app.afficher_vue("facturation")
        self.app.obtenir_vue("facturation").charger_pour_edition_proforma(complet)

    def _imprimer(self) -> None:
        """Génère et ouvre le PDF « FACTURE PROFORMA » (sans numéro) du
        brouillon sélectionné."""
        proforma = self._proforma_selectionnee()
        if proforma is None:
            return
        complet = self.app.proformas.obtenir(proforma.id)
        chemin = self.app.pdf.generer_proforma(complet)
        afficher_toast(self, t("fact_pdf_genere") + chemin.name)
        ouvrir_fichier(chemin)

    def _valider(self) -> None:
        proforma = self._proforma_selectionnee()
        if proforma is None:
            return
        try:
            numero_suggere = self.app.facturation.prochain_numero()
        except ErreurValidation as erreur:
            # Machine de facturation (offline-first) : pool de numéros
            # réservés épuisé ou jamais alimenté — la validation reste
            # possible en saisissant un numéro manuellement, mais celui-ci
            # devra appartenir au pool réservé (voir CLAUDE.md).
            messagebox.showwarning(t("attention"), t(erreur.cle_message))
            numero_suggere = 0
        dialogue = FenetreValidation(self, numero_suggere)
        self.wait_window(dialogue)
        if dialogue.resultat is None:
            return
        numero, date_facture = dialogue.resultat
        if self.app.facturation.numero_existe(numero):
            if not messagebox.askyesno(t("attention"), t("fact_numero_existe")):
                return
        try:
            facture = self.app.proformas.valider(proforma.id, numero, date_facture)
        except ErreurValidation as erreur:
            messagebox.showerror(t("erreur"), t(erreur.cle_message))
            return
        afficher_toast(self, t("proforma_validee").format(facture.numero))
        self.rafraichir()

    def _supprimer(self) -> None:
        proforma = self._proforma_selectionnee()
        if proforma is None:
            return
        if not messagebox.askyesno(t("confirmer"), t("proforma_confirmation_suppression")):
            return
        self.app.proformas.supprimer(proforma.id)
        afficher_toast(self, t("proforma_supprime"))
        self.rafraichir()
