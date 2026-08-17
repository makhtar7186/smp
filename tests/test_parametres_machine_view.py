"""Smoke test de ParametresMachineView et de son intégration dans la nav de
l'application principale (boss). Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import tkinter as tk

import pytest

from app import config
from app.ui import theme
from app.ui.views.parametres_machine_view import ParametresMachineView


class _FauxApplication:
    pass


@pytest.fixture()
def vue(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    application = _FauxApplication()
    root = tk.Tk()
    root.withdraw()
    theme.appliquer_theme(root)
    vue = ParametresMachineView(root, application)
    yield vue
    root.destroy()


def test_mode_par_defaut_est_principale(vue) -> None:
    assert vue.var_mode.get() == "principale"


def test_enregistrer_facturation_distante_persiste(vue) -> None:
    vue.var_mode.set("facturation_distante")
    vue._enregistrer()
    assert config.lire_mode_machine() == "facturation_distante"


def test_rafraichir_relit_le_mode_courant(vue) -> None:
    config.definir_mode_machine("facturation_distante")
    vue.rafraichir()
    assert vue.var_mode.get() == "facturation_distante"


def test_app_boss_nav_inclut_parametres_machine() -> None:
    from app.ui.app import _ELEMENTS_NAV
    cles = {cle for cle, _, _ in _ELEMENTS_NAV}
    assert "parametres_machine" in cles
