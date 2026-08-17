"""Tests de l'API Paiements : permissions par rôle, FIFO d'écriture, recherche
client, traçabilité des remises. Voir CLAUDE.md, section « Paiements »."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService

_TOKEN_CLIENT = "jeton-role-client"
_TOKEN_PRINCIPAL = "jeton-role-principal"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """Base sur fichier temporaire, jetons des deux rôles connus. Le endpoint
    d'écriture de versement ouvre lui-même sa connexion (`creer_connexion()`
    sans argument, dans le worker de la file FIFO) : on monkeypatch donc
    `config.CHEMIN_DB`/`config.DOSSIER_DATA` plutôt que de passer par
    `dependency_overrides`, pour que toutes les connexions (lecture et
    écriture) pointent vers la même base de test."""
    from app import config
    chemin_db = tmp_path / "test.db"
    monkeypatch.setattr(config, "CHEMIN_DB", chemin_db)
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setenv("PROMATELAS_API_TOKEN_CLIENT", _TOKEN_CLIENT)
    monkeypatch.setenv("PROMATELAS_API_TOKEN_PRINCIPAL", _TOKEN_PRINCIPAL)

    facturation = FacturationService(creer_connexion(chemin_db))

    with TestClient(app) as test_client:
        yield test_client, facturation


def _en_tete(token: str) -> dict:
    return {"X-API-Key": token}


def _facture(facturation: FacturationService, numero: int) -> int:
    facture = facturation.enregistrer_facture(
        numero=numero, date_facture=date(2026, 7, 1), nom_client="TEST",
        destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=2, prix_unitaire=10000)],
    )
    return facture.id


class TestSoldeFactureApi:
    def test_impayee(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260201)
        reponse = test_client.get(
            f"/paiements/facture/{facture_id}", headers=_en_tete(_TOKEN_CLIENT))
        assert reponse.status_code == 200
        donnees = reponse.json()
        assert donnees["solde"]["restant"] == 20000
        assert donnees["versements"] == []

    def test_sur_payee(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260202)
        test_client.post(
            f"/paiements/facture/{facture_id}/versement",
            json={"montant": 25000, "date_versement": "2026-07-02"},
            headers=_en_tete(_TOKEN_CLIENT),
        )
        reponse = test_client.get(
            f"/paiements/facture/{facture_id}", headers=_en_tete(_TOKEN_PRINCIPAL))
        assert reponse.json()["solde"]["restant"] == -5000

    def test_facture_introuvable_404(self, client):
        test_client, _ = client
        reponse = test_client.get(
            "/paiements/facture/9999", headers=_en_tete(_TOKEN_CLIENT))
        assert reponse.status_code == 404

    def test_facture_archivee_par_appli_principale_reste_listee(self, client):
        """Chaque application gère son propre système d'archivage — voir
        CLAUDE.md, section « Archivage »."""
        test_client, facturation = client
        facture_id = _facture(facturation, 260212)
        facturation.archiver_ids([facture_id])
        reponse = test_client.get(
            "/paiements/factures", headers=_en_tete(_TOKEN_CLIENT))
        numeros = [f["numero"] for f in reponse.json()]
        assert 260212 in numeros

    def test_liste_expose_telephone(self, client):
        test_client, facturation = client
        facturation.enregistrer_facture(
            260213, date(2026, 7, 1), "TEST", "DAKAR",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
            telephone="77 000 00 00",
        )
        reponse = test_client.get(
            "/paiements/factures", headers=_en_tete(_TOKEN_CLIENT))
        ligne = next(f for f in reponse.json() if f["numero"] == 260213)
        assert ligne["telephone"] == "77 000 00 00"

    def test_recherche_par_telephone(self, client):
        test_client, facturation = client
        facturation.enregistrer_facture(
            260214, date(2026, 7, 1), "AUTRE CLIENT", "DAKAR",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
            telephone="77 555 66 77",
        )
        reponse = test_client.get(
            "/paiements/factures", params={"recherche": "77 555 66 77"},
            headers=_en_tete(_TOKEN_CLIENT))
        numeros = [f["numero"] for f in reponse.json()]
        assert numeros == [260214]


class TestVersementRole:
    def test_role_client_peut_ecrire(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260203)
        reponse = test_client.post(
            f"/paiements/facture/{facture_id}/versement",
            json={"montant": 5000, "date_versement": "2026-07-02"},
            headers=_en_tete(_TOKEN_CLIENT),
        )
        assert reponse.status_code == 200
        assert reponse.json()["montant"] == 5000
        assert reponse.json()["role_origine"] == "role_client"

    def test_role_principal_refuse_403(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260204)
        reponse = test_client.post(
            f"/paiements/facture/{facture_id}/versement",
            json={"montant": 5000, "date_versement": "2026-07-02"},
            headers=_en_tete(_TOKEN_PRINCIPAL),
        )
        assert reponse.status_code == 403

    def test_jeton_invalide_401(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260205)
        reponse = test_client.post(
            f"/paiements/facture/{facture_id}/versement",
            json={"montant": 5000, "date_versement": "2026-07-02"},
            headers=_en_tete("faux-jeton"),
        )
        assert reponse.status_code == 401


class TestImportLegacyApi:
    def _lignes(self):
        return [{
            "numero": 1, "date_facture": "2024-01-15", "client_nom": "ANCIEN CLIENT",
            "montant": 50000, "versement": 30000, "commentaire": "",
        }]

    def test_role_client_peut_importer(self, client):
        test_client, _ = client
        reponse = test_client.post(
            "/paiements/import-legacy", json={"lignes": self._lignes()},
            headers=_en_tete(_TOKEN_CLIENT),
        )
        assert reponse.status_code == 200
        donnees = reponse.json()
        assert donnees["importees"] == 1
        assert donnees["ignorees"] == []

    def test_role_principal_refuse_403(self, client):
        test_client, _ = client
        reponse = test_client.post(
            "/paiements/import-legacy", json={"lignes": self._lignes()},
            headers=_en_tete(_TOKEN_PRINCIPAL),
        )
        assert reponse.status_code == 403

    def test_ligne_avec_numero_deja_existant_est_reportee(self, client):
        test_client, facturation = client
        _facture(facturation, 1)  # occupe déjà le numéro 1 (plancher devient 1)
        reponse = test_client.post(
            "/paiements/import-legacy", json={"lignes": self._lignes()},
            headers=_en_tete(_TOKEN_CLIENT),
        )
        donnees = reponse.json()
        assert donnees["importees"] == 0
        assert donnees["ignorees"][0]["numero"] == 1


class TestFifoQueue:
    def test_ecritures_concurrentes_sans_perte(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260206)
        n = 20
        montant = 100

        def _poster(_i):
            return test_client.post(
                f"/paiements/facture/{facture_id}/versement",
                json={"montant": montant, "date_versement": "2026-07-02"},
                headers=_en_tete(_TOKEN_CLIENT),
            )

        with ThreadPoolExecutor(max_workers=n) as executor:
            reponses = list(executor.map(_poster, range(n)))

        assert all(r.status_code == 200 for r in reponses)
        reponse = test_client.get(
            f"/paiements/facture/{facture_id}", headers=_en_tete(_TOKEN_CLIENT))
        donnees = reponse.json()
        assert donnees["solde"]["verse"] == montant * n
        assert len(donnees["versements"]) == n


class TestRechercheClients:
    def test_recherche_par_nom_et_localite(self, client):
        test_client, facturation = client
        _facture(facturation, 260207)
        reponse = test_client.get(
            "/clients/recherche?q=TEST", headers=_en_tete(_TOKEN_PRINCIPAL))
        assert reponse.status_code == 200
        donnees = reponse.json()
        assert any(c["nom"] == "TEST" for c in donnees)
        assert "telephone" not in donnees[0]

    def test_accessible_aux_deux_roles(self, client):
        test_client, facturation = client
        _facture(facturation, 260208)
        for token in (_TOKEN_CLIENT, _TOKEN_PRINCIPAL):
            reponse = test_client.get(
                "/clients/recherche?q=TEST", headers=_en_tete(token))
            assert reponse.status_code == 200


class TestRemiseTracabilite:
    def test_remise_facture_role_principal_ok_et_tracee(self, client):
        """Remise par facture : réservée à role_principal (l'app principale
        écrit les factures, donc leur remise) — voir CLAUDE.md."""
        test_client, facturation = client
        facture_id = _facture(facturation, 260209)

        reponse = test_client.post(
            f"/paiements/facture/{facture_id}/remise",
            json={"remise_taux": 10.0}, headers=_en_tete(_TOKEN_PRINCIPAL),
        )
        assert reponse.status_code == 200
        detail = test_client.get(
            f"/paiements/facture/{facture_id}", headers=_en_tete(_TOKEN_CLIENT)
        ).json()
        assert detail["remise_modifiee_par"] == "role_principal"
        assert detail["remise_taux"] == 10.0

    def test_remise_facture_role_client_refuse_403(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260211)
        reponse = test_client.post(
            f"/paiements/facture/{facture_id}/remise",
            json={"remise_taux": 20.0}, headers=_en_tete(_TOKEN_CLIENT),
        )
        assert reponse.status_code == 403

    def test_remise_annuelle_tracee(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260210)
        client_id = facturation.obtenir_facture(facture_id).client_id
        reponse = test_client.post(
            f"/clients/{client_id}/remise-annuelle",
            json={"annee": 2026, "ca_annuel": 100000, "taux": 5.0, "note": ""},
            headers=_en_tete(_TOKEN_CLIENT),
        )
        assert reponse.status_code == 200
        donnees = reponse.json()
        assert donnees["modifie_par"] == "role_client"
        assert donnees["montant"] == 5000


class TestSyntheseClientPeriode:
    def test_periode_precise_prioritaire_sur_annee(self, client):
        test_client, facturation = client
        facture_id = _facture(facturation, 260213)
        client_id = facturation.obtenir_facture(facture_id).client_id
        reponse = test_client.get(
            f"/paiements/client/{client_id}/synthese"
            "?annee=2026&date_debut=2026-01-01&date_fin=2026-01-31",
            headers=_en_tete(_TOKEN_CLIENT),
        )
        assert reponse.status_code == 200
        # la facture est datée du 2026-07-01 (voir _facture) : hors de la
        # période précise demandée, donc absente du total malgré annee=2026
        assert reponse.json()["total_facture"] == 0
