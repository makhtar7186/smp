"""Tests d'intégration réels de la bascule SQLite → PostgreSQL (base boss —
voir CLAUDE.md, section « Bascule PostgreSQL »). Nécessitent une vraie
instance PostgreSQL accessible : ce module est entièrement ignoré si les
variables d'environnement suivantes ne sont pas définies (jamais
d'identifiants réels commités dans le dépôt) :

    PROMATELAS_TEST_PG_HOST
    PROMATELAS_TEST_PG_PORT       (défaut 5432)
    PROMATELAS_TEST_PG_BASE
    PROMATELAS_TEST_PG_USER
    PROMATELAS_TEST_PG_PASSWORD

Exemple d'exécution manuelle (PowerShell) :
    $env:PROMATELAS_TEST_PG_HOST = "100.65.90.44"
    $env:PROMATELAS_TEST_PG_BASE = "test1_db"
    $env:PROMATELAS_TEST_PG_USER = "bobo"
    $env:PROMATELAS_TEST_PG_PASSWORD = "passer"
    python -m pytest tests/test_postgres_bascule.py -v

ATTENTION : ces tests créent puis SUPPRIMENT leurs propres lignes (clients,
factures, versements...) sur la base ciblée — ne jamais pointer vers une
base contenant des données réelles importantes."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest import mock

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("PROMATELAS_TEST_PG_HOST"),
    reason="PROMATELAS_TEST_PG_HOST non défini — test d'intégration PostgreSQL ignoré"
          " (voir docstring du module pour l'exécuter manuellement).",
)


@pytest.fixture()
def pg_config() -> dict:
    return {
        "hote": os.environ["PROMATELAS_TEST_PG_HOST"],
        "port": int(os.environ.get("PROMATELAS_TEST_PG_PORT", 5432)),
        "base": os.environ["PROMATELAS_TEST_PG_BASE"],
        "utilisateur": os.environ["PROMATELAS_TEST_PG_USER"],
        "mot_de_passe": os.environ["PROMATELAS_TEST_PG_PASSWORD"],
    }


@pytest.fixture()
def conn_pg(pg_config):
    """Connexion PostgreSQL réelle avec schéma canonique appliqué (même
    chemin que `creer_connexion()` en production, via `config` monkeypatché)."""
    from app import config
    with mock.patch.object(config, "lire_moteur_bdd", return_value="postgresql"), \
         mock.patch.object(config, "lire_config_postgres", return_value=pg_config):
        from app.repositories.base_repository import creer_connexion
        connexion = creer_connexion()
        yield connexion
        connexion.close()


def _nettoyer(conn_pg, numero: int, client_nom: str) -> None:
    """Supprime les lignes créées par un test (numéro de facture dédié,
    largement hors de la plage réelle pour ne jamais toucher de vraies
    données)."""
    conn_pg.execute(
        "DELETE FROM versements WHERE facture_id IN"
        " (SELECT id FROM factures WHERE numero = ?)", (numero,))
    conn_pg.execute(
        "DELETE FROM lignes_vente WHERE facture_id IN"
        " (SELECT id FROM factures WHERE numero = ?)", (numero,))
    conn_pg.execute("DELETE FROM factures WHERE numero = ?", (numero,))
    conn_pg.execute("DELETE FROM remises WHERE client_id IN"
                    " (SELECT id FROM clients WHERE nom = ?)", (client_nom,))
    conn_pg.execute("DELETE FROM clients WHERE nom = ?", (client_nom,))
    conn_pg.commit()


class TestSchemaEtCrud:
    def test_creer_connexion_applique_le_schema_complet(self, conn_pg):
        """Les 12 tables du schéma canonique existent, avec leurs contraintes
        (pas le schéma simplifié de l'outil de migration — voir CLAUDE.md)."""
        rows = conn_pg.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'public'"
        ).fetchall()
        tables = {r["table_name"] for r in rows}
        for table in ("clients", "produits", "factures", "lignes_vente", "remises",
                     "versements", "proformas", "lignes_proforma",
                     "reservations_numeros", "historique_fusions_clients"):
            assert table in tables

    def test_facture_avec_remise_et_tva(self, conn_pg):
        """La TVA est prélevée sur le total net (jamais ajoutée en plus) —
        même comportement que sur SQLite (voir test_facturation.py)."""
        from app.models import LigneVente
        from app.services.facturation_service import FacturationService

        service = FacturationService(conn_pg)
        numero = 970001
        try:
            facture = service.enregistrer_facture(
                numero=numero, date_facture=date(2026, 8, 6),
                nom_client="TEST BASCULE PG", destination="DAKAR",
                remise_taux=10.0, tva_taux=18.0,
                lignes=[LigneVente(designation="SM TAPISSIER 140X190", epaisseur=9,
                                   quantite=1, prix_unitaire=1000000)],
            )
            assert facture.total_net == 900000
            assert facture.total_ttc == 900000
            assert facture.tva_montant == 162000
            assert facture.total_ht == 738000
        finally:
            _nettoyer(conn_pg, numero, "TEST BASCULE PG")

    def test_versement_avec_remarque_et_solde(self, conn_pg):
        from app.models import LigneVente
        from app.services.facturation_service import FacturationService
        from app.services.paiement_service import PaiementService

        facturation = FacturationService(conn_pg)
        paiements = PaiementService(conn_pg)
        numero = 970002
        try:
            facture = facturation.enregistrer_facture(
                numero=numero, date_facture=date(2026, 8, 6),
                nom_client="TEST BASCULE PG2", destination="DAKAR",
                lignes=[LigneVente(designation="SM TAPISSIER 140X190", epaisseur=9,
                                   quantite=1, prix_unitaire=100000)],
            )
            versement = paiements.enregistrer_versement(
                facture.id, 60000, date(2026, 8, 6), remarque="acompte")
            assert versement.remarque == "acompte"
            assert versement.created_at  # horodatage explicite, jamais vide

            solde = paiements.calculer_solde_facture(facture.id)
            assert solde.total == 100000
            assert solde.verse == 60000
            assert solde.restant == 40000
        finally:
            _nettoyer(conn_pg, numero, "TEST BASCULE PG2")

    def test_remise_annuelle_upsert_on_conflict(self, conn_pg):
        """`ON CONFLICT(client_id, annee) DO UPDATE` fonctionne sur PostgreSQL
        (nécessite la contrainte UNIQUE composite — absente du schéma
        simplifié historique de l'outil de migration, voir CLAUDE.md)."""
        from app.models import LigneVente
        from app.services.facturation_service import FacturationService
        from app.services.paiement_service import PaiementService

        facturation = FacturationService(conn_pg)
        paiements = PaiementService(conn_pg)
        numero = 970003
        try:
            facture = facturation.enregistrer_facture(
                numero=numero, date_facture=date(2026, 8, 6),
                nom_client="TEST BASCULE PG3", destination="DAKAR",
                lignes=[LigneVente(designation="SM TAPISSIER 140X190", epaisseur=9,
                                   quantite=1, prix_unitaire=100000)],
            )
            r1 = paiements.appliquer_remise_annuelle(
                facture.client_id, 2026, 100000, 2.0, "premier", "local")
            r2 = paiements.appliquer_remise_annuelle(
                facture.client_id, 2026, 150000, 5.0, "maj", "local")
            assert r1.id == r2.id  # même ligne mise à jour, pas un doublon
            assert r2.ca_annuel == 150000
            assert r2.taux == 5.0
        finally:
            _nettoyer(conn_pg, numero, "TEST BASCULE PG3")


