"""Champ de saisie de date avec calendrier déroulant (tkcalendar), en
remplacement de la saisie manuelle JJ/MM/AAAA partout dans l'application.

`ChampDate` est un `DateEntry` pré-configuré (format d'affichage JJ/MM/AAAA,
calendrier en français) qui reste un remplacement quasi direct d'un
`ttk.Entry` existant : `textvariable` est accepté tel quel (le code appelant
continue de lire/écrire `self.var_xxx.get()`/`.set()` sans changement), et
`.get()`/`.delete(0, "end")`/`.insert(0, texte)` fonctionnent identiquement
(DateEntry hérite de ttk.Entry). Un champ vidé (`.delete(0, "end")`) reste
vide tant que l'utilisateur n'a pas choisi une date dans le calendrier ou
resaisi manuellement — utilisé pour les filtres de période optionnels
(Du/Au, où un champ vide signifie « aucune borne »)."""
from __future__ import annotations

import tkinter as tk

from tkcalendar import DateEntry

from app.ui import theme


class ChampDate(DateEntry):
    """DateEntry stylé selon le thème de l'application, format JJ/MM/AAAA,
    calendrier en français."""

    def __init__(self, parent: tk.Misc, largeur: int = 12, **kwargs) -> None:
        kwargs.setdefault("date_pattern", "dd/mm/yyyy")
        kwargs.setdefault("locale", "fr_FR")
        kwargs.setdefault("width", largeur)
        kwargs.setdefault("background", theme.COULEURS["accent"])
        kwargs.setdefault("foreground", "white")
        kwargs.setdefault("bordercolor", theme.COULEURS["bordure"])
        kwargs.setdefault("headersbackground", theme.COULEURS["accent_clair"])
        kwargs.setdefault("headersforeground", theme.COULEURS["texte"])
        kwargs.setdefault("selectbackground", theme.COULEURS["accent"])
        kwargs.setdefault("normalbackground", theme.COULEURS["carte"])
        kwargs.setdefault("weekendbackground", theme.COULEURS["fond"])
        kwargs.setdefault("othermonthbackground", theme.COULEURS["fond"])
        super().__init__(parent, **kwargs)

    def vider(self) -> None:
        """Vide le champ (aucune date sélectionnée) — pour un filtre de
        période optionnel réinitialisé."""
        self.delete(0, "end")
