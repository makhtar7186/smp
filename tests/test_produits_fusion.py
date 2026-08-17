"""Tests : fusion de produits en doublon (typo de saisie sur nom/valeur)."""
from __future__ import annotations

from datetime import date

from app.models import LigneVente, Produit
from app.repositories.produit_repository import ProduitRepository
from app.services.facturation_service import FacturationService


def test_fusion_reattribue_les_lignes_de_vente(conn):
    repo = ProduitRepository(conn)
    bon = repo.creer(Produit(nom="SM TAPISSIER", type_option="dimension",
                             valeur_option="90X190", prix=14130))
    doublon = repo.creer(Produit(nom="SM  TAPISSIER", type_option="dimension",
                                 valeur_option="90X190", prix=14130))
    service = FacturationService(conn)
    service.enregistrer_facture(
        260001, date(2026, 7, 20), "A", "X",
        [LigneVente(produit_id=doublon.id, designation="SM  TAPISSIER 90X190X",
                    quantite=2, prix_unitaire=14130)],
    )
    nb = repo.fusionner(bon.id, doublon.id)
    assert nb == 1
    ligne = conn.execute(
        "SELECT produit_id FROM lignes_vente"
    ).fetchone()
    assert ligne["produit_id"] == bon.id


def test_fusion_supprime_le_doublon(conn):
    repo = ProduitRepository(conn)
    bon = repo.creer(Produit(nom="SM HOUSSE", type_option="dimension", valeur_option="140X190"))
    doublon = repo.creer(Produit(nom="SM HOUSSE", type_option="litrage", valeur_option="140X190"))
    repo.fusionner(bon.id, doublon.id)
    assert repo.obtenir(doublon.id) is None
    assert repo.obtenir(bon.id) is not None


def test_fusion_sans_lignes_associees(conn):
    repo = ProduitRepository(conn)
    bon = repo.creer(Produit(nom="A", type_option="dimension", valeur_option="X"))
    doublon = repo.creer(Produit(nom="A", type_option="litrage", valeur_option="X"))
    nb = repo.fusionner(bon.id, doublon.id)
    assert nb == 0
    assert repo.obtenir(doublon.id) is None
