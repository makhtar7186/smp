"""Vue Paramètres machine : bascule entre le mode « principale » (comportement
historique de `SMP.exe`, base locale) et « facturation à distance »
(cache local + synchronisation, voir `app.ui.app_facturation_etendue`).
Nécessite un redémarrage manuel de l'application — jamais de relance
automatique de l'exécutable. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app import config
from app.i18n.translations import t
from app.ui import theme


class ParametresMachineView(ttk.Frame):
    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._construire()

    def _construire(self) -> None:
        ttk.Label(self, text=t("param_titre"), style="Titre.TLabel").pack(
            anchor="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))
        ttk.Label(self, text=t("param_description"), style="Secondaire.TLabel",
                 wraplength=760, justify="left").pack(
            anchor="w", padx=theme.PAD_L, pady=(0, theme.PAD_L))

        carte = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        carte.pack(fill="x", padx=theme.PAD_L)

        self.var_mode = tk.StringVar(value=config.lire_mode_machine())
        ttk.Radiobutton(carte, text=t("param_mode_principale"), value="principale",
                       variable=self.var_mode).pack(anchor="w", padx=theme.PAD,
                                                    pady=(theme.PAD, theme.PAD_S))
        ttk.Radiobutton(carte, text=t("param_mode_facturation_distante"),
                       value="facturation_distante", variable=self.var_mode).pack(
            anchor="w", padx=theme.PAD, pady=(0, theme.PAD))

        ttk.Button(self, text=t("enregistrer"), style="Accent.TButton",
                  command=self._enregistrer).pack(anchor="w", padx=theme.PAD_L,
                                                  pady=theme.PAD)

    def rafraichir(self) -> None:
        self.var_mode.set(config.lire_mode_machine())

    def _enregistrer(self) -> None:
        config.definir_mode_machine(self.var_mode.get())
        messagebox.showinfo(t("succes"), t("param_redemarrage_requis"))
