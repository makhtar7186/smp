"""Carte KPI : titre, valeur, variation vs période précédente."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.i18n.translations import t
from app.ui import theme


class KPICard(ttk.Frame):
    """Carte blanche avec ombre simulée (bordure basse), valeur et variation."""

    def __init__(self, parent: tk.Misc, titre: str) -> None:
        super().__init__(parent)
        # Ombre simulée : frame sombre décalée sous la carte
        ombre = tk.Frame(self, bg=theme.COULEURS["bordure"])
        ombre.pack(fill="both", expand=True, padx=(0, 0), pady=(0, 0))
        self._carte = tk.Frame(ombre, bg=theme.COULEURS["carte"],
                               highlightthickness=1,
                               highlightbackground=theme.COULEURS["bordure"])
        self._carte.pack(fill="both", expand=True, padx=(0, 2), pady=(0, 2))

        self._titre = ttk.Label(self._carte, text=titre, style="KpiTitre.TLabel")
        self._titre.pack(anchor="w", padx=theme.PAD, pady=(theme.PAD, 2))
        self._valeur = ttk.Label(self._carte, text="—", style="KpiValeur.TLabel")
        self._valeur.pack(anchor="w", padx=theme.PAD)
        self._variation = ttk.Label(self._carte, text="", style="Secondaire.TLabel")
        self._variation.pack(anchor="w", padx=theme.PAD, pady=(2, theme.PAD))

    def definir(self, valeur: str, variation_pct: float | None = None) -> None:
        """Met à jour la valeur affichée et la variation en %."""
        self._valeur.configure(text=valeur)
        if variation_pct is None:
            self._variation.configure(text=t("dash_vs_precedent") + " : —",
                                      style="Secondaire.TLabel")
        else:
            fleche = "▲" if variation_pct >= 0 else "▼"
            style = "KpiHausse.TLabel" if variation_pct >= 0 else "KpiBaisse.TLabel"
            self._variation.configure(
                text=f"{fleche} {variation_pct:+.1f} % {t('dash_vs_precedent')}",
                style=style,
            )
