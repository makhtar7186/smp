"""Tests de /admin/factures (Archive à distance) — role_facturation
uniquement. Voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
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

    facturation = FacturationService(creer_connexion(chemin_db))
    with TestClient(app) as test_client:
        yield test_client, facturation


def _en_tete(token: str) -> dict:
    return {"X-API-Key": token}


def _facture(facturation: FacturationService, numero: int) -> int:
    facture = facturation.enregistrer_facture(
        numero=numero, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=1, prix_unitaire=10000)],
    )
    return facture.id


def test_role_client_refuse_403(client) -> None:
    test_client, _ = client
    reponse = test_client.get("/admin/factures", headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 403


def test_sans_jeton_401(client) -> None:
    test_client, _ = client
    reponse = test_client.get("/admin/factures")
    assert reponse.status_code == 401


def test_liste_toutes_les_factures_actives(client) -> None:
    test_client, facturation = client
    _facture(facturation, 260601)
    reponse = test_client.get("/admin/factures", headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert any(f["numero"] == 260601 for f in donnees)
    assert all(f["archivee"] is False for f in donnees)


def test_archiver_ids_puis_filtrer(client) -> None:
    test_client, facturation = client
    facture_id = _facture(facturation, 260602)

    reponse = test_client.post(
        "/admin/factures/archiver-ids", json={"ids": [facture_id]},
        headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    assert reponse.json()["nb"] == 1

    actives = test_client.get(
        "/admin/factures?archivee=false", headers=_en_tete(_TOKEN_FACTURATION)).json()
    assert not any(f["id"] == facture_id for f in actives)
    archivees = test_client.get(
        "/admin/factures?archivee=true", headers=_en_tete(_TOKEN_FACTURATION)).json()
    assert any(f["id"] == facture_id for f in archivees)


def test_desarchiver_ids(client) -> None:
    test_client, facturation = client
    facture_id = _facture(facturation, 260603)
    test_client.post("/admin/factures/archiver-ids", json={"ids": [facture_id]},
                     headers=_en_tete(_TOKEN_FACTURATION))
    reponse = test_client.post(
        "/admin/factures/desarchiver-ids", json={"ids": [facture_id]},
        headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    actives = test_client.get(
        "/admin/factures?archivee=false", headers=_en_tete(_TOKEN_FACTURATION)).json()
    assert any(f["id"] == facture_id for f in actives)


def test_archiver_et_desarchiver_periode(client) -> None:
    test_client, facturation = client
    _facture(facturation, 260604)
    corps = {"date_debut": "2026-01-01", "date_fin": "2026-12-31"}
    reponse = test_client.post(
        "/admin/factures/archiver-periode", json=corps, headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    assert reponse.json()["nb"] >= 1
    reponse2 = test_client.post(
        "/admin/factures/desarchiver-periode", json=corps, headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse2.status_code == 200
    assert reponse2.json()["nb"] >= 1


def test_role_principal_refuse_403_sur_ecriture(client, monkeypatch) -> None:
    monkeypatch.setenv("PROMATELAS_API_TOKEN_PRINCIPAL", "jeton-role-principal")
    test_client, facturation = client
    facture_id = _facture(facturation, 260605)
    reponse = test_client.post(
        "/admin/factures/archiver-ids", json={"ids": [facture_id]},
        headers=_en_tete("jeton-role-principal"))
    assert reponse.status_code == 403


def test_statut_archivage(client) -> None:
    """Sert ArchiveStatutSyncWorker : indique, parmi des numéros connus
    localement par une machine de facturation, lesquels sont archivés."""
    test_client, facturation = client
    facture_id = _facture(facturation, 260606)
    test_client.post("/admin/factures/archiver-ids", json={"ids": [facture_id]},
                     headers=_en_tete(_TOKEN_FACTURATION))
    _facture(facturation, 260607)  # reste active

    reponse = test_client.post(
        "/admin/factures/statut-archivage",
        json={"numeros": [260606, 260607, 999999]},
        headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    assert reponse.json()["numeros_archives"] == [260606]


def test_statut_archivage_role_client_refuse_403(client) -> None:
    test_client, _facturation = client
    reponse = test_client.post(
        "/admin/factures/statut-archivage", json={"numeros": [1]},
        headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 403
