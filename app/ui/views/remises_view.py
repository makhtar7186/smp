"""Vue Remises annuelles : CA par client et calcul de la remise de fin d'année."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app.i18n.translations import t
from app.ui import theme
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.formatting import format_fcfa
from app.utils.validation import ErreurValidation


class RemisesView(ttk.Frame):
    """Tableau des CA annuels par client, saisie d'un taux, remise historisée."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._lignes = []
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text=t("rem_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L,
            pady=(theme.PAD_L, theme.PAD))

        barre = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        barre.grid(row=1, column=0, sticky="ew", padx=theme.PAD_L)
        tk.Label(barre, text=t("rem_annee"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        annee_courante = date.today().year
        self.var_annee = tk.StringVar(value=str(annee_courante))
        ttk.Combobox(barre, textvariable=self.var_annee, state="readonly", width=8,
                     values=[str(a) for a in range(annee_courante, annee_courante - 8,
                                                   -1)]).pack(side="left")
        ttk.Button(barre, text=t("filtrer"), style="Accent.TButton",
                   command=self.rafraichir).pack(side="left", padx=theme.PAD)

        tk.Label(barre, text=t("rem_taux"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD_L, 4))
        self.var_taux = tk.StringVar()
        ttk.Entry(barre, textvariable=self.var_taux, width=8).pack(side="left")
        tk.Label(barre, text=t("rem_note"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        self.var_note = tk.StringVar()
        ttk.Entry(barre, textvariable=self.var_note, width=22).pack(side="left")
        ttk.Button(barre, text=t("rem_calculer"), style="Accent.TButton",
                   command=self._appliquer_taux).pack(side="left", padx=theme.PAD)

        self._table = DataTable(self, [
            ("client", t("fact_client"), 200, "w"),
            ("adresse", t("cli_adresse"), 130, "w"),
            ("ca", t("rem_ca_annuel"), 150, "e"),
            ("taux", t("rem_taux"), 90, "center"),
            ("montant", t("rem_montant"), 150, "e"),
            ("note", t("rem_note"), 200, "w"),
        ])
        self._table.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_L,
                         pady=theme.PAD)

    def rafraichir(self) -> None:
        """Recharge le tableau CA + remises de l'année choisie."""
        annee = int(self.var_annee.get())
        self._lignes = self.app.remises.tableau_annee(annee)
        self._table.vider()
        for ligne in self._lignes:
            self._table.ajouter([
                ligne.client_nom, ligne.client_adresse,
                format_fcfa(ligne.ca_annuel, False),
                f"{ligne.taux:g} %" if ligne.taux else "",
                format_fcfa(ligne.montant, False) if ligne.montant else "",
                ligne.note,
            ])

    def _appliquer_taux(self) -> None:
        """Applique le taux saisi au client sélectionné et enregistre la remise."""
        iid = self._table.selection_iid()
        if iid is None or not self._lignes:
            return
        ligne = self._lignes[self._table.tree.index(iid)]
        try:
            taux = float(self.var_taux.get().replace(",", "."))
            if taux < 0 or taux > 100:
                raise ValueError
        except ValueError:
            from tkinter import messagebox
            messagebox.showerror(t("erreur"), t("nombre_invalide"))
            return
        if ligne.ca_annuel <= 0:
            afficher_toast(self, t("rem_aucun_ca"), succes=False)
            return
        self.app.remises.enregistrer(
            client_id=ligne.client_id, annee=int(self.var_annee.get()),
            ca_annuel=ligne.ca_annuel, taux=taux, note=self.var_note.get().strip(),
        )
        afficher_toast(self, t("rem_enregistree"))
        self.rafraichir()
