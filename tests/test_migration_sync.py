"""Tests de la migration additive de l'architecture offline-first : nouvelles
tables de synchronisation et colonne clients.modifie_le."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.repositories.base_repository import creer_connexion

_NOUVELLES_TABLES = (
    "reservations_numeros",
    "historique_fusions_clients",
    "numeros_reserves",
    "queue_synchronisation",
)


def test_nouvelles_tables_presentes(conn) -> None:
    noms = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    for table in _NOUVELLES_TABLES:
        assert table in noms


def test_colonne_modifie_le_presente_sur_clients(conn) -> None:
    colonnes = {r[1] for r in conn.execute("PRAGMA table_info(clients)")}
    assert "modifie_le" in colonnes


def test_migration_idempotente(tmp_path: Path) -> None:
    """Ouvrir deux fois la même base de fichier ne doit ni échouer ni dupliquer
    de colonnes/tables."""
    chemin_db = tmp_path / "test.db"
    conn1 = creer_connexion(chemin_db)
    conn1.close()
    conn2 = creer_connexion(chemin_db)
    colonnes = {r[1] for r in conn2.execute("PRAGMA table_info(clients)")}
    assert "modifie_le" in colonnes
    conn2.close()


