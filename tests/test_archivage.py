"""Tests : archivage de factures (masque l'historique des ventes ET les
statistiques/dashboards ; sans effet sur les factures clients ni les marges)."""
from __future__ import annotations

from datetime import date

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.stats_service import StatsService


def _peupler(conn) -> FacturationService:
    service = FacturationService(conn)
    service.enregistrer_facture(260001, date(2026, 6, 10), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)])
    service.enregistrer_facture(260002, date(2026, 6, 20), "CLIENT B", "BAKEL",
        [LigneVente(designation="X", quantite=2, prix_unitaire=10000)])
    service.enregistrer_facture(260003, date(2026, 7, 5), "CLIENT A", "DAKAR",
        [LigneVente(designation="X", quantite=1, prix_unitaire=10000)])
    return service


class TestArchivage:
    def test_archiver_masque_de_la_liste_par_defaut(self, conn):
        service = _peupler(conn)
        nb = service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        assert nb == 2
        visibles = service.lister_factures()
        assert len(visibles) == 1
        assert visibles[0].numero == 260003

    def test_archivees_reapparaissent_avec_inclure_archivees(self, conn):
        service = _peupler(conn)
        service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        toutes = service.lister_factures(inclure_archivees=True)
        assert len(toutes) == 3
        archivees = [f for f in toutes if f.archivee]
        assert len(archivees) == 2

    def test_desarchiver_les_reaffiche(self, conn):
        service = _peupler(conn)
        service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        nb = service.desarchiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        assert nb == 2
        assert len(service.lister_factures()) == 3

    def test_archivage_idempotent(self, conn):
        service = _peupler(conn)
        service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        nb_deuxieme_fois = service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        assert nb_deuxieme_fois == 0  # déjà archivées

    def test_archivage_filtre_par_client(self, conn):
        service = _peupler(conn)
        repo_clients = service._clients  # type: ignore[attr-defined]
        client_a = repo_clients.chercher_par_nom_et_adresse("CLIENT A", "DAKAR")
        nb = service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30),
                                      client_id=client_a.id)
        assert nb == 1
        visibles = {f.numero for f in service.lister_factures()}
        assert visibles == {260002, 260003}

    def test_archivage_masque_aussi_les_stats_et_dashboards(self, conn):
        """Une facture archivée disparaît aussi du CA / des dashboards (pas
        seulement de l'historique des ventes)."""
        service = _peupler(conn)
        stats = StatsService(conn)
        ca_avant = stats.kpi_ca_annee(date(2026, 12, 31)).valeur
        assert ca_avant == 40000  # 10000 + 20000 + 10000
        service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        ca_apres = stats.kpi_ca_annee(date(2026, 12, 31)).valeur
        assert ca_apres == 10000  # seule la facture de juillet reste comptée

    def test_archivage_ids_specifiques(self, conn):
        """Archivage d'une sélection précise de factures (page Archive)."""
        service = _peupler(conn)
        toutes = service.lister_factures()
        cible = next(f for f in toutes if f.numero == 260001)
        nb = service.archiver_ids([cible.id])
        assert nb == 1
        visibles = {f.numero for f in service.lister_factures()}
        assert visibles == {260002, 260003}

    def test_desarchivage_ids_specifiques(self, conn):
        service = _peupler(conn)
        toutes = service.lister_factures()
        cible = next(f for f in toutes if f.numero == 260001)
        service.archiver_ids([cible.id])
        nb = service.desarchiver_ids([cible.id])
        assert nb == 1
        assert len(service.lister_factures()) == 3

    def test_archivage_sans_effet_sur_le_ca_annuel_des_remises(self, conn):
        """La page Remises (CA annuel par client) reste inchangée par
        l'archivage — seule sa valeur pour le tableau de bord bouge."""
        service = _peupler(conn)
        stats = StatsService(conn)
        avant = dict((nom, ca) for _cid, nom, _loc, ca in stats.ca_par_client(2026))
        service.archiver_periode(date(2026, 6, 1), date(2026, 6, 30))
        apres = dict((nom, ca) for _cid, nom, _loc, ca in stats.ca_par_client(2026))
        assert avant == apres

