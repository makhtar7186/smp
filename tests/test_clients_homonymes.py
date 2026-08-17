"""Tests : clients homonymes distingués par adresse."""
from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from app.models import Client, LigneVente
from app.repositories.base_repository import creer_connexion
from app.repositories.client_repository import ClientRepository
from app.services.facturation_service import FacturationService


class TestUnicite:
    def test_meme_nom_adresses_differentes_autorise(self, conn):
        repo = ClientRepository(conn)
        a = repo.creer(Client(nom="Moussa Ndiaye", adresse="Dakar"))
        b = repo.creer(Client(nom="moussa ndiaye", adresse="Thiès"))
        assert a.id != b.id
        assert {c.adresse for c in repo.lister_par_nom("MOUSSA NDIAYE")} == \
            {"DAKAR", "THIÈS"}

    def test_meme_nom_meme_adresse_refuse(self, conn):
        repo = ClientRepository(conn)
        repo.creer(Client(nom="Moussa Ndiaye", adresse="Dakar"))
        with pytest.raises(sqlite3.IntegrityError):
            repo.creer(Client(nom="MOUSSA NDIAYE", adresse="dakar"))


class TestObtenirOuCreer:
    def test_premiere_creation(self, conn):
        repo = ClientRepository(conn)
        client = repo.obtenir_ou_creer("Ablaye Mbaye", adresse="Ourossogui")
        assert client.nom == "ABLAYE MBAYE"
        assert client.adresse == "OUROSSOGUI"

    def test_meme_nom_meme_adresse_reutilise(self, conn):
        repo = ClientRepository(conn)
        a = repo.obtenir_ou_creer("Ablaye Mbaye", adresse="Ourossogui")
        b = repo.obtenir_ou_creer("ablaye mbaye", adresse="OUROSSOGUI")
        assert a.id == b.id

    def test_adresse_absente_est_completee_sans_dupliquer(self, conn):
        """Un client créé sans adresse connue (destination jamais précisée) voit
        sa fiche complétée à la première destination fournie, sans doublon."""
        repo = ClientRepository(conn)
        a = repo.creer(Client(nom="Ablaye Mbaye"))  # adresse encore inconnue
        b = repo.obtenir_ou_creer("Ablaye Mbaye", adresse="Ourossogui")
        assert a.id == b.id
        assert b.adresse == "OUROSSOGUI"
        assert len(repo.lister_par_nom("ABLAYE MBAYE")) == 1

    def test_adresse_deja_connue_et_differente_ne_fusionne_pas(self, conn):
        """Bug signalé : un client dont l'adresse est déjà connue (LOUGA) ne
        doit jamais être fusionné avec un homonyme facturé à une autre
        destination (DIAMNIADIO) — ce sont deux personnes différentes."""
        repo = ClientRepository(conn)
        a = repo.obtenir_ou_creer("Cheikh Oumar", adresse="Louga")
        b = repo.obtenir_ou_creer("Cheikh Oumar", adresse="Diamniadio")
        assert a.id != b.id
        assert {c.adresse for c in repo.lister_par_nom("CHEIKH OUMAR")} == \
            {"LOUGA", "DIAMNIADIO"}

    def test_homonyme_explicite_puis_desambiguise_par_adresse(self, conn):
        """Un vrai homonyme se crée explicitement (page Clients) ; une fois les
        deux fiches connues, l'adresse exacte permet de retrouver la bonne."""
        repo = ClientRepository(conn)
        a = repo.creer(Client(nom="Ablaye Mbaye", adresse="Ourossogui"))
        b = repo.creer(Client(nom="Ablaye Mbaye", adresse="Bakel"))
        assert repo.obtenir_ou_creer("Ablaye Mbaye", adresse="Ourossogui").id == a.id
        assert repo.obtenir_ou_creer("Ablaye Mbaye", adresse="Bakel").id == b.id

    def test_homonymes_adresse_non_reconnue_cree_une_3e_fiche(self, conn):
        """Deux homonymes connus, une destination qui ne correspond à aucun des
        deux : cas ambigu, une nouvelle fiche est créée plutôt que de deviner."""
        repo = ClientRepository(conn)
        repo.creer(Client(nom="Ablaye Mbaye", adresse="Ourossogui"))
        repo.creer(Client(nom="Ablaye Mbaye", adresse="Bakel"))
        c = repo.obtenir_ou_creer("Ablaye Mbaye", adresse="Thies")
        assert len(repo.lister_par_nom("ABLAYE MBAYE")) == 3
        assert c.adresse == "THIES"

    def test_correspond_deja(self, conn):
        repo = ClientRepository(conn)
        assert not repo.correspond_deja("Nouveau Client", "Dakar")
        repo.creer(Client(nom="Nouveau Client", adresse="Dakar"))
        assert repo.correspond_deja("Nouveau Client", "Dakar")
        # Adresse différente d'un homonyme déjà connu : pas une correspondance
        assert not repo.correspond_deja("Nouveau Client", "Thies")

    def test_correspond_deja_adresse_a_completer(self, conn):
        repo = ClientRepository(conn)
        repo.creer(Client(nom="Nouveau Client"))  # adresse encore vide
        assert repo.correspond_deja("Nouveau Client", "Dakar")

    def test_correspond_deja_avec_homonymes_multiples(self, conn):
        repo = ClientRepository(conn)
        repo.creer(Client(nom="Nouveau Client", adresse="Dakar"))
        repo.creer(Client(nom="Nouveau Client", adresse="Bakel"))
        assert repo.correspond_deja("Nouveau Client", "Dakar")
        assert repo.correspond_deja("Nouveau Client", "Bakel")
        assert not repo.correspond_deja("Nouveau Client", "Thies")


