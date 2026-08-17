"""Smoke test de ApplicationFacturationEtendue : construction Tk headless,
périmètre de nav étendu, non-régression de ApplicationFacturation (base) qui
ne doit gagner aucune des nouvelles entrées. Voir CLAUDE.md, section
« Machine de facturation ».

Les pages réseau uniquement (Archive/Paiements/Vue client/Historique
complet) ne sont JAMAIS navigées avec un `api_admin`/`api` réel dans ces
tests — `ConfigSync`/`ConfigClient` par défaut ont un hôte vide, et une
requête `requests` vers un hôte vide peut bloquer bien au-delà du timeout de
connexion attendu selon la plateforme. On y navigue uniquement après avoir
remplacé `api_admin`/`api` par un faux client (mêmes noms de méthode), jamais
de réseau réel."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.sync import config_sync
from app.ui.app_facturation import ApplicationFacturation
from app.ui.app_facturation_etendue import ApplicationFacturationEtendue


class _FauxApiAdmin:
    def lister_factures_admin(self, **kwargs):
        return []


@pytest.fixture()
def app_etendue(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "CHEMIN_CACHE_FACTURATION", tmp_path / "cache.db")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config_sync, "CHEMIN_CONFIG_SYNC", tmp_path / "sync_config.json")
    application = ApplicationFacturationEtendue()
    application.withdraw()
    application.api_admin = _FauxApiAdmin()
    yield application
    application.destroy()


def test_elements_nav_etendus(app_etendue) -> None:
    cles = [cle for cle, _, _ in app_etendue.ELEMENTS_NAV]
    for cle in ("facturation", "proforma", "ventes", "produits", "clients",
               "historique_complet", "archive", "paiements", "vue_client"):
        assert cle in cles
    assert len(cles) == 9


def test_base_ne_gagne_aucune_entree(tmp_path: Path, monkeypatch) -> None:
    """Non-régression du refactor d'extensibilité : `ApplicationFacturation`
    (classe de base, nav restreinte) doit rester inchangée."""
    monkeypatch.setattr(config, "CHEMIN_CACHE_FACTURATION", tmp_path / "cache2.db")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config_sync, "CHEMIN_CONFIG_SYNC", tmp_path / "sync_config2.json")
    base = ApplicationFacturation()
    try:
        cles = [cle for cle, _, _ in base.ELEMENTS_NAV]
        assert cles == ["facturation", "proforma", "ventes", "produits", "clients"]
    finally:
        base.destroy()


def test_api_et_api_admin_construits_avec_le_jeton_facturation(app_etendue) -> None:
    app_etendue._config_sync.token = "jeton-facturation-test"
    app_etendue.api = app_etendue._construire_api_client()
    assert app_etendue.api._config.token == "jeton-facturation-test"
    assert app_etendue.api_admin is not None


def test_navigation_vers_les_vues_offline_first(app_etendue) -> None:
    for cle in ("facturation", "proforma", "ventes", "produits", "clients"):
        app_etendue.afficher_vue(cle)
        assert app_etendue._vue_courante == cle


def test_navigation_vers_les_vues_reseau_avec_faux_client(app_etendue) -> None:
    """`api_admin` est remplacé par un faux client (voir fixture) — jamais
    de requête réseau réelle dans ce test."""
    for cle in ("historique_complet", "archive"):
        app_etendue.afficher_vue(cle)
        assert app_etendue._vue_courante == cle
