"""Tests du service de remises annuelles."""
from __future__ import annotations

from datetime import date

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.remise_service import RemiseService


def _vendre(conn, nom_client: str, montant: int, jour: date, numero: int):
    FacturationService(conn).enregistrer_facture(
        numero, jour, nom_client, "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=montant)],
    )


def test_calcul_montant_arrondi():
    assert RemiseService.calculer_montant(1_000_000, 2.5) == 25000
    assert RemiseService.calculer_montant(999, 0.1) == 1
    assert RemiseService.calculer_montant(0, 10) == 0


def test_tableau_annee_liste_les_clients(conn):
    _vendre(conn, "A", 500000, date(2026, 3, 1), 260001)
    _vendre(conn, "B", 200000, date(2026, 4, 1), 260002)
    _vendre(conn, "A", 100000, date(2025, 4, 1), 250001)   # autre année
    lignes = RemiseService(conn).tableau_annee(2026)
    assert [(l.client_nom, l.ca_annuel) for l in lignes] == \
        [("A", 500000), ("B", 200000)]


def test_enregistrement_et_upsert(conn):
    _vendre(conn, "A", 1_000_000, date(2026, 3, 1), 260001)
    service = RemiseService(conn)
    ligne = service.tableau_annee(2026)[0]
    service.enregistrer(ligne.client_id, 2026, ligne.ca_annuel, 2.0, "1er calcul")
    service.enregistrer(ligne.client_id, 2026, ligne.ca_annuel, 3.0, "corrigé")
    lignes = service.tableau_annee(2026)
    assert lignes[0].taux == 3.0
    assert lignes[0].montant == 30000
    assert lignes[0].note == "corrigé"
    nb = conn.execute("SELECT COUNT(*) AS n FROM remises").fetchone()["n"]
    assert nb == 1