class TestFacturationAvecHomonymes:
    def test_facturation_distingue_deux_homonymes_deja_crees(self, conn):
        """Deux clients homonymes créés explicitement (page Clients) gardent des
        historiques de facturation bien séparés dès lors que la destination
        saisie correspond exactement à l'adresse de chacun."""
        repo = ClientRepository(conn)
        dakar = repo.creer(Client(nom="Moussa Ndiaye", adresse="Dakar"))
        thies = repo.creer(Client(nom="Moussa Ndiaye", adresse="Thies"))
        service = FacturationService(conn)
        f1 = service.enregistrer_facture(
            260001, date(2026, 7, 18), "Moussa Ndiaye", "Dakar",
            [LigneVente(designation="SM TAPISSIER 90X190X",
                        quantite=1, prix_unitaire=14130)],
        )
        f2 = service.enregistrer_facture(
            260002, date(2026, 7, 19), "Moussa Ndiaye", "Thies",
            [LigneVente(designation="SM TAPISSIER 90X190X",
                        quantite=2, prix_unitaire=14130)],
        )
        assert f1.client_id == dakar.id
        assert f2.client_id == thies.id
        assert f1.client_id != f2.client_id

    def test_deux_factures_meme_nom_destinations_differentes_ne_fusionnent_pas(
        self, conn
    ):
        """Reproduction du cas signalé au niveau facturation : deux clients au
        même nom, facturés avec des destinations différentes, ne doivent
        jamais être confondus en un seul et même client."""
        service = FacturationService(conn)
        f1 = service.enregistrer_facture(
            260001, date(2026, 7, 18), "Moussa Ndiaye", "Dakar",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        )
        f2 = service.enregistrer_facture(
            260002, date(2026, 7, 19), "Moussa Ndiaye", "Thies",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        )
        assert f1.client_id != f2.client_id
        assert len(ClientRepository(conn).lister_par_nom("MOUSSA NDIAYE")) == 2

    def test_meme_client_reconnu_sur_facture_suivante(self, conn):
        service = FacturationService(conn)
        f1 = service.enregistrer_facture(
            260001, date(2026, 7, 18), "Moussa Ndiaye", "Dakar",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        )
        f2 = service.enregistrer_facture(
            260002, date(2026, 7, 19), "Moussa Ndiaye", "Dakar",
            [LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        )
        assert f1.client_id == f2.client_id
