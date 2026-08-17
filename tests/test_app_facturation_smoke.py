"""Smoke test : ApplicationFacturation se construit sans erreur, avec un
cache local temporaire, et permet de naviguer vers chaque vue de son
périmètre restreint (Facturation/Proforma/Ventes/Produits/Clients). N'appelle
jamais `mainloop()` ni ne démarre les workers réseau (le `after(150, ...)` de
démarrage ne se déclenche pas sans boucle d'événements active)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.sync import config_sync
from app.ui.app_facturation import _ELEMENTS_NAV, ApplicationFacturation


@pytest.fixture()
def app_facturation(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "CHEMIN_CACHE_FACTURATION", tmp_path / "cache.db")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config_sync, "CHEMIN_CONFIG_SYNC", tmp_path / "sync_config.json")
    application = ApplicationFacturation()
    application.withdraw()
    yield application
    application.destroy()


def test_construction_et_attributs_de_service(app_facturation) -> None:
    app = app_facturation
    assert app.facturation is not None
    assert app.proformas is not None
    assert app.clients_maintenance is not None
    assert app.pdf is not None
    assert app.sync_worker is not None
    assert app.referentiel_worker is not None


def test_navigation_vers_chaque_vue_du_perimetre(app_facturation) -> None:
    app = app_facturation
    for cle in ("facturation", "proforma", "ventes", "produits", "clients"):
        app.afficher_vue(cle)
        assert app._vue_courante == cle


def test_pas_de_pages_boss_only_dans_la_nav(app_facturation) -> None:
    cles_nav = {cle for cle, _, _ in _ELEMENTS_NAV}
    interdites = {"dashboard", "remises", "archive", "paiements", "api",
                 "analyse", "vue_client"}
    assert not (cles_nav & interdites)
