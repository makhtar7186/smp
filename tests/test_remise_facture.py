"""Tests : remise propre à une facture (distincte de la remise annuelle)."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import Facture, LigneVente
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService
from app.utils.validation import ErreurValidation


def test_facture_sans_remise_total_net_egal_total():
    facture = Facture(lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=10000)])
    assert facture.remise_taux == 0.0
    assert facture.remise_montant == 0
    assert facture.total_net == facture.total == 10000


def test_facture_remise_montant_et_total_net():
    facture = Facture(
        remise_taux=10,
        lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
    )
    assert facture.total == 10000
    assert facture.remise_montant == 1000
    assert facture.total_net == 9000


def test_facture_remise_arrondie():
    facture = Facture(
        remise_taux=7.5,
        lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    # 1000 * 7.5 / 100 = 75.0 -> pas d'arrondi surprenant ici, mais on vérifie round()
    assert facture.remise_montant == 75
    assert facture.total_net == 925


def test_enregistrer_facture_persiste_remise_taux(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
        remise_taux=15,
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.remise_taux == 15
    assert relue.remise_montant == 1500
    assert relue.total_net == 8500


def test_enregistrer_facture_sans_remise_par_defaut(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.remise_taux == 0.0


def test_modifier_facture_change_la_remise(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
        remise_taux=10,
    )
    service.modifier_facture(
        facture.id, 260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
        remise_taux=20,
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.remise_taux == 20
    assert relue.remise_montant == 2000


def test_remise_taux_hors_bornes_refusee(conn):
    service = FacturationService(conn)
    with pytest.raises(ErreurValidation):
        service.enregistrer_facture(
            260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
            [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
            remise_taux=150,
        )


def test_remise_taux_negatif_refusee(conn):
    service = FacturationService(conn)
    with pytest.raises(ErreurValidation):
        service.enregistrer_facture(
            260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
            [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
            remise_taux=-5,
        )


def test_remise_taux_100_pourcent_accepte(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
        remise_taux=100,
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.total_net == 0


def test_pdf_facture_avec_remise_ne_leve_pas(tmp_path):
    service = PdfService(tmp_path)
    facture = Facture(
        numero=260001, date_facture=date(2026, 7, 20),
        client_nom="CLIENT A", destination="DAKAR", remise_taux=10,
        lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
    )
    chemin = service.generer_facture(facture)
    assert chemin.exists()


def test_pdf_facture_sans_remise_ne_leve_pas(tmp_path):
    service = PdfService(tmp_path)
    facture = Facture(
        numero=260001, date_facture=date(2026, 7, 20),
        client_nom="CLIENT A", destination="DAKAR",
        lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
    )
    chemin = service.generer_facture(facture)
    assert chemin.exists()
