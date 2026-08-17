"""Tests des endpoints de synchronisation offline-first (réservation de
numéros, référentiels) — voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.models import Client, LigneVente, Produit
from app.repositories.base_repository import creer_connexion
from app.repositories.client_repository import ClientRepository
from app.repositories.produit_repository import ProduitRepository
from app.services.facturation_service import FacturationService

_TOKEN_CLIENT = "jeton-role-client"
_TOKEN_FACTURATION = "jeton-role-facturation"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from app import config
    chemin_db = tmp_path / "test.db"
    monkeypatch.setattr(config, "CHEMIN_DB", chemin_db)
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setenv("PROMATELAS_API_TOKEN_CLIENT", _TOKEN_CLIENT)
    monkeypatch.setenv("PROMATELAS_API_TOKEN_FACTURATION", _TOKEN_FACTURATION)

    conn = creer_connexion(chemin_db)
    with TestClient(app) as test_client:
        yield test_client, conn


def _en_tete(token: str) -> dict:
    return {"X-API-Key": token}


class TestReserverNumeros:
    def test_role_facturation_recoit_un_bloc(self, client):
        test_client, _ = client
        reponse = test_client.post(
            "/factures/reserver-numeros",
            json={"quantite": 10, "machine_id": "comptoir-1"},
            headers=_en_tete(_TOKEN_FACTURATION),
        )
        assert reponse.status_code == 200
        assert len(reponse.json()["numeros"]) == 10

    def test_role_client_refuse_403(self, client):
        test_client, _ = client
        reponse = test_client.post(
            "/factures/reserver-numeros",
            json={"quantite": 5},
            headers=_en_tete(_TOKEN_CLIENT),
        )
        assert reponse.status_code == 403

    def test_jeton_invalide_401(self, client):
        test_client, _ = client
        reponse = test_client.post(
            "/factures/reserver-numeros",
            json={"quantite": 5},
            headers=_en_tete("faux-jeton"),
        )
        assert reponse.status_code == 401

    def test_deux_blocs_successifs_ne_se_chevauchent_pas(self, client):
        test_client, _ = client
        premier = test_client.post(
            "/factures/reserver-numeros", json={"quantite": 5},
            headers=_en_tete(_TOKEN_FACTURATION)).json()["numeros"]
        second = test_client.post(
            "/factures/reserver-numeros", json={"quantite": 5},
            headers=_en_tete(_TOKEN_FACTURATION)).json()["numeros"]
        assert not set(premier) & set(second)
        assert second[0] == premier[-1] + 1


class TestReferentiels:
    def test_referentiel_produits(self, client):
        test_client, conn = client
        ProduitRepository(conn).creer(Produit(
            nom="SM TAPISSIER", type_option="dimension", valeur_option="140X190",
            prix=10000))
        reponse = test_client.get("/referentiels/produits",
                                  headers=_en_tete(_TOKEN_FACTURATION))
        assert reponse.status_code == 200
        donnees = reponse.json()
        assert any(p["nom"] == "SM TAPISSIER" for p in donnees)

    def test_referentiel_clients(self, client):
        test_client, conn = client
        clients = ClientRepository(conn)
        clients.creer(Client(nom="REVENDEUR X", adresse="DAKAR"))
        reponse = test_client.get("/referentiels/clients",
                                  headers=_en_tete(_TOKEN_FACTURATION))
        assert reponse.status_code == 200
        donnees = {c["nom"]: c for c in reponse.json()}
        assert donnees["REVENDEUR X"]["adresse"] == "DAKAR"

    def test_role_client_refuse_403(self, client):
        test_client, _ = client
        reponse = test_client.get("/referentiels/produits",
                                  headers=_en_tete(_TOKEN_CLIENT))
        assert reponse.status_code == 403
