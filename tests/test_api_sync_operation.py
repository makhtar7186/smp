"""Tests HTTP de POST /sync/operation — 400 sur erreur métier, 401/403 par
rôle. Voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.repositories.base_repository import creer_connexion
from app.sync.payloads import cle_correlation_facture

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
    creer_connexion(chemin_db).close()
    with TestClient(app) as test_client:
        yield test_client


def _en_tete(token: str) -> dict:
    return {"X-API-Key": token}


def _corps_creation_facture(numero: int) -> dict:
    payload = {
        "numero": numero, "date_facture": "2026-03-01", "nom_client": "TEST",
        "destination": "DAKAR", "etabli_par": "",
        "remise_taux": 0.0,
        "lignes": [{"designation": "SM TAPISSIER 140X190X",
                   "quantite": 1, "prix_unitaire": 10000, "remarque": ""}],
    }
    return {
        "type_operation": "creation_facture",
        "cle_correlation": cle_correlation_facture(numero),
        "payload": payload,
        "cree_le": "2026-03-01T09:00:00",
    }


def test_creation_facture_reussie(client) -> None:
    reponse = client.post("/sync/operation", json=_corps_creation_facture(260001),
                          headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ok"
    assert reponse.json()["id_correlation_serveur"] is not None


def test_erreur_metier_retourne_400(client) -> None:
    corps = _corps_creation_facture(260002)
    corps["payload"]["lignes"] = []  # panier vide -> ErreurValidation côté serveur
    reponse = client.post("/sync/operation", json=corps, headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 400


def test_role_client_refuse_403(client) -> None:
    reponse = client.post("/sync/operation", json=_corps_creation_facture(260003),
                          headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 403


def test_jeton_invalide_401(client) -> None:
    reponse = client.post("/sync/operation", json=_corps_creation_facture(260004),
                          headers=_en_tete("faux-jeton"))
    assert reponse.status_code == 401
