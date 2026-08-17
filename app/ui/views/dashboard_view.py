"""Vue Tableau de bord : KPI, top produits, évolution du CA, répartition."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app.i18n.translations import t
from app.ui import theme
from app.ui.components import graphiques_dashboard as graph
from app.ui.components.kpi_card import KPICard
from app.utils.formatting import format_fcfa


class DashboardView(ttk.Frame):
    """Vue d'ensemble analytique (données de l'année en cours)."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._canvases: list = []
        self._construire()

    # Construction ------------------------------------------------------------
    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(3, weight=1)

        entete = ttk.Frame(self)
        entete.grid(row=0, column=0, sticky="ew", padx=theme.PAD_L,
                    pady=(theme.PAD_L, theme.PAD))
        ttk.Label(entete, text=t("dash_titre"), style="Titre.TLabel").pack(side="left")

        # Sélecteurs (granularité évolution + critère top produits)
        self.var_granularite = tk.StringVar(value=t("dash_par_mois"))
        self._granularites = {
            t("dash_par_jour"): "jour",
            t("dash_par_semaine"): "semaine",
            t("dash_par_mois"): "mois",
        }
        combo_gran = ttk.Combobox(entete, textvariable=self.var_granularite,
                                  state="readonly", width=10,
                                  values=list(self._granularites))
        combo_gran.pack(side="right")
        combo_gran.bind("<<ComboboxSelected>>", lambda _e: self.rafraichir())
        self.var_top = tk.StringVar(value=t("dash_top_quantite"))
        combo_top = ttk.Combobox(entete, textvariable=self.var_top,
                                 state="readonly", width=16,
                                 values=[t("dash_top_quantite"), t("dash_top_ca")])
        combo_top.pack(side="right", padx=theme.PAD_S)
        combo_top.bind("<<ComboboxSelected>>", lambda _e: self.rafraichir())

        # Rangée de cartes KPI
        rangee_kpi = ttk.Frame(self)
        rangee_kpi.grid(row=1, column=0, sticky="ew", padx=theme.PAD_L)
        self._cartes: dict[str, KPICard] = {}
        for indice, (cle, titre) in enumerate([
            ("jour", t("dash_ca_jour")),
            ("mois", t("dash_ca_mois")),
            ("annee", t("dash_ca_annee")),
            ("nb", t("dash_nb_ventes")),
            ("panier", t("dash_panier_moyen")),
        ]):
            rangee_kpi.columnconfigure(indice, weight=1, uniform="kpi")
            carte = KPICard(rangee_kpi, titre)
            carte.grid(row=0, column=indice, sticky="nsew",
                       padx=(0 if indice == 0 else theme.PAD_S, 0))
            self._cartes[cle] = carte

        # Rangée graphiques : top produits + répartition
        rangee1 = ttk.Frame(self)
        rangee1.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_L,
                     pady=theme.PAD)
        rangee1.columnconfigure(0, weight=3)
        rangee1.columnconfigure(1, weight=2)
        rangee1.rowconfigure(0, weight=1)
        self._cadre_top = graph.cadre_graphique(rangee1, 0, t("dash_top_produits"))
        self._cadre_donut = graph.cadre_graphique(rangee1, 1, t("dash_repartition"))

        # Évolution du CA (pleine largeur)
        rangee2 = ttk.Frame(self)
        rangee2.grid(row=3, column=0, sticky="nsew", padx=theme.PAD_L,
                     pady=(0, theme.PAD_L))
        rangee2.columnconfigure(0, weight=1)
        rangee2.rowconfigure(0, weight=1)
        self._cadre_evolution = graph.cadre_graphique(rangee2, 0, t("dash_evolution"))

    # Rafraîchissement --------------------------------------------------------
    def rafraichir(self) -> None:
        """Recharge KPI et graphiques (année en cours)."""
        aujourdhui = date.today()
        stats = self.app.stats

        kpi_jour = stats.kpi_ca_jour(aujourdhui)
        kpi_mois = stats.kpi_ca_mois(aujourdhui)
        kpi_annee = stats.kpi_ca_annee(aujourdhui)
        kpi_nb = stats.kpi_nb_ventes_annee(aujourdhui)
        self._cartes["jour"].definir(format_fcfa(kpi_jour.valeur), kpi_jour.variation_pct)
        self._cartes["mois"].definir(format_fcfa(kpi_mois.valeur), kpi_mois.variation_pct)
        self._cartes["annee"].definir(format_fcfa(kpi_annee.valeur),
                                      kpi_annee.variation_pct)
        self._cartes["nb"].definir(str(kpi_nb.valeur), kpi_nb.variation_pct)
        self._cartes["panier"].definir(format_fcfa(stats.panier_moyen_annee(aujourdhui)))

        debut_annee = date(aujourdhui.year, 1, 1)
        fin_annee = date(aujourdhui.year, 12, 31)
        par = "quantite" if self.var_top.get() == t("dash_top_quantite") else "ca"
        texte_vide = t("dash_aucune_vente")
        graph.dessiner_top_produits(
            self._cadre_top, stats.top_produits(debut_annee, fin_annee, par=par),
            texte_vide, self._canvases)
        graph.dessiner_repartition_gamme(
            self._cadre_donut, stats.repartition_par_gamme(debut_annee, fin_annee),
            texte_vide, self._canvases)
        granularite = self._granularites.get(self.var_granularite.get(), "mois")
        graph.dessiner_evolution_ca(
            self._cadre_evolution, stats.serie_ca(debut_annee, fin_annee, granularite),
            texte_vide, self._canvases)
