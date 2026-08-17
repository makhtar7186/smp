"""Tests des onglets Dashboard/Remises du mode client (`OngletDashboard`,
`OngletRemises`) — équivalents distants de `DashboardView`/`RemisesView`,
alimentés par `ApiClient`. Voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.client import archive_client, config_client, queue_hors_ligne
from app.client.ui import ApplicationClient


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "CHEMIN_DB", tmp_path / "promatelas.db")
    monkeypatch.setattr(config_client, "CHEMIN_CONFIG_CLIENT", tmp_path / "client_config.json")
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT",
                        tmp_path / "factures_archivees_client.json")
    monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "versements_en_attente.json")
    application = ApplicationClient()
    application.withdraw()
    yield application
    application.destroy()


class _FauxApi:
    def stats_kpis(self, jour=None):
        return {
            "ca_jour": {"valeur": 1000, "precedent": 500, "variation_pct": 100.0},
            "ca_mois": {"valeur": 5000, "precedent": 4000, "variation_pct": 25.0},
            "ca_annee": {"valeur": 50000, "precedent": 40000, "variation_pct": 25.0},
            "nb_ventes": {"valeur": 5, "precedent": 4, "variation_pct": 25.0},
            "panier_moyen": 10000,
        }

    def stats_top_produits(self, debut, fin, par="quantite", limite=10):
        return [{"libelle": "SM TAPISSIER", "valeur": 5}]

    def stats_repartition_gamme(self, debut, fin):
        return [{"gamme": "SM TAPISSIER", "ca": 5000}]

    def stats_serie_ca(self, debut, fin, granularite="mois"):
        return [{"periode": "2026-01", "ca": 5000}]

    def remises_tableau(self, annee):
        return [{"client_id": 1, "client_nom": "X", "client_adresse": "DAKAR",
                "ca_annuel": 10000, "taux": 5.0, "montant": 500, "note": ""}]

    def appliquer_remise_annuelle(self, client_id, annee, ca_annuel, taux, note=""):
        return {"id": 1}


def test_onglets_construits_et_presents(app_client) -> None:
    app = app_client
    assert app.onglet_dashboard is not None
    assert app.onglet_remises is not None


def test_dashboard_sans_api_ne_leve_pas(app_client) -> None:
    app_client.onglet_dashboard.actualiser()  # self.api est None avant _demarrage()


def test_dashboard_actualiser_avec_donnees(app_client) -> None:
    app = app_client
    app.api = _FauxApi()
    app.onglet_dashboard.actualiser()
    assert app.onglet_dashboard._statut.cget("text") == ""


def test_remises_actualiser_et_afficher_tableau(app_client) -> None:
    app = app_client
    app.api = _FauxApi()
    app.onglet_remises.actualiser()
    assert len(app.onglet_remises._lignes) == 1
