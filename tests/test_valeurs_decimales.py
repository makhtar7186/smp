"""Tests : quantité décimale (ex. 2,5) en facturation."""
from __future__ import annotations

from datetime import date

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.utils.formatting import format_nombre
from app.utils.validation import valider_nombre_positif


class TestValidation:
    def test_entier_reste_entier(self):
        assert valider_nombre_positif("9") == 9
        assert isinstance(valider_nombre_positif("9"), int)

    def test_decimale_virgule_acceptee(self):
        assert valider_nombre_positif("2,5") == 2.5

    def test_decimale_point_acceptee(self):
        assert valider_nombre_positif("2.5") == 2.5

    def test_strict_refuse_zero(self):
        import pytest
        from app.utils.validation import ErreurValidation
        with pytest.raises(ErreurValidation):
            valider_nombre_positif("0", strict=True)


class TestFormatNombre:
    def test_entier_sans_decimale(self):
        assert format_nombre(9) == "9"
        assert format_nombre(9.0) == "9"

    def test_decimale_avec_virgule(self):
        assert format_nombre(2.5) == "2,5"


class TestFacturationDecimale:
    def test_ligne_avec_quantite_decimale(self, conn):
        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            260001, date(2026, 7, 20), "CLIENT TEST", "DAKAR",
            [LigneVente(designation="SM MOUSSE 90X190X",
                        quantite=1.5, prix_unitaire=10000)],
        )
        relue = service.obtenir_facture(facture.id)
        ligne = relue.lignes[0]
        assert ligne.quantite == 1.5
        assert ligne.total == 15000  # 1.5 × 10000, arrondi

    def test_produit_auto_cree_conserve_le_prix_pratique(self, conn):
        from app.repositories.produit_repository import ProduitRepository
        service = FacturationService(conn)
        service.enregistrer_facture(
            260001, date(2026, 7, 20), "A", "X",
            [LigneVente(designation="SM MOUSSE 90X190X",
                        quantite=1, prix_unitaire=8000)],
        )
        produit = ProduitRepository(conn).chercher("SM MOUSSE 90X190X", "", "")
        assert produit is not None
        assert produit.prix == 8000