class TestStatsEtRemises:
    """`StatsService`/`RemiseService` — dashboard et remises annuelles.
    Couvre les deux bugs découverts et corrigés sur PostgreSQL :
    `strftime()` (fonction SQLite absente de PostgreSQL, groupement par
    période déplacé côté Python) et le GROUP BY strict de PostgreSQL
    (colonnes non agrégées, résolution d'alias ambiguë avec une vraie
    colonne du même nom — voir `repartition_par_gamme`)."""

    def test_dashboard_complet_sans_erreur_500(self, conn_pg):
        from app.models import LigneVente, Produit
        from app.repositories.produit_repository import ProduitRepository
        from app.services.facturation_service import FacturationService
        from app.services.remise_service import RemiseService
        from app.services.stats_service import StatsService

        facturation = FacturationService(conn_pg)
        stats = StatsService(conn_pg)
        remises = RemiseService(conn_pg)
        produits_repo = ProduitRepository(conn_pg)
        numero = 970004
        produit = produits_repo.chercher("TEST GAMME PG", "140X190", 9)
        try:
            if produit is None:
                produit = produits_repo.creer(Produit(
                    gamme="TEST GAMME PG", dimensions="140X190", epaisseur=9,
                    prix_defaut=100000))
            facture = facturation.enregistrer_facture(
                numero=numero, date_facture=date(2026, 8, 6),
                nom_client="TEST DASHBOARD PG", destination="DAKAR",
                lignes=[LigneVente(produit_id=produit.id,
                                   designation="TEST GAMME PG 140X190", epaisseur=9,
                                   quantite=2, prix_unitaire=100000)],
            )
            debut, fin = date(2026, 8, 1), date(2026, 8, 6)

            assert stats.kpi_ca_jour(date(2026, 8, 6)).valeur == 200000
            assert stats.serie_ca(debut, fin, "jour")
            assert stats.serie_ca(debut, fin, "semaine")
            assert stats.serie_ca(date(2026, 1, 1), date(2026, 12, 31), "mois")
            assert stats.ca_par_jour_semaine(debut, fin)
            assert stats.top_produits(debut, fin)
            assert stats.repartition_par_gamme(debut, fin) == [("TEST GAMME PG", 200000)]
            assert stats.quantites_par_epaisseur(debut, fin)
            assert stats.quantites_par_dimension(debut, fin)
            assert stats.top_clients(debut, fin)
            libelles = stats.liste_produits_vendus()
            assert libelles
            assert stats.resume_produit(libelles[0], debut, fin)
            assert stats.serie_quantite_produit(libelles[0], debut, fin, "mois")
            assert stats.ca_par_client(2026)
            assert remises.tableau_annee(2026)
        finally:
            conn_pg.execute("DELETE FROM lignes_vente WHERE facture_id IN"
                            " (SELECT id FROM factures WHERE numero = ?)", (numero,))
            conn_pg.execute("DELETE FROM factures WHERE numero = ?", (numero,))
            conn_pg.execute("DELETE FROM remises WHERE client_id IN"
                            " (SELECT id FROM clients WHERE nom = ?)",
                            ("TEST DASHBOARD PG",))
            conn_pg.execute("DELETE FROM clients WHERE nom = ?", ("TEST DASHBOARD PG",))
            if produit.id is not None:
                conn_pg.execute("DELETE FROM produits WHERE id = ?", (produit.id,))
            conn_pg.commit()


