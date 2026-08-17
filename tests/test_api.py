"""Tests de l'API distante en lecture seule : auth, liste, détail, PDF, 404."""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.api.deps import obtenir_facturation, obtenir_pdf
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService

_TOKEN = "jeton-de-test"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Client de test avec une base sur fichier temporaire et un jeton API
    connu. Chaque requête HTTP peut être exécutée sur un thread différent
    (FastAPI exécute les endpoints sync dans un threadpool) : comme en
    production, la dépendance API ouvre donc une connexion SQLite fraîche par
    appel plutôt que de partager une connexion entre threads (interdit par
    sqlite3). Un service séparé, sur sa propre connexion, sert à préparer les
    données du test."""
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setenv("PROMATELAS_API_TOKEN_CLIENT", _TOKEN)
    chemin_db = tmp_path / "test.db"
    facturation = FacturationService(creer_connexion(chemin_db))

    def _override_facturation():
        conn = creer_connexion(chemin_db)
        try:
            yield FacturationService(conn)
        finally:
            conn.close()

    app.dependency_overrides[obtenir_facturation] = _override_facturation
    app.dependency_overrides[obtenir_pdf] = lambda: PdfService(tmp_path)

    with TestClient(app) as test_client:
        yield test_client, facturation

    app.dependency_overrides.clear()


def _en_tete(token: str = _TOKEN) -> dict:
    return {"X-API-Key": token}


class TestAuth:
    def test_sans_jeton_401(self, client):
        test_client, _ = client
        reponse = test_client.get("/factures")
        assert reponse.status_code == 401

    def test_mauvais_jeton_401(self, client):
        test_client, _ = client
        reponse = test_client.get("/factures", headers=_en_tete("faux"))
        assert reponse.status_code == 401

    def test_bon_jeton_200(self, client):
        test_client, _ = client
        reponse = test_client.get("/factures", headers=_en_tete())
        assert reponse.status_code == 200

    def test_health_sans_jeton(self, client):
        test_client, _ = client
        assert test_client.get("/health").status_code == 200


class TestListeFactures:
    def test_liste_vide(self, client):
        test_client, _ = client
        reponse = test_client.get("/factures", headers=_en_tete())
        assert reponse.json() == []

    def test_liste_contient_facture_usine(self, client):
        test_client, facturation = client
        from app.models import LigneVente
        facturation.enregistrer_facture(
            numero=260001, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR", telephone="77 000 00 00",
            lignes=[LigneVente(designation="SM TAPISSIER 140X190X",
                               quantite=2, prix_unitaire=10000)],
        )
        reponse = test_client.get("/factures", headers=_en_tete())
        donnees = reponse.json()
        assert len(donnees) == 1
        assert donnees[0]["numero"] == 260001
        assert donnees[0]["total"] == 20000
        assert donnees[0]["telephone"] == "77 000 00 00"

    def test_facture_archivee_par_appli_principale_reste_exposee(self, client):
        """Chaque application gère son propre système d'archivage (voir
        CLAUDE.md, section « Archivage ») : une facture archivée via
        l'application principale (FacturationService.archiver_ids) doit
        rester visible sur l'API distante — l'app cliente décide seule de ce
        qu'elle masque, indépendamment."""
        test_client, facturation = client
        from app.models import LigneVente
        facture = facturation.enregistrer_facture(
            numero=260010, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR",
            lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                               quantite=1, prix_unitaire=5000)],
        )
        facturation.archiver_ids([facture.id])
        reponse = test_client.get("/factures", headers=_en_tete())
        donnees = reponse.json()
        assert any(f["numero"] == 260010 for f in donnees)


class TestDetailFacture:
    def test_detail_ok(self, client):
        test_client, facturation = client
        from app.models import LigneVente
        facture = facturation.enregistrer_facture(
            numero=260003, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR",
            lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                               quantite=2, prix_unitaire=10000)],
        )
        reponse = test_client.get(f"/factures/{facture.id}", headers=_en_tete())
        assert reponse.status_code == 200
        donnees = reponse.json()
        assert donnees["numero"] == 260003
        assert len(donnees["lignes"]) == 1
        assert donnees["total"] == 20000

    def test_facture_inexistante_404(self, client):
        test_client, _ = client
        reponse = test_client.get("/factures/9999", headers=_en_tete())
        assert reponse.status_code == 404


class TestPdf:
    def test_pdf_facture(self, client):
        test_client, facturation = client
        from app.models import LigneVente
        facture = facturation.enregistrer_facture(
            numero=260005, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR",
            lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                               quantite=2, prix_unitaire=10000)],
        )
        reponse = test_client.get(f"/factures/{facture.id}/pdf", headers=_en_tete())
        assert reponse.status_code == 200
        assert reponse.headers["content-type"] == "application/pdf"

    def test_bordereau_facture(self, client):
        test_client, facturation = client
        from app.models import LigneVente
        facture = facturation.enregistrer_facture(
            numero=260006, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR",
            lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                               quantite=2, prix_unitaire=10000)],
        )
        reponse = test_client.get(f"/factures/{facture.id}/bordereau",
                                  headers=_en_tete())
        assert reponse.status_code == 200
        assert reponse.headers["content-type"] == "application/pdf"

    def test_pdf_facture_inexistante_404(self, client):
        test_client, _ = client
        reponse = test_client.get("/factures/9999/pdf", headers=_en_tete())
        assert reponse.status_code == 404
