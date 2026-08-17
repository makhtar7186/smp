"""Smoke test de JournalFusionsView (lecture seule) et de son intégration
dans la navigation de l'application principale (boss)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from app.models import HistoriqueFusion
from app.repositories.historique_fusion_repository import HistoriqueFusionRepository
from app.ui import theme
from app.ui.views.journal_fusions_view import JournalFusionsView


class _FauxApplication:
    pass


@pytest.fixture()
def vue(conn):
    application = _FauxApplication()
    application.conn = conn
    root = tk.Tk()
    root.withdraw()
    theme.appliquer_theme(root)
    vue = JournalFusionsView(root, application)
    yield vue, application
    root.destroy()


def test_rafraichir_liste_vide_ne_leve_pas(vue) -> None:
    vue_, _ = vue
    vue_.rafraichir()
    assert vue_._entrees == []


def test_rafraichir_affiche_les_entrees_avec_conflit(vue) -> None:
    vue_, application = vue
    HistoriqueFusionRepository(application.conn).enregistrer(HistoriqueFusion(
        machine_origine="comptoir-1", demande_le="2026-03-01T09:00:00",
        client_a_garder_nom="CIBLE", client_a_garder_adresse="DAKAR",
        client_a_supprimer_nom="SOURCE", client_a_supprimer_adresse="THIES",
        client_a_garder_id_serveur=1, client_a_supprimer_id_serveur=2,
        conflit_detecte=True,
        etat_avant_json='{"cible": {"nom": "CIBLE"}}',
        etat_apres_json='{"cible": {"nom": "CIBLE"}}',
    ))
    vue_.rafraichir()
    assert len(vue_._entrees) == 1
    assert vue_._entrees[0].conflit_detecte is True


def test_app_boss_nav_inclut_journal_fusions() -> None:
    from app.ui.app import _ELEMENTS_NAV
    cles = {cle for cle, _, _ in _ELEMENTS_NAV}
    assert "journal_fusions" in cles
