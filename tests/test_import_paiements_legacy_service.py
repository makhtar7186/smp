"""Tests de ImporterPaiementsLegacyService : import ponctuel d'un résumé de
paiements historiques (facture « coquille » + versement), sans jamais
toucher au catalogue produits ni au stock — voir CLAUDE.md, section « Import
des paiements historiques »."""
from __future__ import annotations

from datetime import date

from app.services.facturation_service import FacturationService
from app.services.import_paiements_legacy_service import (
    ImporterPaiementsLegacyService,
    LigneImportLegacy,
)
from app.services.paiement_service import PaiementService


def _ligne(numero=1, montant=50000, versement=30000, client="ANCIEN CLIENT 001",
          commentaire="") -> LigneImportLegacy:
    return LigneImportLegacy(
        numero=numero, date_facture=date(2024, 1, 15), client_nom=client,
        montant=montant, versement=versement, commentaire=commentaire,
    )


class TestImportNominal:
    def test_cree_facture_et_versement(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([_ligne()])
        assert rapport.importees == 1
        assert rapport.ignorees == []

        paiements = PaiementService(conn)
        facturation = FacturationService(conn)
        entete = facturation.chercher_facture_par_numero(1)
        assert entete is not None
        facture = facturation.obtenir_facture(entete.id)
        assert facture.client_nom == "ANCIEN CLIENT 001"
        assert facture.total == 50000
        assert facture.tva_taux == 0

        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.total == 50000
        assert solde.verse == 30000
        assert solde.restant == 20000

    def test_versement_nul_nenregistre_aucun_versement(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        service.importer([_ligne(numero=2, versement=0)])
        facture = FacturationService(conn).chercher_facture_par_numero(2)
        solde = PaiementService(conn).calculer_solde_facture(facture.id)
        assert solde.verse == 0
        assert solde.restant == 50000

    def test_naffecte_ni_produit_ni_stock(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        service.importer([_ligne(numero=3)])
        assert conn.execute("SELECT COUNT(*) AS n FROM mouvements_stock").fetchone()["n"] == 0
        # Un seul produit "coquille" partagé, jamais un par facture importée.
        service.importer([_ligne(numero=4)])
        nb_produits = conn.execute("SELECT COUNT(*) AS n FROM produits").fetchone()["n"]
        assert nb_produits == 0  # produit_id jamais rattaché : aucune ligne créée dans "produits"

    def test_meme_client_reutilise_la_fiche(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        service.importer([_ligne(numero=5, client="CLIENT X"),
                          _ligne(numero=6, client="CLIENT X")])
        nb_clients = conn.execute(
            "SELECT COUNT(*) AS n FROM clients WHERE nom = 'CLIENT X'").fetchone()["n"]
        assert nb_clients == 1


class TestLignesIgnorees:
    def test_numero_deja_utilise_par_une_facture_reelle_est_ignore(self, conn):
        facturation = FacturationService(conn)
        from app.models import LigneVente
        facturation.enregistrer_facture(
            numero=5, date_facture=date(2026, 1, 1), nom_client="A",
            destination="X", lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)])

        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([_ligne(numero=1), _ligne(numero=5)])
        assert rapport.importees == 1
        assert len(rapport.ignorees) == 1
        assert rapport.ignorees[0].numero == 5
        assert rapport.ignorees[0].raison == "numero_deja_utilise"

    def test_numero_superieur_au_plus_haut_numero_reel_est_accepte(self, conn):
        """Bug corrigé : la numérotation de l'ancien système et celle de ce
        système démarrent souvent chacune à des petits nombres proches — un
        numéro legacy plus grand que le numéro réel le plus haut doit être
        importé normalement, pas rejeté (voir CLAUDE.md)."""
        facturation = FacturationService(conn)
        from app.models import LigneVente
        facturation.enregistrer_facture(
            numero=1, date_facture=date(2026, 1, 1), nom_client="A",
            destination="X", lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)])

        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([_ligne(numero=29), _ligne(numero=38)])
        assert rapport.importees == 2
        assert rapport.ignorees == []

    def test_numero_deja_importe_dans_le_meme_lot_est_ignore(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([_ligne(numero=1), _ligne(numero=1)])
        assert rapport.importees == 1
        assert len(rapport.ignorees) == 1
        assert rapport.ignorees[0].raison == "numero_deja_utilise"

    def test_numero_invalide_est_ignore(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([_ligne(numero=0), _ligne(numero=-5)])
        assert rapport.importees == 0
        assert all(l.raison == "numero_invalide" for l in rapport.ignorees)

    def test_montant_invalide_est_ignore(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([_ligne(numero=1, montant=0)])
        assert rapport.importees == 0
        assert rapport.ignorees[0].raison == "montant_invalide"

    def test_reste_du_lot_traite_malgre_une_ligne_ignoree(self, conn):
        service = ImporterPaiementsLegacyService(conn)
        rapport = service.importer([
            _ligne(numero=1, montant=0),  # ignorée
            _ligne(numero=2),             # importée
        ])
        assert rapport.importees == 1
        assert len(rapport.ignorees) == 1
