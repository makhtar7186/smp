"""Vue Journal des fusions (boss) : historique en lecture seule des fusions
de clients rejouées depuis une machine de facturation, y compris celles
appliquées malgré un conflit détecté. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from app.i18n.translations import t
from app.repositories.historique_fusion_repository import HistoriqueFusionRepository
from app.ui import theme
from app.ui.components.data_table import DataTable


class JournalFusionsView(ttk.Frame):
    """Lecture seule : aucune écriture, aucun repli sur une autre couche."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._repo = HistoriqueFusionRepository(application.conn)
        self._entrees = []
        self._construire()

    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        ttk.Label(self, text=t("fj_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD))
        ttk.Label(self, text=t("fj_description"), style="Secondaire.TLabel",
                 wraplength=760, justify="left").grid(
            row=0, column=0, sticky="sw", padx=theme.PAD_L, pady=(0, theme.PAD_S))

        self._table = DataTable(self, [
            ("date", t("fj_traite_le"), 150, "center"),
            ("machine", t("fj_machine"), 130, "w"),
            ("conserve", t("fj_client_conserve"), 200, "w"),
            ("supprime", t("fj_client_supprime"), 200, "w"),
            ("conflit", t("fj_conflit"), 90, "center"),
        ])
        self._table.grid(row=1, column=0, sticky="nsew", padx=theme.PAD_L, pady=theme.PAD)
        self._table.tree.bind("<<TreeviewSelect>>", self._afficher_detail)

        bas = ttk.Frame(self)
        bas.grid(row=2, column=0, sticky="ew", padx=theme.PAD_L, pady=(0, theme.PAD_L))
        bas.columnconfigure(0, weight=1)
        self._detail = tk.Text(bas, height=8, wrap="word", font=theme.POLICES["petit"],
                               bg=theme.COULEURS["carte"], relief="flat")
        self._detail.grid(row=0, column=0, sticky="nsew")
        self._detail.configure(state="disabled")

    def rafraichir(self) -> None:
        self._entrees = self._repo.lister()
        self._table.vider()
        for entree in self._entrees:
            self._table.ajouter([
                entree.traite_le, entree.machine_origine,
                f"{entree.client_a_garder_nom} — {entree.client_a_garder_adresse}",
                f"{entree.client_a_supprimer_nom} — {entree.client_a_supprimer_adresse}",
                t("oui") if entree.conflit_detecte else t("non"),
            ])
        self._vider_detail()

    def _vider_detail(self) -> None:
        self._detail.configure(state="normal")
        self._detail.delete("1.0", "end")
        self._detail.configure(state="disabled")

    def _afficher_detail(self, _evenement) -> None:
        iid = self._table.selection_iid()
        if iid is None:
            self._vider_detail()
            return
        entree = self._entrees[self._table.tree.index(iid)]
        try:
            avant = json.dumps(json.loads(entree.etat_avant_json), ensure_ascii=False, indent=2)
            apres = json.dumps(json.loads(entree.etat_apres_json), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            avant, apres = entree.etat_avant_json, entree.etat_apres_json
        texte = f"{t('fj_etat_avant')}\n{avant}\n\n{t('fj_etat_apres')}\n{apres}"
        self._detail.configure(state="normal")
        self._detail.delete("1.0", "end")
        self._detail.insert("1.0", texte)
        self._detail.configure(state="disabled")
