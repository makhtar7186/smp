"""Tableau ttk.Treeview stylé avec défilement et lignes alternées."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Sequence

from app.ui import theme


class DataTable(ttk.Frame):
    """Treeview en lecture avec en-têtes, scrollbar et lignes alternées."""

    def __init__(
        self,
        parent: tk.Misc,
        colonnes: Sequence[tuple[str, str, int, str]],
        hauteur: int = 12,
    ) -> None:
        """`colonnes` : liste de (id, libellé, largeur px, ancre 'w'/'center'/'e')."""
        super().__init__(parent)
        ids = [c[0] for c in colonnes]
        self.tree = ttk.Treeview(self, columns=ids, show="headings", height=hauteur,
                                 selectmode="browse")
        for cid, libelle, largeur, ancre in colonnes:
            self.tree.heading(cid, text=libelle)
            self.tree.column(cid, width=largeur, anchor=ancre, stretch=True)
        barre = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=barre.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        barre.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        theme.configurer_lignes_alternees(self.tree)

    def vider(self) -> None:
        """Supprime toutes les lignes."""
        for item in self.tree.get_children():
            self.tree.delete(item)

    def ajouter(self, valeurs: Sequence, iid: str | None = None) -> str:
        """Ajoute une ligne avec alternance de couleur ; retourne l'iid."""
        indice = len(self.tree.get_children())
        return self.tree.insert("", "end", iid=iid, values=list(valeurs),
                                tags=(theme.tag_alternance(indice),))

    def selection_iid(self) -> str | None:
        """iid de la ligne sélectionnée, ou None."""
        selection = self.tree.selection()
        return selection[0] if selection else None
