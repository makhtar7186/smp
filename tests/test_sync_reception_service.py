"""Tests de SyncReceptionService (boss) : rejeu fidèle des opérations de la
file de synchronisation via des clés naturelles, fusion de client avec/sans
conflit détecté et journalisée. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import json
from datetime import date

import pytest

from app.models import Client, LigneVente, Produit
from app.repositories.client_repository import ClientRepository
from app.repositories.historique_fusion_repository import HistoriqueFusionRepository
from app.repositories.produit_repository import ProduitRepository
from app.services.facturation_service import FacturationService
from app.services.sync_reception_service import SyncReceptionService
from app.sync.payloads import (
    cle_correlation_facture,
    cle_correlation_fusion,
    construire_payload_facture,
    construire_payload_fusion_client,
)
from app.utils.validation import ErreurMetier


def _ligne() -> LigneVente:
    return LigneVente(designation="SM TAPISSIER 140X190X",
                      quantite=2, prix_unitaire=10000)


class TestRejeuFacture:
    def test_creation_facture_resout_client_et_produit_en_autorite(self, conn) -> None:
        service = SyncReceptionService(conn)
        payload = construire_payload_facture(
            260001, date(2026, 3, 1), "NOUVEAU CLIENT", "DAKAR", [_ligne()], "", 0.0)
        resultat = service.rejouer("creation_facture", cle_correlation_facture(260001),
                                   payload)
        assert resultat["statut"] == "ok"
        facturation = FacturationService(conn)
        facture = facturation.obtenir_facture(resultat["id_correlation_serveur"])
        assert facture.client_nom == "NOUVEAU CLIENT"
        assert facture.lignes[0].produit_id is not None  # produit auto-créé

    def test_modification_facture_retrouve_id_par_numero(self, conn) -> None:
        facturation = FacturationService(conn)
        facture = facturation.enregistrer_facture(
            numero=260002, date_facture=date(2026, 3, 1), nom_client="AVANT",
            destination="DAKAR", lignes=[_ligne()])

        service = SyncReceptionService(conn)
        payload = construire_payload_facture(
            260002, date(2026, 3, 1), "APRES", "DAKAR", [_ligne()], "", 0.0)
        resultat = service.rejouer("modification_facture",
                                   cle_correlation_facture(260002), payload)
        assert resultat["id_correlation_serveur"] == facture.id
        assert facturation.obtenir_facture(facture.id).client_nom == "APRES"

    def test_modification_facture_introuvable_leve_erreur_metier(self, conn) -> None:
        service = SyncReceptionService(conn)
        payload = construire_payload_facture(
            269999, date(2026, 3, 1), "X", "DAKAR", [_ligne()], "", 0.0)
        with pytest.raises(ErreurMetier):
            service.rejouer("modification_facture", cle_correlation_facture(269999),
                            payload)

    def test_suppression_facture_retrouve_par_numero_et_supprime(self, conn) -> None:
        facturation = FacturationService(conn)
        facture = facturation.enregistrer_facture(
            numero=260003, date_facture=date(2026, 3, 1), nom_client="X",
            destination="DAKAR", lignes=[_ligne()])

        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "suppression_facture", cle_correlation_facture(260003), {"numero": 260003})
        assert resultat["id_correlation_serveur"] == facture.id
        assert facturation.obtenir_facture(facture.id) is None

    def test_suppression_facture_deja_absente_ne_leve_rien(self, conn) -> None:
        """Créée puis supprimée sur la machine de facturation avant d'avoir
        jamais atteint le serveur : rien à supprimer, ce n'est pas une
        erreur — le résultat voulu (elle n'existe pas) est déjà atteint."""
        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "suppression_facture", cle_correlation_facture(269998), {"numero": 269998})
        assert resultat["statut"] == "ok"
        assert resultat["id_correlation_serveur"] is None

    def test_suppression_facture_restitue_le_stock(self, conn) -> None:
        from app.services.stock_service import StockService
        stock = StockService(conn)
        produit = stock.creer_produit("BIDON", prix=2500)
        stock.entrer_stock(produit.id, 50)
        facturation = FacturationService(conn)
        facture = facturation.enregistrer_facture(
            numero=260004, date_facture=date(2026, 3, 1), nom_client="X",
            destination="DAKAR",
            lignes=[LigneVente(produit_id=produit.id, designation="BIDON",
                               quantite=10, prix_unitaire=2500)])
        assert stock.lister_produits()[0].quantite_stock == 40

        service = SyncReceptionService(conn)
        service.rejouer("suppression_facture", cle_correlation_facture(260004),
                        {"numero": 260004})
        assert stock.lister_produits()[0].quantite_stock == 50


