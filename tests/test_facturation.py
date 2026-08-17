"""Tests du service de facturation : totaux, numérotation, validations."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.utils.validation import ErreurValidation


def _ligne(quantite: int = 2, prix: int = 10000) -> LigneVente:
    return LigneVente(designation="SM TAPISSIER 140X190X", 
                      quantite=quantite, prix_unitaire=prix)


class TestCalculs:
    def test_total_ligne_est_quantite_fois_prix(self):
        assert _ligne(quantite=3, prix=14130).total == 42390

    def test_total_facture_est_somme_des_lignes(self, conn):
        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            numero=260001, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR", lignes=[_ligne(2, 10000), _ligne(5, 7750)],
        )
        assert facture.total == 20000 + 38750

    def test_tva_est_prelevee_sur_le_total_net_jamais_ajoutee(self, conn):
        """Le client paie exactement le total net (marchandise, éventuellement
        remisée) que la TVA soit activée ou non — la TVA est prélevée SUR ce
        montant (nous la reversons sur notre marge), jamais ajoutée en plus
        (le client ne doit jamais payer un supplément à cause de la TVA).
        La TVA (18 %) est désormais obligatoire et appliquée automatiquement,
        jamais un paramètre de saisie."""
        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            numero=260002, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR", lignes=[_ligne(1, 1000000)],
        )
        assert facture.total == 1000000
        assert facture.total_ttc == 1000000  # montant réellement dû, inchangé
        assert facture.tva_montant == 180000
        assert facture.total_ht == 820000
        assert facture.total_ht + facture.tva_montant == facture.total_ttc

    def test_tva_combinee_a_une_remise_reste_sur_le_total_net(self, conn):
        """La TVA se calcule sur le total NET (après remise), pas sur le
        total brut — la remise s'applique en premier."""
        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            numero=260003, date_facture=date(2026, 7, 18), nom_client="TEST",
            destination="DAKAR", lignes=[_ligne(1, 1000000)],
            remise_taux=10.0,
        )
        assert facture.total == 1000000
        assert facture.total_net == 900000       # après remise de 10%
        assert facture.total_ttc == 900000        # inchangé par la TVA
        assert facture.tva_montant == 162000       # 18% de 900000
        assert facture.total_ht == 738000


class TestNumerotation:
    """Numérotation continue : simple incrément du plus grand numéro connu,
    jamais de remise à zéro ni de plafond au changement d'année (ancien
    schéma AANNNN, plafonné à 9999 factures/an, abandonné pour cette raison)."""

    def test_base_vide_commence_a_un(self, conn):
        service = FacturationService(conn)
        assert service.prochain_numero() == 1

    def test_incremente_simplement(self, conn):
        service = FacturationService(conn)
        service.enregistrer_facture(261611, date(2026, 7, 18), "A", "X", [_ligne()])
        assert service.prochain_numero() == 261612

    def test_jamais_de_remise_a_zero_au_changement_d_annee(self, conn):
        service = FacturationService(conn)
        service.enregistrer_facture(261611, date(2026, 12, 30), "A", "X", [_ligne()])
        assert service.prochain_numero() == 261612  # jamais 270001

    def test_numero_existe(self, conn):
        service = FacturationService(conn)
        service.enregistrer_facture(261611, date(2026, 7, 18), "A", "X", [_ligne()])
        assert service.numero_existe(261611)
        assert not service.numero_existe(261612)

    def test_numero_duplique_refuse(self, conn):
        """Il n'existe plus qu'une seule sorte de facture (voir CLAUDE.md) :
        deux factures ne peuvent plus jamais partager un numéro — contrainte
        UNIQUE côté base, garde-fou final contre tout doublon résiduel."""
        import sqlite3

        service = FacturationService(conn)
        service.enregistrer_facture(261611, date(2026, 7, 18), "A", "X",
                                    [_ligne(1, 10000)])
        with pytest.raises(sqlite3.Error):
            service.enregistrer_facture(261611, date(2026, 7, 18), "A", "X",
                                        [_ligne(1, 15000)])


class TestValidations:
    def test_panier_vide_refuse(self, conn):
        service = FacturationService(conn)
        with pytest.raises(ErreurValidation):
            service.enregistrer_facture(260001, date(2026, 7, 18), "A", "X", [])

    def test_client_vide_refuse(self, conn):
        service = FacturationService(conn)
        with pytest.raises(ErreurValidation):
            service.enregistrer_facture(260001, date(2026, 7, 18), "  ", "X",
                                        [_ligne()])

    def test_quantite_nulle_refusee(self, conn):
        service = FacturationService(conn)
        with pytest.raises(ErreurValidation):
            service.enregistrer_facture(260001, date(2026, 7, 18), "A", "X",
                                        [_ligne(quantite=0)])

    def test_prix_negatif_refuse(self, conn):
        service = FacturationService(conn)
        with pytest.raises(ErreurValidation):
            service.enregistrer_facture(260001, date(2026, 7, 18), "A", "X",
                                        [_ligne(prix=-5)])


class TestPersistance:
    def test_facture_relue_identique(self, conn):
        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            260001, date(2026, 7, 18), "ablaye  mbaye", "OUROSSOGUI",
            [_ligne(10, 14130)],
        )
        relue = service.obtenir_facture(facture.id)
        assert relue.numero == 260001
        assert relue.client_nom == "ABLAYE MBAYE"  # nom normalisé
        assert relue.total == 141300
        assert len(relue.lignes) == 1

    def test_telephone_et_matricule_persistes(self, conn):
        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            260001, date(2026, 7, 18), "TEST", "DAKAR", [_ligne()],
            telephone="77 000 00 00", matricule="DK-1234-A",
        )
        relue = service.obtenir_facture(facture.id)
        assert relue.telephone == "77 000 00 00"
        assert relue.matricule == "DK-1234-A"

    def test_filtre_periode_et_client(self, conn):
        service = FacturationService(conn)
        service.enregistrer_facture(260001, date(2026, 1, 10), "A", "X", [_ligne()])
        service.enregistrer_facture(260002, date(2026, 6, 10), "B", "X", [_ligne()])
        assert len(service.lister_factures(date(2026, 5, 1), date(2026, 12, 31))) == 1
        assert len(service.lister_factures()) == 2

    def test_suppression_cascade(self, conn):
        service = FacturationService(conn)
        facture = service.enregistrer_facture(260001, date(2026, 1, 10), "A", "X",
                                              [_ligne()])
        service.supprimer_facture(facture.id)
        assert service.obtenir_facture(facture.id) is None
        reste = conn.execute("SELECT COUNT(*) AS n FROM lignes_vente").fetchone()["n"]
        assert reste == 0

    def test_suppression_restitue_le_stock(self, conn):
        """Supprimer une facture doit rendre le stock comme si les articles
        n'avaient jamais quitté (voir CLAUDE.md, « Gestion de stock »)."""
        from app.services.stock_service import StockService
        stock = StockService(conn)
        produit = stock.creer_produit("BIDON", prix=2500)
        stock.entrer_stock(produit.id, 50)

        service = FacturationService(conn)
        facture = service.enregistrer_facture(
            260001, date(2026, 1, 10), "A", "X",
            [LigneVente(produit_id=produit.id, designation="BIDON",
                       quantite=10, prix_unitaire=2500)])
        assert stock.lister_produits()[0].quantite_stock == 40

        service.supprimer_facture(facture.id)
        assert stock.lister_produits()[0].quantite_stock == 50
