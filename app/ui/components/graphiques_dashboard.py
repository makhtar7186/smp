"""Rendu matplotlib partagé des tableaux de bord — fonctions pures prenant
des données déjà récupérées (jamais d'accès à un service ou une connexion),
réutilisées à la fois par `app/ui/views/dashboard_view.py` (données locales,
`StatsService`) et par l'onglet Dashboard du mode client (données distantes,
`ApiClient`, voir CLAUDE.md, section « Machine de facturation »)."""
from __future__ import annotations

import tkinter as tk
from typing import Sequence

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from app.ui import theme


def style_axes(axes) -> None:
    """Applique le style du thème à un axe matplotlib."""
    axes.set_facecolor(theme.COULEURS["carte"])
    for cote in ("top", "right"):
        axes.spines[cote].set_visible(False)
    for cote in ("left", "bottom"):
        axes.spines[cote].set_color(theme.COULEURS["bordure"])
    axes.tick_params(colors=theme.COULEURS["texte_secondaire"], labelsize=8)


def cadre_graphique(parent: tk.Widget, colonne: int, titre: str) -> tk.Frame:
    """Carte blanche titrée destinée à recevoir un canvas matplotlib — le
    titre (1er enfant) est préservé par `message_vide`/le tracé suivant."""
    cadre = tk.Frame(parent, bg=theme.COULEURS["carte"], highlightthickness=1,
                     highlightbackground=theme.COULEURS["bordure"])
    cadre.grid(row=0, column=colonne, sticky="nsew",
               padx=(0 if colonne == 0 else theme.PAD_S, 0))
    tk.Label(cadre, text=titre, bg=theme.COULEURS["carte"],
             font=theme.POLICES["sous_titre"],
             fg=theme.COULEURS["texte"]).pack(anchor="w", padx=theme.PAD,
                                              pady=(theme.PAD_S, 0))
    return cadre


def _vider_contenu(cadre: tk.Frame) -> None:
    """Retire tout le contenu du cadre sauf le titre (1er enfant, posé par
    `cadre_graphique`)."""
    for enfant in list(cadre.winfo_children())[1:]:
        enfant.destroy()


def _figure(largeur: float, hauteur: float) -> tuple[Figure, object]:
    figure = Figure(figsize=(largeur, hauteur), dpi=90, facecolor=theme.COULEURS["carte"])
    axes = figure.add_subplot(111)
    style_axes(axes)
    return figure, axes


def _poser_canvas(cadre: tk.Frame, figure: Figure, canvases: list) -> None:
    """`canvases` : liste tenue par l'appelant pour garder une référence au
    `FigureCanvasTkAgg` (sinon garbage-collecté et le canvas disparaît)."""
    _vider_contenu(cadre)
    canvas = FigureCanvasTkAgg(figure, master=cadre)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True,
                                padx=theme.PAD_S, pady=theme.PAD_S)
    canvases.append(canvas)


def message_vide(cadre: tk.Frame, texte: str) -> None:
    _vider_contenu(cadre)
    tk.Label(cadre, text=texte, bg=theme.COULEURS["carte"],
             fg=theme.COULEURS["texte_secondaire"],
             font=theme.POLICES["normal"]).pack(expand=True)


def dessiner_top_produits(cadre: tk.Frame, donnees: Sequence[tuple[str, int]],
                          texte_vide: str, canvases: list) -> None:
    if not donnees:
        message_vide(cadre, texte_vide)
        return
    figure, axes = _figure(5.4, 2.6)
    libelles = [lib[:28] for lib, _ in reversed(donnees)]
    valeurs = [val for _, val in reversed(donnees)]
    axes.barh(libelles, valeurs, color=theme.PALETTE_GRAPHIQUES[0], height=0.6)
    axes.tick_params(labelsize=7.5)
    figure.tight_layout(pad=1.2)
    _poser_canvas(cadre, figure, canvases)


def dessiner_repartition_gamme(cadre: tk.Frame, donnees: Sequence[tuple[str, int]],
                               texte_vide: str, canvases: list) -> None:
    if not donnees:
        message_vide(cadre, texte_vide)
        return
    figure, axes = _figure(3.6, 2.6)
    libelles = [lib[:20] for lib, _ in donnees]
    valeurs = [val for _, val in donnees]
    axes.pie(valeurs, labels=libelles, colors=theme.PALETTE_GRAPHIQUES,
             wedgeprops={"width": 0.42, "edgecolor": theme.COULEURS["carte"]},
             textprops={"fontsize": 7.5, "color": theme.COULEURS["texte"]},
             autopct="%1.0f%%", pctdistance=0.78)
    figure.tight_layout(pad=1.0)
    _poser_canvas(cadre, figure, canvases)


def dessiner_evolution_ca(cadre: tk.Frame, serie: Sequence[tuple[str, int]],
                          texte_vide: str, canvases: list) -> None:
    if not serie:
        message_vide(cadre, texte_vide)
        return
    figure, axes = _figure(9.6, 2.2)
    periodes = [p for p, _ in serie]
    valeurs = [v for _, v in serie]
    axes.plot(periodes, valeurs, color=theme.PALETTE_GRAPHIQUES[0],
              linewidth=2, marker="o", markersize=3.5)
    axes.fill_between(range(len(valeurs)), valeurs, alpha=0.08,
                      color=theme.PALETTE_GRAPHIQUES[0])
    if len(periodes) > 12:
        pas = max(1, len(periodes) // 12)
        axes.set_xticks(range(0, len(periodes), pas))
    axes.tick_params(axis="x", rotation=30, labelsize=7)
    figure.tight_layout(pad=1.2)
    _poser_canvas(cadre, figure, canvases)
