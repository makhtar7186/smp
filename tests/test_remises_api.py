"""Tests de GET /remises/tableau — lecture seule du tableau CA annuel/remise
par client, équivalent distant de RemisesView. L'écriture (POST
/clients/{id}/remise-annuelle) est déjà testée dans tests/test_paiements.py."""
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


def test_sans_jeton_401(client) -> None:
    test_client, _ = client
    reponse = test_client.get("/remises/tableau?annee=2026")
    assert reponse.status_code == 401


def test_tableau_reflete_le_ca_annuel(client) -> None:
    test_client, facturation = client
    facturation.enregistrer_facture(
        numero=260401, date_facture=date(2026, 3, 1), nom_client="GROS CLIENT",
        destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=2, prix_unitaire=10000)],
    )
    reponse = test_client.get("/remises/tableau?annee=2026", headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 200
    lignes = reponse.json()
    ligne = next(l for l in lignes if l["client_nom"] == "GROS CLIENT")
    assert ligne["ca_annuel"] == 20000
    assert ligne["taux"] == 0.0


def test_ecriture_remise_annuelle_puis_relecture_du_tableau(client) -> None:
    test_client, facturation = client
    facturation.enregistrer_facture(
        numero=260402, date_facture=date(2026, 4, 1), nom_client="AUTRE CLIENT",
        destination="THIES",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=1, prix_unitaire=10000)],
    )
    facture = facturation.obtenir_facture(
        facturation.lister_factures(client_id=None)[0].id)
    client_id = facture.client_id

    reponse_ecriture = test_client.post(
        f"/clients/{client_id}/remise-annuelle",
        json={"annee": 2026, "ca_annuel": 10000, "taux": 5.0, "note": "fidélité"},
        headers=_en_tete(_TOKEN_CLIENT),
    )
    assert reponse_ecriture.status_code == 200

    reponse = test_client.get("/remises/tableau?annee=2026", headers=_en_tete(_TOKEN_CLIENT))
    ligne = next(l for l in reponse.json() if l["client_id"] == client_id)
    assert ligne["taux"] == 5.0
    assert ligne["montant"] == 500
    assert ligne["note"] == "fidélité"
