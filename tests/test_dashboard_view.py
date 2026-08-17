"""Smoke test de DashboardView : construction Tkinter headless + rafraîchir
avec des données réelles, à la fois panier vide et panier peuplé (couvre le
chemin "message vide" ET le chemin "graphique tracé", pour la non-régression
du refactor vers app.ui.components.graphiques_dashboard)."""
from __future__ import annotations

import tkinter as tk
from datetime import date

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.stats_service import StatsService
from app.ui import theme
from app.ui.views.dashboard_view import DashboardView


class _FauxApplication:
    pass


@pytest.fixture()
def vue(conn):
    application = _FauxApplication()
    application.stats = StatsService(conn)
    application.facturation = FacturationService(conn)
    root = tk.Tk()
    root.withdraw()
    theme.appliquer_theme(root)
    vue = DashboardView(root, application)
    yield vue, application
    root.destroy()


def test_rafraichir_panier_vide_ne_leve_pas(vue) -> None:
    vue_, _ = vue
    vue_.rafraichir()  # aucune vente : chemin "message vide" des 3 graphiques


def test_rafraichir_avec_des_ventes(vue) -> None:
    vue_, application = vue
    application.facturation.enregistrer_facture(
        numero=260501, date_facture=date.today(), nom_client="TEST",
        destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=2, prix_unitaire=10000)],
    )
    vue_.rafraichir()
    assert vue_._cartes["jour"] is not None
