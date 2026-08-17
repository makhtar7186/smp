"""Tests de /admin/factures/{id} (+pdf/bordereau) — détail d'une facture
usine pour le rôle role_facturation, qui n'a pas accès à `routes.py`
(role_client/role_principal uniquement). Sert la page « Historique complet »
de la machine de facturation en mode étendu — voir CLAUDE.md, section
« Machine de facturation »."""
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


def _facture_usine(facturation: FacturationService, numero: int) -> int:
    facture = facturation.enregistrer_facture(
        numero=numero, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=1, prix_unitaire=10000)],
    )
    return facture.id


def test_liste_expose_telephone(client) -> None:
    test_client, facturation = client
    facturation.enregistrer_facture(
        numero=260900, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR", telephone="77 000 00 00",
        lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)])
    reponse = test_client.get("/admin/factures", headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees[0]["telephone"] == "77 000 00 00"


def test_role_client_refuse_403(client) -> None:
    test_client, facturation = client
    facture_id = _facture_usine(facturation, 260901)
    reponse = test_client.get(
        f"/admin/factures/{facture_id}", headers=_en_tete(_TOKEN_CLIENT))
    assert reponse.status_code == 403


def test_sans_jeton_401(client) -> None:
    test_client, facturation = client
    facture_id = _facture_usine(facturation, 260902)
    reponse = test_client.get(f"/admin/factures/{facture_id}")
    assert reponse.status_code == 401


def test_detail_facture_usine(client) -> None:
    test_client, facturation = client
    facture_id = _facture_usine(facturation, 260903)
    reponse = test_client.get(
        f"/admin/factures/{facture_id}", headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 200
    donnees = reponse.json()
    assert donnees["numero"] == 260903
    assert donnees["client_nom"] == "TEST"
    assert len(donnees["lignes"]) == 1


def test_facture_introuvable_404(client) -> None:
    test_client, _facturation = client
    reponse = test_client.get(
        "/admin/factures/999999", headers=_en_tete(_TOKEN_FACTURATION))
    assert reponse.status_code == 404


def test_pdf_et_bordereau(client) -> None:
    test_client, facturation = client
    facture_id = _facture_usine(facturation, 260905)
    pdf = test_client.get(
        f"/admin/factures/{facture_id}/pdf", headers=_en_tete(_TOKEN_FACTURATION))
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    bordereau = test_client.get(
        f"/admin/factures/{facture_id}/bordereau", headers=_en_tete(_TOKEN_FACTURATION))
    assert bordereau.status_code == 200
    assert bordereau.headers["content-type"] == "application/pdf"