class TestRejeuCreationsAutonomes:
    def test_creation_client(self, conn) -> None:
        service = SyncReceptionService(conn)
        resultat = service.rejouer("creation_client", "creation_client:X|DAKAR",
                                   {"nom": "X", "telephone": "77", "adresse": "DAKAR"})
        client = ClientRepository(conn).obtenir(resultat["id_correlation_serveur"])
        assert client.nom == "X"
        assert client.telephone == "77"

    def test_creation_produit(self, conn) -> None:
        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "creation_produit", "creation_produit:NOM|DIMENSION|140X190",
            {"nom": "NOM", "type_option": "dimension", "valeur_option": "140X190",
             "prix": 5000})
        produit = ProduitRepository(conn).obtenir(resultat["id_correlation_serveur"])
        assert produit.nom == "NOM"
        assert produit.prix == 5000

    def test_modification_produit_retrouve_par_ancienne_identite(self, conn) -> None:
        produits = ProduitRepository(conn)
        produit = produits.creer(Produit(nom="BIDON", type_option="litrage",
                                         valeur_option="5L", prix=2500))
        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "modification_produit", "modification_produit:BIDON|LITRAGE|5L",
            {"ancien_nom": "BIDON", "ancien_type_option": "litrage",
             "ancien_valeur_option": "5L", "nom": "BIDON", "type_option": "litrage",
             "valeur_option": "5L", "prix": 3000, "actif": True})
        assert resultat["id_correlation_serveur"] == produit.id
        assert produits.obtenir(produit.id).prix == 3000

    def test_modification_produit_introuvable_le_cree(self, conn) -> None:
        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "modification_produit", "modification_produit:X|Y|Z",
            {"ancien_nom": "X", "ancien_type_option": "", "ancien_valeur_option": "",
             "nom": "NOUVEAU", "type_option": "", "valeur_option": "",
             "prix": 1000, "actif": True})
        produit = ProduitRepository(conn).obtenir(resultat["id_correlation_serveur"])
        assert produit.nom == "NOUVEAU"

    def test_modification_client_retrouve_par_ancienne_identite(self, conn) -> None:
        clients = ClientRepository(conn)
        client = clients.creer(Client(nom="AVANT", adresse="DAKAR"))
        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "modification_client", "modification_client:AVANT|DAKAR",
            {"ancien_nom": "AVANT", "ancien_adresse": "DAKAR",
             "nom": "APRES", "telephone": "770000000", "adresse": "DAKAR"})
        assert resultat["id_correlation_serveur"] == client.id
        maj = clients.obtenir(client.id)
        assert maj.nom == "APRES"
        assert maj.telephone == "770000000"

    def test_modification_client_fusionne_si_telephone_deja_pris(self, conn) -> None:
        """Le téléphone visé appartient déjà à un AUTRE client côté serveur —
        la modification doit fusionner plutôt que heurter la contrainte
        d'unicité (voir ClientMaintenanceService.fusionner_doublon_telephone)."""
        clients = ClientRepository(conn)
        deja_titulaire = clients.creer(
            Client(nom="TITULAIRE", adresse="THIES", telephone="770000001"))
        a_modifier = clients.creer(Client(nom="AVANT", adresse="DAKAR"))
        service = SyncReceptionService(conn)
        resultat = service.rejouer(
            "modification_client", "modification_client:AVANT|DAKAR",
            {"ancien_nom": "AVANT", "ancien_adresse": "DAKAR",
             "nom": "APRES", "telephone": "770000001", "adresse": "DAKAR"})
        assert resultat["id_correlation_serveur"] == a_modifier.id
        assert clients.obtenir(deja_titulaire.id) is None  # fusionné, supprimé
        maj = clients.obtenir(a_modifier.id)
        assert maj.telephone == "770000001"
        assert maj.nom == "APRES"


class TestRejeuFusion:
    def test_fusion_sans_conflit(self, conn) -> None:
        clients = ClientRepository(conn)
        cible = clients.creer(Client(nom="CIBLE", adresse="DAKAR"))
        source = clients.creer(Client(nom="SOURCE", adresse="THIES"))

        service = SyncReceptionService(conn)
        payload = construire_payload_fusion_client(cible, source)
        cle = cle_correlation_fusion(cible, source)
        resultat = service.rejouer("fusion_client", cle, payload, machine_id="comptoir-1",
                                   cree_le="2026-03-01T10:00:00")
        assert resultat["statut"] == "ok"

        historique = HistoriqueFusionRepository(conn).lister()
        assert len(historique) == 1
        assert historique[0].conflit_detecte is False
        assert historique[0].machine_origine == "comptoir-1"
        assert clients.obtenir(source.id) is None  # doublon supprimé

    def test_fusion_avec_conflit_detecte_et_journalisee(self, conn) -> None:
        clients = ClientRepository(conn)
        cible = clients.creer(Client(nom="CIBLE2", adresse="DAKAR"))
        source = clients.creer(Client(nom="SOURCE2", adresse="THIES"))

        service = SyncReceptionService(conn)
        payload = construire_payload_fusion_client(cible, source)
        # Simule une modification serveur survenue APRES la décision locale de
        # fusion (avant le rejeu) : le modifie_le connu localement est obsolète.
        payload["cible_modifie_le_connu"] = "2020-01-01T00:00:00"

        resultat = service.rejouer(
            "fusion_client", cle_correlation_fusion(cible, source), payload,
            machine_id="comptoir-1", cree_le="2026-03-01T10:00:00")
        assert resultat["statut"] == "ok"  # appliquée malgré le conflit

        historique = HistoriqueFusionRepository(conn).lister()
        entree = historique[0]
        assert entree.conflit_detecte is True
        avant = json.loads(entree.etat_avant_json)
        assert avant["cible"]["nom"] == "CIBLE2"
        apres = json.loads(entree.etat_apres_json)
        assert apres["cible"]["nom"] == "CIBLE2"

    def test_fusion_client_introuvable_leve_erreur_metier(self, conn) -> None:
        service = SyncReceptionService(conn)
        fantome = Client(nom="FANTOME", adresse="NULLEPART", modifie_le="")
        with pytest.raises(ErreurMetier):
            service.rejouer(
                "fusion_client",
                cle_correlation_fusion(fantome, fantome),
                construire_payload_fusion_client(fantome, fantome))
