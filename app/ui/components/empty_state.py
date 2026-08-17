"""État vide élégant (« Aucune vente sur cette période »)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.ui import theme


class EmptyState(ttk.Frame):
    """Message centré affiché quand une liste ou un graphique n'a pas de données."""

    def __init__(self, parent: tk.Misc, message: str, icone: str = "🗒") -> None:
        super().__init__(parent, style="Carte.TFrame")
        conteneur = ttk.Frame(self, style="Carte.TFrame")
        conteneur.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(conteneur, text=icone, font=("Segoe UI Emoji", 28),
                 bg=theme.COULEURS["carte"],
                 fg=theme.COULEURS["texte_secondaire"]).pack()
        ttk.Label(conteneur, text=message, style="Secondaire.TLabel").pack(pady=4)
