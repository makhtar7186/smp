"""Champ de saisie avec suggestions filtrées au fil de la frappe."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from app.ui import theme

_MAX_SUGGESTIONS = 10


class AutocompleteEntry(ttk.Entry):
    """Zone de texte qui propose, sous le champ, les valeurs contenant la saisie.

    - Les valeurs commençant par la saisie sont proposées en premier.
    - Flèches ↑/↓ pour surligner, Entrée ou clic pour choisir, Échap pour fermer.
    - `on_select(valeur)` est appelé quand une suggestion est choisie.
    """

    def __init__(
        self,
        parent: tk.Misc,
        largeur: int = 24,
        textvariable: tk.StringVar | None = None,
        on_select: Callable[[str], None] | None = None,
    ) -> None:
        self.var = textvariable or tk.StringVar()
        super().__init__(parent, textvariable=self.var, width=largeur)
        self._valeurs: list[str] = []
        self._suggestions: list[str] = []
        self._on_select = on_select
        self._popup: tk.Toplevel | None = None
        self._listbox: tk.Listbox | None = None

        self.bind("<KeyRelease>", self._sur_frappe)
        self.bind("<Down>", self._surligner_suivant)
        self.bind("<Up>", self._surligner_precedent)
        self.bind("<Return>", self._valider_surlignee)
        self.bind("<Escape>", lambda _e: self._fermer())
        self.bind("<FocusOut>", lambda _e: self.after(180, self._fermer))

    # API ---------------------------------------------------------------------
    def definir_valeurs(self, valeurs: list[str]) -> None:
        """Remplace la liste des valeurs proposables."""
        self._valeurs = list(valeurs)

    def get(self) -> str:  # type: ignore[override]
        return self.var.get()

    def set(self, valeur: str) -> None:
        self.var.set(valeur)

    # Suggestions -------------------------------------------------------------
    def _filtrer(self) -> list[str]:
        saisie = self.var.get().strip().upper()
        if not saisie:
            return self._valeurs[:_MAX_SUGGESTIONS]
        debut = [v for v in self._valeurs if v.upper().startswith(saisie)]
        contient = [v for v in self._valeurs
                    if saisie in v.upper() and not v.upper().startswith(saisie)]
        return (debut + contient)[:_MAX_SUGGESTIONS]

    def _sur_frappe(self, evenement: tk.Event) -> None:
        if evenement.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        self._suggestions = self._filtrer()
        if self._suggestions:
            self._ouvrir()
        else:
            self._fermer()

    def _ouvrir(self) -> None:
        if self._popup is None:
            self._popup = tk.Toplevel(self)
            self._popup.overrideredirect(True)
            self._popup.attributes("-topmost", True)
            self._listbox = tk.Listbox(
                self._popup, font=theme.POLICES["normal"], relief="flat",
                bg="white", fg=theme.COULEURS["texte"],
                selectbackground=theme.COULEURS["accent"],
                selectforeground="white", activestyle="none",
                highlightthickness=1,
                highlightbackground=theme.COULEURS["bordure"],
            )
            self._listbox.pack(fill="both", expand=True)
            self._listbox.bind("<ButtonPress-1>", self._sur_clic)
        self._listbox.delete(0, "end")
        for valeur in self._suggestions:
            self._listbox.insert("end", valeur)
        hauteur = min(len(self._suggestions), _MAX_SUGGESTIONS)
        self._listbox.configure(height=hauteur)
        largeur = max(self.winfo_width(), 220)
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 1
        self._popup.geometry(f"{largeur}x{hauteur * 24}+{x}+{y}")
        self._popup.deiconify()

    def _fermer(self) -> None:
        if self._popup is not None:
            self._popup.destroy()
            self._popup = None
            self._listbox = None

    # Sélection ---------------------------------------------------------------
    def _choisir(self, valeur: str) -> None:
        self.var.set(valeur)
        self.icursor("end")
        self._fermer()
        if self._on_select:
            self._on_select(valeur)

    def _sur_clic(self, evenement: tk.Event) -> str:
        indice = self._listbox.nearest(evenement.y)
        if 0 <= indice < len(self._suggestions):
            self._choisir(self._suggestions[indice])
        return "break"

    def _indice_surligne(self) -> int:
        if self._listbox is None:
            return -1
        selection = self._listbox.curselection()
        return selection[0] if selection else -1

    def _surligner(self, indice: int) -> None:
        if self._listbox is None:
            return
        self._listbox.selection_clear(0, "end")
        self._listbox.selection_set(indice)
        self._listbox.see(indice)

    def _surligner_suivant(self, _evenement) -> str:
        if self._popup is None:
            self._suggestions = self._filtrer()
            if not self._suggestions:
                return "break"
            self._ouvrir()
        indice = min(self._indice_surligne() + 1, len(self._suggestions) - 1)
        self._surligner(indice)
        return "break"

    def _surligner_precedent(self, _evenement) -> str:
        if self._popup is not None and self._suggestions:
            self._surligner(max(self._indice_surligne() - 1, 0))
        return "break"

    def _valider_surlignee(self, _evenement) -> str:
        indice = self._indice_surligne()
        if self._popup is not None and 0 <= indice < len(self._suggestions):
            self._choisir(self._suggestions[indice])
            return "break"
        self._fermer()
        return ""
