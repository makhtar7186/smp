"""Tests : fusion de fiches clients existantes."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import Client, LigneVente, Remise
from app.repositories.client_repository import ClientRepository
from app.repositories.remise_repository import RemiseRepository
from app.services.client_maintenance_service import ClientMaintenanceService
from app.services.facturation_service import FacturationService
from app.utils.validation import ErreurValidation


class TestFusion:
    def _preparer_doublons(self, conn):
        """Deux fiches pour le même client (faute de saisie sur l'adresse),
        chacune avec ses propres factures."""
        repo = ClientRepository(conn)
        bon = repo.creer(Client(nom="Moussa Ndiaye", adresse="Ourossogui"))
        faute = repo.creer(Client(nom="Moussa Ndiaye", adresse="Ourosogui"))
        service = FacturationService(conn)
        service.enregistrer_facture(
            260001, date(2026, 3, 1), "Moussa Ndiaye", "Ourossogui",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)])
        service.enregistrer_facture(
            260002, date(2026, 3, 2), "Moussa Ndiaye", "Ourosogui",
            [LigneVente(designation="X", quantite=2, prix_unitaire=1000)])
        return bon, faute

    def test_fusion_transfere_les_factures(self, conn):
        bon, faute = self._preparer_doublons(conn)
        service = ClientMaintenanceService(conn)
        resultat = service.fusionner(bon.id, faute.id)
        assert resultat.factures_transferees == 1
        factures = FacturationService(conn).lister_factures()
        assert all(f.client_id == bon.id for f in factures)
        assert len(factures) == 2

    def test_fusion_supprime_le_doublon(self, conn):
        bon, faute = self._preparer_doublons(conn)
        ClientMaintenanceService(conn).fusionner(bon.id, faute.id)
        repo = ClientRepository(conn)
        assert repo.obtenir(faute.id) is None
        assert len(repo.lister_par_nom("MOUSSA NDIAYE")) == 1

    def test_fusion_complete_les_champs_manquants(self, conn):
        repo = ClientRepository(conn)
        cible = repo.creer(Client(nom="A", adresse="X"))
        source = repo.creer(Client(nom="A", adresse="Y", telephone="770000000"))
        ClientMaintenanceService(conn).fusionner(cible.id, source.id)
        maj = repo.obtenir(cible.id)
        assert maj.telephone == "770000000"   # récupéré du doublon

    def test_fusion_reattribue_remises_sans_conflit(self, conn):
        repo = ClientRepository(conn)
        cible = repo.creer(Client(nom="A", adresse="X"))
        source = repo.creer(Client(nom="A", adresse="Y"))
        remises = RemiseRepository(conn)
        remises.enregistrer(Remise(client_id=source.id, annee=2026,
                                   ca_annuel=100000, taux=2.0, montant=2000))
        ClientMaintenanceService(conn).fusionner(cible.id, source.id)
        lignes = remises.lister_annee(2026)
        assert cible.id in lignes and lignes[cible.id].montant == 2000

    def test_fusion_conflit_remise_garde_celle_de_la_cible(self, conn):
        repo = ClientRepository(conn)
        cible = repo.creer(Client(nom="A", adresse="X"))
        source = repo.creer(Client(nom="A", adresse="Y"))
        remises = RemiseRepository(conn)
        remises.enregistrer(Remise(client_id=cible.id, annee=2026,
                                   ca_annuel=500000, taux=3.0, montant=15000))
        remises.enregistrer(Remise(client_id=source.id, annee=2026,
                                   ca_annuel=100000, taux=2.0, montant=2000))
        ClientMaintenanceService(conn).fusionner(cible.id, source.id)
        lignes = remises.lister_annee(2026)
        assert lignes[cible.id].montant == 15000   # celle de la cible conservée

    def test_fusion_avec_soi_meme_refusee(self, conn):
        repo = ClientRepository(conn)
        client = repo.creer(Client(nom="A", adresse="X"))
        with pytest.raises(ErreurValidation):
            ClientMaintenanceService(conn).fusionner(client.id, client.id)


class TestFusionAutomatiqueTelephone:
    """Deux fiches distinctes qui finissent par partager le même numéro
    (une fois normalisé) sont considérées comme la même personne — voir
    ClientMaintenanceService.fusionner_doublon_telephone."""

    def test_fusionne_la_fiche_deja_titulaire_du_numero(self, conn):
        repo = ClientRepository(conn)
        ancien = repo.creer(Client(nom="FALL", adresse="DAKAR", telephone="770000001"))
        edite = repo.creer(Client(nom="FALLOU", adresse="PIKINE", telephone="770000002"))
        edite.telephone = "770000001"  # tentative de faire converger vers le même numéro
        ClientMaintenanceService(conn).fusionner_doublon_telephone(edite)
        repo.modifier(edite)  # n'aurait pas pu s'exécuter sans la fusion (index unique)

        restants = repo.lister()
        assert len(restants) == 1
        assert restants[0].nom == "FALLOU"  # la fiche en cours d'édition survit
        assert restants[0].telephone == "770000001"
        assert repo.obtenir(ancien.id) is None

    def test_normalisation_reconnait_un_meme_numero_formate_differemment(self, conn):
        repo = ClientRepository(conn)
        repo.creer(Client(nom="A", adresse="X", telephone="77 000 00 01"))
        # Le même numéro, saisi sans espaces : doit être reconnu comme identique.
        assert repo.chercher_par_telephone("770000001") is not None

    def test_sans_collision_ne_fusionne_rien(self, conn):
        repo = ClientRepository(conn)
        seul = repo.creer(Client(nom="SEUL", adresse="X", telephone="770000009"))
        ClientMaintenanceService(conn).fusionner_doublon_telephone(seul)
        assert repo.obtenir(seul.id) is not None
        assert len(repo.lister()) == 1
