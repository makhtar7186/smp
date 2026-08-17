"""Vue Analyse produits : suivi d'un produit précis et visuels de production."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from app.i18n import translations
from app.i18n.translations import t
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.champ_date import ChampDate
from app.ui.components.kpi_card import KPICard
from app.utils.formatting import (
    format_date,
    format_fcfa,
    parse_date_affichage,
)


def _style_axes(axes) -> None:
    axes.set_facecolor(theme.COULEURS["carte"])
    for cote in ("top", "right"):
        axes.spines[cote].set_visible(False)
    for cote in ("left", "bottom"):
        axes.spines[cote].set_color(theme.COULEURS["bordure"])
    axes.tick_params(colors=theme.COULEURS["texte_secondaire"], labelsize=7.5)


class AnalyseView(ttk.Frame):
    """Suivi précis d'un produit (quantités sur une période) + visuels
    d'aide à la décision : épaisseurs, dimensions, habitudes, top clients."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._construire()

    # Construction (contenu défilant : la page est plus haute que l'écran) ----
    def _construire(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        canvas = tk.Canvas(self, bg=theme.COULEURS["fond"], highlightthickness=0)
        barre = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=barre.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        barre.grid(row=0, column=1, sticky="ns")
        self._contenu = ttk.Frame(canvas)
        fenetre = canvas.create_window((0, 0), window=self._contenu, anchor="nw")
        self._contenu.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(fenetre, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-e.delta // 120, "units"))

        contenu = self._contenu
        contenu.columnconfigure(0, weight=1)
        ttk.Label(contenu, text=t("ana_titre"), style="Titre.TLabel").grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L,
            pady=(theme.PAD_L, theme.PAD))

        # Filtres : produit + période + granularité
        aujourdhui = date.today()
        filtres = tk.Frame(contenu, bg=theme.COULEURS["carte"],
                           highlightthickness=1,
                           highlightbackground=theme.COULEURS["bordure"])
        filtres.grid(row=1, column=0, sticky="ew", padx=theme.PAD_L)
        self.var_produit = tk.StringVar()
        self.var_du = tk.StringVar(value=format_date(date(aujourdhui.year, 1, 1)))
        self.var_au = tk.StringVar(value=format_date(aujourdhui))
        tk.Label(filtres, text=t("fact_produit"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4), pady=theme.PAD)
        self._champ_produit = AutocompleteEntry(
            filtres, largeur=34, textvariable=self.var_produit,
            on_select=lambda _v: self.rafraichir())
        self._champ_produit.pack(side="left")
        tk.Label(filtres, text=t("du"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        # DateEntry écrase la variable liée avec la date du jour à la
        # construction — la valeur par défaut voulue (1er janvier) est donc
        # réappliquée juste après, plutôt que passée à la création de var_du.
        ChampDate(filtres, largeur=11, textvariable=self.var_du).pack(side="left")
        self.var_du.set(format_date(date(aujourdhui.year, 1, 1)))
        tk.Label(filtres, text=t("au"), bg=theme.COULEURS["carte"]).pack(
            side="left", padx=(theme.PAD, 4))
        ChampDate(filtres, largeur=11, textvariable=self.var_au).pack(side="left")
        self.var_au.set(format_date(aujourdhui))
        self.var_granularite = tk.StringVar(value=t("dash_par_mois"))
        self._granularites = {t("dash_par_jour"): "jour",
                              t("dash_par_semaine"): "semaine",
                              t("dash_par_mois"): "mois"}
        combo = ttk.Combobox(filtres, textvariable=self.var_granularite,
                             state="readonly", width=9,
                             values=list(self._granularites))
        combo.pack(side="left", padx=(theme.PAD, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: self.rafraichir())
        ttk.Button(filtres, text=t("filtrer"), style="Accent.TButton",
                   command=self.rafraichir).pack(side="left", padx=theme.PAD)

        # KPI du produit choisi
        rangee_kpi = ttk.Frame(contenu)
        rangee_kpi.grid(row=2, column=0, sticky="ew", padx=theme.PAD_L,
                        pady=theme.PAD)
        self._cartes: dict[str, KPICard] = {}
        for indice, (cle, titre) in enumerate([
            ("quantite", t("ana_quantite_vendue")),
            ("ca", t("ana_ca")),
            ("factures", t("ana_nb_factures")),
            ("prix", t("ana_prix_moyen")),
        ]):
            rangee_kpi.columnconfigure(indice, weight=1, uniform="anakpi")
            carte = KPICard(rangee_kpi, titre)
            carte.grid(row=0, column=indice, sticky="nsew",
                       padx=(0 if indice == 0 else theme.PAD_S, 0))
            self._cartes[cle] = carte

        # Graphiques
        self._cadre_evolution = self._carte_graphique(contenu, 3,
                                                      t("ana_evolution_produit"))
        rangee1 = ttk.Frame(contenu)
        rangee1.grid(row=4, column=0, sticky="ew", padx=theme.PAD_L,
                     pady=(theme.PAD_S, 0))
        rangee1.columnconfigure(0, weight=1)
        rangee1.columnconfigure(1, weight=1)
        self._cadre_litrage = self._carte_graphique(rangee1, None,
                                                     t("ana_par_litrage"),
                                                     colonne=0)
        self._cadre_dimension = self._carte_graphique(rangee1, None,
                                                      t("ana_par_dimension"),
                                                      colonne=1)
        rangee2 = ttk.Frame(contenu)
        rangee2.grid(row=5, column=0, sticky="ew", padx=theme.PAD_L,
                     pady=(theme.PAD_S, theme.PAD_L))
        rangee2.columnconfigure(0, weight=1)
        rangee2.columnconfigure(1, weight=1)
        self._cadre_jours = self._carte_graphique(rangee2, None,
                                                  t("ana_jour_semaine"),
                                                  colonne=0)
        self._cadre_top_produits = self._carte_graphique(rangee2, None,
                                                         t("ana_top_produits"),
                                                         colonne=1)

    def _carte_graphique(self, parent, rang: int | None, titre: str,
                         colonne: int = 0) -> tk.Frame:
        cadre = tk.Frame(parent, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        if rang is not None:
            cadre.grid(row=rang, column=0, sticky="ew", padx=theme.PAD_L,
                       pady=(theme.PAD_S, 0))
        else:
            cadre.grid(row=0, column=colonne, sticky="nsew",
                       padx=(0 if colonne == 0 else theme.PAD_S, 0))
        tk.Label(cadre, text=titre, bg=theme.COULEURS["carte"],
                 font=theme.POLICES["sous_titre"],
                 fg=theme.COULEURS["texte"]).pack(anchor="w", padx=theme.PAD,
                                                  pady=(theme.PAD_S, 0))
        return cadre

    # Données -----------------------------------------------------------------
    def _periode(self) -> tuple[date, date] | None:
        try:
            return (parse_date_affichage(self.var_du.get()),
                    parse_date_affichage(self.var_au.get()))
        except ValueError:
            messagebox.showerror(t("erreur"), t("date_invalide"))
            return None

    def rafraichir(self) -> None:
        """Recharge KPI et graphiques selon produit + période choisis."""
        periode = self._periode()
        if periode is None:
            return
        debut, fin = periode
        stats = self.app.stats
        self._champ_produit.definir_valeurs(stats.liste_produits_vendus())

        libelle = self.var_produit.get().strip()
        if libelle:
            resume = stats.resume_produit(libelle, debut, fin)
            self._cartes["quantite"].definir(str(resume["quantite"]))
            self._cartes["ca"].definir(format_fcfa(resume["ca"]))
            self._cartes["factures"].definir(str(resume["nb_factures"]))
            self._cartes["prix"].definir(format_fcfa(resume["prix_moyen"]))
            granularite = self._granularites.get(self.var_granularite.get(), "mois")
            self._barres(self._cadre_evolution,
                         stats.serie_quantite_produit(libelle, debut, fin,
                                                      granularite),
                         largeur=9.6, hauteur=2.0)
        else:
            for carte in self._cartes.values():
                carte.definir("—")
            self._message_vide(self._cadre_evolution, t("ana_choisir_produit"))

        self._barres(self._cadre_litrage,
                     stats.quantites_par_litrage(debut, fin),
                     largeur=4.7, hauteur=2.0)
        self._barres(self._cadre_dimension,
                     stats.quantites_par_dimension(debut, fin),
                     largeur=4.7, hauteur=2.0)
        # Jours : réordonnés lundi → dimanche, libellés localisés
        jours = translations.jours_semaine()
        ca_jours = dict(stats.ca_par_jour_semaine(debut, fin))
        serie_jours = [(jours[i], ca_jours.get(i, 0))
                       for i in (1, 2, 3, 4, 5, 6, 0)]
        self._barres(self._cadre_jours,
                     serie_jours if any(v for _, v in serie_jours) else [],
                     largeur=4.7, hauteur=2.0)
        self._barres_horizontales(self._cadre_top_produits,
                                  stats.top_produits(debut, fin,
                                                     par="quantite", limite=10),
                                  largeur=4.7, hauteur=2.0)

    # Rendu graphique ---------------------------------------------------------
    def _poser(self, cadre: tk.Frame, figure: Figure) -> None:
        """Insère la figure dans un cadre préalablement nettoyé (_nettoyer)."""
        canvas = FigureCanvasTkAgg(figure, master=cadre)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True,
                                    padx=theme.PAD_S, pady=theme.PAD_S)

    def _nettoyer(self, cadre: tk.Frame) -> None:
        for enfant in cadre.winfo_children():
            est_titre = (isinstance(enfant, tk.Label)
                         and enfant.cget("fg") == theme.COULEURS["texte"])
            if not est_titre:
                enfant.destroy()

    def _message_vide(self, cadre: tk.Frame, texte: str | None = None) -> None:
        self._nettoyer(cadre)
        tk.Label(cadre, text=texte or t("dash_aucune_vente"),
                 bg=theme.COULEURS["carte"],
                 fg=theme.COULEURS["texte_secondaire"],
                 font=theme.POLICES["normal"]).pack(pady=theme.PAD_L)

    def _figure(self, largeur: float, hauteur: float):
        figure = Figure(figsize=(largeur, hauteur), dpi=90,
                        facecolor=theme.COULEURS["carte"])
        axes = figure.add_subplot(111)
        _style_axes(axes)
        return figure, axes

    def _barres(self, cadre: tk.Frame, donnees: list[tuple[str, int]],
                largeur: float, hauteur: float) -> None:
        self._nettoyer(cadre)
        if not donnees:
            self._message_vide(cadre)
            return
        figure, axes = self._figure(largeur, hauteur)
        libelles = [str(lib)[:16] for lib, _ in donnees]
        valeurs = [val for _, val in donnees]
        axes.bar(libelles, valeurs, color=theme.PALETTE_GRAPHIQUES[0], width=0.6)
        if len(libelles) > 14:
            axes.tick_params(axis="x", rotation=45)
        figure.tight_layout(pad=1.1)
        self._poser(cadre, figure)

    def _barres_horizontales(self, cadre: tk.Frame,
                             donnees: list[tuple[str, int]],
                             largeur: float, hauteur: float) -> None:
        self._nettoyer(cadre)
        if not donnees:
            self._message_vide(cadre)
            return
        figure, axes = self._figure(largeur, hauteur)
        libelles = [lib[:20] for lib, _ in reversed(donnees)]
        valeurs = [val for _, val in reversed(donnees)]
        axes.barh(libelles, valeurs, color=theme.PALETTE_GRAPHIQUES[1], height=0.6)
        figure.tight_layout(pad=1.1)
        self._poser(cadre, figure)
