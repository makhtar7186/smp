"""Tests de AccesDirectDonnees : mêmes lectures qu'ApiClient (HTTP) mais en
base directe, utilisé par ApplicationClient quand ce poste héberge lui-même
son serveur — voir CLAUDE.md, section « Accès distant »."""
from __future__ import annotations

from datetime import date

import pytest

from app import config
from app.client.acces_direct import AccesDirectDonnees
from app.client.api_client import ErreurApiClient
from app.client.config_client import ConfigClient
from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService
from app.services.remise_service import RemiseService


@pytest.fixture()
def acces(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_EXPORTS", tmp_path / "exports")
    conn = creer_connexion(tmp_path / "test.db")
    cfg = ConfigClient(hote="127.0.0.1", port=8420, token="jeton-role-client")
    return AccesDirectDonnees(conn, cfg), conn


def _facture(conn, numero: int, remise_taux: float = 0.0):
    facturation = FacturationService(conn)
    return facturation.enregistrer_facture(
        numero=numero, date_facture=date(2026, 7, 1), nom_client="TEST",
        destination="DAKAR", remise_taux=remise_taux,
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=2, prix_unitaire=10000)],
    )


def test_lister_factures_meme_forme_que_l_api(acces):
    direct, conn = acces
    facture = _facture(conn, 260101)
    factures = direct.lister_factures()
    assert len(factures) == 1
    ligne = factures[0]
    assert ligne["id"] == facture.id
    assert ligne["numero"] == 260101
    assert ligne["date_facture"] == "2026-07-01"
    assert ligne["client_nom"] == "TEST"
    assert ligne["total"] == 20000
    assert ligne["nb_lignes"] == 1


def test_telecharger_pdf_et_bordereau_retournent_des_octets(acces):
    direct, conn = acces
    facture = _facture(conn, 260102)
    pdf = direct.telecharger_pdf(facture.id)
    bordereau = direct.telecharger_bordereau(facture.id)
    assert isinstance(pdf, bytes) and pdf.startswith(b"%PDF")
    assert isinstance(bordereau, bytes) and bordereau.startswith(b"%PDF")


def test_facture_introuvable_leve_erreur_api_client(acces):
    direct, _conn = acces
    with pytest.raises(ErreurApiClient):
        direct.telecharger_pdf(999)
    with pytest.raises(ErreurApiClient):
        direct.obtenir_facture_paiement(999)


def test_lister_factures_paiements_et_totaux(acces):
    direct, conn = acces
    _facture(conn, 260104)
    lignes = direct.lister_factures_paiements()
    assert len(lignes) == 1
    assert lignes[0]["total"] == 20000
    assert lignes[0]["verse"] == 0
    assert lignes[0]["restant"] == 20000

    totaux = direct.totaux_paiements()
    assert totaux == {"total_facture": 20000, "total_verse": 0, "total_restant": 20000}


def test_obtenir_facture_paiement_detail(acces):
    direct, conn = acces
    facture = _facture(conn, 260105)
    detail = direct.obtenir_facture_paiement(facture.id)
    assert detail["numero"] == 260105
    assert detail["solde"] == {"facture_id": facture.id, "total": 20000,
                               "verse": 0, "restant": 20000}
    assert detail["versements"] == []


def test_rechercher_clients(acces):
    direct, conn = acces
    _facture(conn, 260106)
    resultats = direct.rechercher_clients("TEST")
    assert len(resultats) == 1
    assert resultats[0]["nom"] == "TEST"


def test_stats_et_remises_sur_base_vide_ne_levent_pas(acces):
    direct, _conn = acces
    debut, fin = date(2026, 1, 1), date(2026, 12, 31)
    kpis = direct.stats_kpis(date(2026, 7, 1))
    assert kpis["ca_jour"]["valeur"] == 0
    assert direct.stats_top_produits(debut, fin) == []
    assert direct.stats_repartition_gamme(debut, fin) == []
    assert direct.stats_serie_ca(debut, fin) == []
    assert direct.remises_tableau(2026) == []


def test_remises_tableau_reflete_le_ca_client(acces):
    direct, conn = acces
    _facture(conn, 260107)
    lignes = direct.remises_tableau(2026)
    assert len(lignes) == 1
    assert lignes[0]["client_nom"] == "TEST"
    assert lignes[0]["ca_annuel"] == 20000


def test_ecritures_deleguees_au_client_http(acces, monkeypatch):
    """Les écritures (versement, remise annuelle) doivent passer par le
    client HTTP interne — jamais directement en SQLite — pour préserver la
    file FIFO du serveur contre les écritures concurrentes."""
    direct, _conn = acces
    appels = []
    monkeypatch.setattr(
        direct._http, "creer_versement",
        lambda facture_id, montant, date_versement, remarque="": appels.append(
            ("versement", facture_id, montant, date_versement, remarque)) or {"id": 1})
    monkeypatch.setattr(
        direct._http, "appliquer_remise_annuelle",
        lambda client_id, annee, ca_annuel, taux, note="": appels.append(
            ("remise", client_id, annee, ca_annuel, taux, note)) or {"id": 1})

    direct.creer_versement(5, 1000, date(2026, 7, 1), "acompte")
    direct.appliquer_remise_annuelle(3, 2026, 50000, 5.0)

    assert appels == [
        ("versement", 5, 1000, date(2026, 7, 1), "acompte"),
        ("remise", 3, 2026, 50000, 5.0, ""),
    ]
