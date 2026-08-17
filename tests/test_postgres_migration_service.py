"""Tests du scaffolding de migration PostgreSQL. Couvre le comportement
quand psycopg2 est absent (message d'erreur clair, jamais de crash, simulé
via monkeypatch — indépendant de ce qui est réellement installé dans
l'environnement de test) et les parties pures/introspectives (mapping de
types, lecture du schéma SQLite). L'insertion réelle et le rollback contre
une vraie base PostgreSQL ne sont pas couverts ici — ils nécessitent une
instance PostgreSQL réelle (voir docs/DEPLOIEMENT_SERVICE_WINDOWS.md)."""
from __future__ import annotations

import pytest

from app.repositories.base_repository import creer_connexion
from app.services import postgres_migration_service as pms
from app.services.postgres_migration_service import (
    TABLES_MIGREES,
    ConfigPostgres,
    ErreurMigrationPostgres,
    PostgresMigrationService,
)


@pytest.fixture()
def conn(tmp_path):
    return creer_connexion(tmp_path / "test.db")


@pytest.fixture()
def service(conn):
    return PostgresMigrationService(conn)


class TestSansPsycopg2:
    """Simule l'absence de psycopg2 (monkeypatch de `_importer_psycopg2`,
    indépendant de ce qui est réellement installé ici) — vérifie que ça se
    traduit par un message clair, jamais une exception non gérée."""

    @pytest.fixture(autouse=True)
    def _sans_psycopg2(self, monkeypatch):
        def _leve(*_args, **_kwargs):
            raise ErreurMigrationPostgres(
                "Le module psycopg2 n'est pas installé sur ce poste "
                "(pip install psycopg2-binary)."
            )
        monkeypatch.setattr(pms, "_importer_psycopg2", _leve)

    def test_tester_connexion_message_clair(self, service):
        succes, message = service.tester_connexion(ConfigPostgres())
        assert succes is False
        assert "psycopg2" in message

    def test_migrer_rapporte_erreur_globale(self, service):
        rapport = service.migrer(ConfigPostgres(), dry_run=True)
        assert rapport.reussie is False
        assert "psycopg2" in rapport.erreur_globale
        assert rapport.tables == []
        assert rapport.total_lignes == 0


class TestAvecPsycopg2Installe:
    """psycopg2 est bien importable (dépendance réelle depuis
    requirements.txt — voir CLAUDE.md) : une tentative de connexion échoue
    proprement (pas de serveur configuré/accessible dans cet environnement
    de test), sans exception non gérée ni message technique psycopg2 brut
    manquant de contexte."""

    def test_tester_connexion_echoue_proprement_sans_serveur(self, service):
        succes, message = service.tester_connexion(
            ConfigPostgres(hote="127.0.0.1", port=1, base="inexistante"))
        assert succes is False
        assert message  # un message d'erreur psycopg2 lisible, jamais vide


class TestIntrospectionSchema:
    """`_colonnes` doit refléter le schéma SQLite réel (base_repository._SCHEMA)
    sans liste dupliquée à la main — vérifié pour chaque table migrée."""

    def test_toutes_les_tables_migrees_existent_dans_le_schema(self, service):
        for table in TABLES_MIGREES:
            colonnes = service._colonnes(table)
            assert colonnes, f"table {table} introuvable ou vide de colonnes"

    def test_clients_id_est_cle_primaire(self, service):
        colonnes = {nom: pk for nom, _type, pk in service._colonnes("clients")}
        assert colonnes["id"] is True
        assert colonnes["nom"] is False

    def test_factures_contient_les_colonnes_tva_et_remise(self, service):
        """Non-régression : les colonnes ajoutées par les migrations (remise_taux,
        tva_taux) doivent apparaître automatiquement, sans mise à jour manuelle
        de ce service."""
        noms = {nom for nom, _type, _pk in service._colonnes("factures")}
        assert "remise_taux" in noms
        assert "tva_taux" in noms
