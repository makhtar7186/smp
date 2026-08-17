"""Test de non-régression : `machines_actives` (PostgreSQL) sans colonne
`id` faisait échouer TOUTE la synchro descendante — chaque appel à
`GET /referentiels/produits`/`clients` (et la réservation de numéros)
déclenchait le heartbeat (`FacturationService.toucher_activite`), qui levait
une erreur serveur à cause de l'ajout automatique de `RETURNING id` par
`ConnexionPostgres.execute` sur une table sans cette colonne. Voir
CLAUDE.md, section « Numérotation résiliente »."""
from __future__ import annotations

from app.repositories.base_repository import (
    _corriger_machines_actives_postgres,
    _schema_postgresql,
)


class _FauxCursor:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict]:
        return self._rows


class _FauxConnexionPostgres:
    """N'est volontairement PAS un `sqlite3.Connection` : `est_postgresql()`
    la traite donc comme PostgreSQL, exactement comme `ConnexionPostgres`."""

    def __init__(self, colonnes: list[str]) -> None:
        # Liste vide = table absente (aucune ligne dans information_schema).
        self._colonnes = colonnes
        self.instructions_executees: list[str] = []

    def execute(self, sql: str, params=()) -> _FauxCursor:
        self.instructions_executees.append(sql)
        if "information_schema.columns" in sql:
            return _FauxCursor([{"column_name": c} for c in self._colonnes])
        return _FauxCursor([])

    def commit(self) -> None:
        pass


def test_schema_postgresql_machines_actives_a_une_colonne_id() -> None:
    schema = _schema_postgresql()
    debut = schema.index("CREATE TABLE IF NOT EXISTS machines_actives")
    fin = schema.index(";", debut)
    definition = schema[debut:fin]
    assert "SERIAL PRIMARY KEY" in definition
    assert "machine_id TEXT NOT NULL UNIQUE" in definition


def test_corrige_l_ancienne_forme_sans_id() -> None:
    """Table déjà provisionnée SANS colonne `id` (forme boguée d'origine) :
    doit être supprimée pour être recréée ensuite avec le schéma correct."""
    conn = _FauxConnexionPostgres(colonnes=["machine_id", "dernier_vu"])
    _corriger_machines_actives_postgres(conn)
    assert any("DROP TABLE machines_actives" in sql
               for sql in conn.instructions_executees)


def test_ne_touche_pas_une_table_deja_correcte() -> None:
    conn = _FauxConnexionPostgres(colonnes=["id", "machine_id", "dernier_vu"])
    _corriger_machines_actives_postgres(conn)
    assert not any("DROP TABLE" in sql for sql in conn.instructions_executees)


def test_ne_leve_rien_si_la_table_n_existe_pas_encore() -> None:
    conn = _FauxConnexionPostgres(colonnes=[])  # aucune ligne = table absente
    _corriger_machines_actives_postgres(conn)
    assert not any("DROP TABLE" in sql for sql in conn.instructions_executees)