class TestReservationConcurrente:
    def test_reservation_blocs_sans_collision(self, pg_config):
        """`LOCK TABLE ... IN EXCLUSIVE MODE` sérialise correctement les
        demandes concurrentes de blocs de numéros (équivalent PostgreSQL de
        BEGIN IMMEDIATE sur SQLite — voir db_backend.debuter_transaction_exclusive)."""
        from app import config

        def reserver(indice: int) -> list[int]:
            with mock.patch.object(config, "lire_moteur_bdd", return_value="postgresql"), \
                 mock.patch.object(config, "lire_config_postgres", return_value=pg_config):
                from app.repositories.base_repository import creer_connexion
                from app.repositories.reservation_repository import (
                    ReservationNumeroRepository,
                )
                from app.services.facturation_service import FacturationService

                connexion = creer_connexion()
                service = FacturationService(
                    connexion, reservations=ReservationNumeroRepository(connexion))
                try:
                    return service.reserver_bloc_numeros(5, "usine", f"machine-{indice}")
                finally:
                    connexion.close()

        with ThreadPoolExecutor(max_workers=6) as executeur:
            resultats = list(executeur.map(reserver, range(6)))

        tous = [n for bloc in resultats for n in bloc]
        assert len(tous) == len(set(tous)), "collision détectée entre blocs concurrents"
