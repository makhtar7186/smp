"""Tests de la sauvegarde PostgreSQL → SQLite. Même limitation que
test_postgres_migration_service.py : pas de vraie instance PostgreSQL ici,
donc seulement le comportement sans psycopg2 et la logique de
planification (`SqliteBackupWorker`), pas l'insertion réelle."""
from __future__ import annotations

import pytest

from app import config
from app.services import sqlite_backup_service as sbs
from app.services.postgres_migration_service import ConfigPostgres, ErreurMigrationPostgres
from app.services.sqlite_backup_service import SqliteBackupService, SqliteBackupWorker


@pytest.fixture(autouse=True)
def _isoler_dossier_data(tmp_path, monkeypatch):
    """Jamais écrire dans le vrai app/data/ du poste de dev pendant les
    tests (settings.json, journal de sauvegarde) — même convention que
    test_api_management.py."""
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")


class TestSansPsycopg2:
    @pytest.fixture(autouse=True)
    def _sans_psycopg2(self, monkeypatch):
        def _leve(*_args, **_kwargs):
            raise ErreurMigrationPostgres(
                "Le module psycopg2 n'est pas installé sur ce poste "
                "(pip install psycopg2-binary)."
            )
        monkeypatch.setattr(sbs, "_importer_psycopg2", _leve)

    def test_sauvegarder_rapporte_erreur_claire(self, tmp_path):
        rapport = SqliteBackupService().sauvegarder(ConfigPostgres(), tmp_path / "backup.db")
        assert rapport.reussie is False
        assert "psycopg2" in rapport.erreur_globale
        assert rapport.tables == []
        assert rapport.total_lignes == 0
        # Aucun fichier SQLite ne doit être créé si la connexion PostgreSQL
        # n'a jamais pu être tentée sérieusement (échec avant même
        # `creer_connexion`).
        assert not (tmp_path / "backup.db").exists()


class TestWorkerSansPostgres:
    """`_cycle()` doit être un no-op silencieux tant que la base boss n'est
    pas basculée sur PostgreSQL — jamais tenter de se connecter."""

    def test_cycle_noop_si_moteur_sqlite(self, monkeypatch, tmp_path):
        monkeypatch.setenv("PROMATELAS_MOTEUR_BDD", "sqlite")
        worker = SqliteBackupWorker()

        appelé = {"valeur": False}

        def _echoue_si_appelé(*_a, **_kw):
            appelé["valeur"] = True
            raise AssertionError("sauvegarder() ne doit pas être appelé en moteur sqlite")

        monkeypatch.setattr(SqliteBackupService, "sauvegarder", _echoue_si_appelé)
        worker._cycle()
        assert appelé["valeur"] is False

    def test_cycle_ne_leve_jamais_meme_en_erreur(self, monkeypatch):
        """`_boucle()` capture toute exception (voir CLAUDE.md, « Un thread
        démon ne doit jamais mourir ») — ici on vérifie juste que `_cycle()`
        seul, appelé en moteur postgresql sans psycopg2, produit un rapport
        d'échec plutôt que de lever."""
        monkeypatch.setenv("PROMATELAS_MOTEUR_BDD", "postgresql")

        def _leve(*_args, **_kwargs):
            raise ErreurMigrationPostgres("psycopg2 absent")

        monkeypatch.setattr(sbs, "_importer_psycopg2", _leve)
        worker = SqliteBackupWorker()
        worker._cycle()  # ne doit lever aucune exception
