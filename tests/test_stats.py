"""Tests du service de statistiques."""
from __future__ import annotations

from datetime import date

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.stats_service import StatsService


def _peupler(conn):
    """Trois factures : deux en juillet 2026, une en juin 2026."""
    service = FacturationService(conn)
    service.enregistrer_facture(261601, date(2026, 6, 15), "CLIENT A", "DAKAR", [
        LigneVente(designation="SM TAPISSIER 90X190X", 
                   quantite=10, prix_unitaire=14130),
    ])
    service.enregistrer_facture(261610, date(2026, 7, 17), "CLIENT B", "BAKEL", [
        LigneVente(designation="SM RESSORT 180X190X", 
                   quantite=2, prix_unitaire=78000),
    ])
    service.enregistrer_facture(261611, date(2026, 7, 18), "CLIENT A", "DAKAR", [
        LigneVente(designation="SM TAPISSIER 90X190X", 
                   quantite=5, prix_unitaire=14130),
        LigneVente(designation="SM HOUSSE 140X190X", 
                   quantite=4, prix_unitaire=10850),
    ])
    return service


def test_kpi_ca_jour(conn):
    _peupler(conn)
    kpi = StatsService(conn).kpi_ca_jour(date(2026, 7, 18))
    assert kpi.valeur == 5 * 14130 + 4 * 10850
    assert kpi.precedent == 2 * 78000          # la veille (17/07)
    assert kpi.variation_pct is not None


def test_kpi_ca_mois_et_precedent(conn):
    _peupler(conn)
    kpi = StatsService(conn).kpi_ca_mois(date(2026, 7, 31))
    assert kpi.valeur == 2 * 78000 + 5 * 14130 + 4 * 10850
    assert kpi.precedent == 10 * 14130         # juin


def test_kpi_ca_annee_sans_reference(conn):
    _peupler(conn)
    kpi = StatsService(conn).kpi_ca_annee(date(2026, 12, 31))
    assert kpi.precedent == 0
    assert kpi.variation_pct is None


def test_panier_moyen(conn):
    _peupler(conn)
    stats = StatsService(conn)
    ca_total = stats.kpi_ca_annee(date(2026, 12, 31)).valeur
    assert stats.panier_moyen_annee(date(2026, 12, 31)) == round(ca_total / 3)


def test_top_produits_par_quantite_et_ca(conn):
    _peupler(conn)
    stats = StatsService(conn)
    top_quantite = stats.top_produits(date(2026, 1, 1), date(2026, 12, 31), "quantite")
    assert top_quantite[0] == ("SM TAPISSIER 90X190X", 15)
    top_ca = stats.top_produits(date(2026, 1, 1), date(2026, 12, 31), "ca")
    assert top_ca[0][0] == "SM TAPISSIER 90X190X"   # 15 × 14130 = 211950


def test_serie_ca_par_mois(conn):
    _peupler(conn)
    serie = StatsService(conn).serie_ca(date(2026, 1, 1), date(2026, 12, 31), "mois")
    assert dict(serie)["2026-06"] == 141300
    assert len(serie) == 2


def test_ca_par_client(conn):
    _peupler(conn)
    resultat = StatsService(conn).ca_par_client(2026)
    noms = [nom for _, nom, _localite, _ca in resultat]
    assert noms[0] == "CLIENT A"               # plus gros CA en premier


def test_periode_vide(conn):
    _peupler(conn)
    stats = StatsService(conn)
    assert stats.top_produits(date(2020, 1, 1), date(2020, 12, 31)) == []
    assert stats.serie_ca(date(2020, 1, 1), date(2020, 12, 31)) == []
