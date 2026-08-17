"""Tests : modification d'une facture déjà enregistrée (sans supprimer/ressaisir)."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.utils.validation import ErreurValidation


def test_modifier_remplace_les_lignes(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)],
    )
    service.modifier_facture(
        facture.id, 260001, date(2026, 7, 20), "CLIENT A", "DAKAR",
        [LigneVente(designation="Y", quantite=2, prix_unitaire=5000)],
    )
    relue = service.obtenir_facture(facture.id)
    assert len(relue.lignes) == 1
    assert relue.lignes[0].designation == "Y"
    assert relue.total == 10000
    # L'id reste le même : aucune nouvelle facture créée
    assert len(service.lister_factures()) == 1


def test_modifier_change_le_numero(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "A", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    service.modifier_facture(
        facture.id, 260099, date(2026, 7, 20), "A", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.numero == 260099


def test_modifier_change_le_client(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "Client Errone", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    service.modifier_facture(
        facture.id, 260001, date(2026, 7, 20), "Bon Client", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.client_nom == "BON CLIENT"


def test_modifier_change_telephone_et_matricule(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "A", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        telephone="77 000 00 00", matricule="DK-1234-A",
    )
    service.modifier_facture(
        facture.id, 260001, date(2026, 7, 20), "A", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        telephone="78 111 11 11", matricule="DK-9999-Z",
    )
    relue = service.obtenir_facture(facture.id)
    assert relue.telephone == "78 111 11 11"
    assert relue.matricule == "DK-9999-Z"


def test_modifier_panier_vide_refuse(conn):
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 7, 20), "A", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    with pytest.raises(ErreurValidation):
        service.modifier_facture(facture.id, 260001, date(2026, 7, 20), "A", "X", [])
    # La facture d'origine n'a pas été touchée
    assert len(service.obtenir_facture(facture.id).lignes) == 1


def test_modifier_conserve_larchivage(conn):
    """Modifier une facture archivée ne la désarchive pas."""
    service = FacturationService(conn)
    facture = service.enregistrer_facture(
        260001, date(2026, 6, 10), "A", "X",
        [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
    )
    service.archiver_ids([facture.id])
    service.modifier_facture(
        facture.id, 260001, date(2026, 6, 10), "A", "X",
        [LigneVente(designation="X", quantite=2, prix_unitaire=1000)],
    )
    toutes = service.lister_factures(inclure_archivees=True)
    assert toutes[0].archivee is True
