"""Tests de l'API Dashboard (/stats/*) — lecture seule, ouverte à tout rôle
valide. Voir CLAUDE.md, section « Machine de facturation »/onglet Dashboard
du mode client."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService

_TOKEN_CLIENT = "jeton-role-client"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from app import config
    chemin_db = tmp_path / "test.db"
    monkeypatch.setattr(config, "CHEMIN_DB", chemin_db)
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setenv("PROMATELAS_API_TOKEN_CLIENT", _TOKEN_CLIENT)

    facturation = FacturationService(creer_connexion(chemin_db))
    with TestClient(app) as test_client:
        yield test_client, facturation


def _en_tete(token: str) -> dict:
    return {"X-API-Key": token}


def _facture(facturation: FacturationService, numero: int, jour: date, prix: int) -> None:
    facturation.enregistrer_facture(
        numero=numero, date_facture=jour, nom_client="TEST", destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=1, prix_unitaire=prix)],
    )


def test_kpis_sans_jeton_401(client) -> None:
    test_client, _ = client
    reponse = test_client.get("/stats/kpis")
    assert reponse.status_code == 401


def test_kpis_reflete_les_ventes_du_jour(client) -> None:
    test_client, facturation = client
    aujourdhui = date.today()
    _facture(facturation, 260301, aujourdhui, 10000)
    reponse = test_client.get(f"/stats/kpis?jour={aujourdhui.isoformat()}",
                              headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["ca_jour"]["valeur"] == 10000
    assert donnees["panier_moyen"] == 10000


def test_top_produits(client) -> None:
    test_client, facturation = client
    aujourdhui = date.today()
    _facture(facturation, 260302, aujourdhui, 5000)
    debut = date(aujourdhui.year, 1, 1)
    fin = date(aujourdhui.year, 12, 31)
    reponse = test_client.get(
        f"/stats/top-produits?debut={debut}&fin={fin}", headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 200
    assert any("SM TAPISSIER" in p["libelle"] for p in reponse.json())


def test_repartition_gamme_et_serie_ca(client) -> None:
    test_client, facturation = client
    aujourdhui = date.today()
    _facture(facturation, 260303, aujourdhui, 5000)
    debut = date(aujourdhui.year, 1, 1)
    fin = date(aujourdhui.year, 12, 31)
    reponse_gamme = test_client.get(
        f"/stats/repartition-gamme?debut={debut}&fin={fin}", headers=_en_tete(_TOKEN_CLIENT))
    assert reponse_gamme.status_code == 200
    reponse_serie = test_client.get(
        f"/stats/serie-ca?debut={debut}&fin={fin}", headers=_en_tete(_TOKEN_CLIENT))
    assert reponse_serie.status_code == 200
    assert sum(p["ca"] for p in reponse_serie.json()) == 5000
