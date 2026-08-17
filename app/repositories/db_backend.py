"""Adaptation PostgreSQL pour la couche `repositories/` — permet à la base
« boss » (app principale + serveur API) de fonctionner sur PostgreSQL plutôt
que SQLite, réglage basculable (`config.lire_moteur_bdd()`), sans toucher au
SQL déjà écrit dans les repositories. Les caches locaux des machines de
facturation restent TOUJOURS SQLite (offline-first — voir CLAUDE.md), donc
`creer_connexion(chemin_db=...)` avec un chemin explicite reste inchangée ;
seul l'appel sans argument (`creer_connexion()`, la base par défaut) est
sensible au moteur configuré.

`ConnexionPostgres`/`CursorPostgres` répliquent le sous-ensemble de
l'interface `sqlite3.Connection`/`sqlite3.Cursor` réellement utilisé par les
repositories :
- `.execute(sql, params)` — traduit les `?` en `%s`, et complète
  automatiquement les `INSERT` d'un `RETURNING id` pour que `cur.lastrowid`
  continue de fonctionner tel quel (psycopg2 n'a pas de `lastrowid` natif).
- `.executescript(sql)` — exécution multi-instructions (schéma), psycopg2 le
  supporte nativement.
- `.commit()`/`.rollback()`/`.close()` — passthrough direct.
- Curseur en accès dict (`row["colonne"]`), via `psycopg2.extras.RealDictCursor`
  — même API que `sqlite3.Row` utilisée partout dans les repositories.

`psycopg2` est importé paresseusement : aucune dépendance ajoutée pour qui
n'utilise jamais PostgreSQL (voir requirements.txt)."""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Sequence

_MOTS_INSERT = re.compile(r"^\s*INSERT\s+INTO", re.IGNORECASE)
_A_DEJA_RETURNING = re.compile(r"RETURNING\b", re.IGNORECASE)


class ErreurConnexionPostgres(Exception):
    """psycopg2 indisponible ou connexion PostgreSQL impossible."""


def _importer_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError as exc:
        raise ErreurConnexionPostgres(
            "Le module psycopg2 n'est pas installé sur ce poste "
            "(pip install psycopg2-binary)."
        ) from exc
    return psycopg2


def est_postgresql(conn) -> bool:
    """Vrai si `conn` est une connexion PostgreSQL (jamais un vrai
    `sqlite3.Connection` — la voie sqlite reste un passthrough total, cette
    fonction sert aux quelques endroits qui doivent adapter une instruction
    précise, ex. le verrou de réservation de numéros)."""
    return not isinstance(conn, sqlite3.Connection)


def _traduire_placeholders(sql: str) -> str:
    """`?` (SQLite) → `%s` (psycopg2). Le codebase n'utilise jamais `?` en
    dehors d'un paramètre lié (jamais dans un littéral texte), donc une
    substitution directe est sûre — vérifié : aucun `?` littéral dans le SQL
    de ce projet."""
    return sql.replace("?", "%s")


class CursorPostgres:
    """Enveloppe fine autour d'un curseur psycopg2 (RealDictCursor) —
    `fetchone`/`fetchall`/`rowcount` passthrough, `lastrowid` alimenté par le
    `RETURNING id` ajouté automatiquement aux INSERT (voir
    `ConnexionPostgres.execute`)."""

    def __init__(self, cursor) -> None:
        self._cursor = cursor
        self.lastrowid: int | None = None

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def __iter__(self):
        return iter(self._cursor)


class ConnexionPostgres:
    """Remplace `sqlite3.Connection` pour les repositories quand
    `config.lire_moteur_bdd() == 'postgresql'`."""

    def __init__(self, connexion_psycopg2) -> None:
        self._conn = connexion_psycopg2

    def execute(self, sql: str, params: Sequence[Any] = ()) -> CursorPostgres:
        from psycopg2.extras import RealDictCursor

        sql_traduit = _traduire_placeholders(sql)
        ajoute_returning = bool(_MOTS_INSERT.match(sql)) and not _A_DEJA_RETURNING.search(sql)
        if ajoute_returning:
            sql_traduit = sql_traduit.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql_traduit, tuple(params))
        enveloppe = CursorPostgres(cur)
        if ajoute_returning:
            ligne = cur.fetchone()
            enveloppe.lastrowid = ligne["id"] if ligne else None
        return enveloppe

    def executescript(self, sql: str) -> None:
        """Exécution multi-instructions (schéma DDL) — psycopg2 exécute
        nativement plusieurs instructions séparées par `;` en un seul appel,
        pas besoin de découper manuellement."""
        with self._conn.cursor() as cur:
            cur.execute(sql)
        self._conn.commit()

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()


def connecter_postgres(hote: str, port: int, base: str, utilisateur: str,
                       mot_de_passe: str) -> ConnexionPostgres:
    """Ouvre une connexion PostgreSQL et la retourne enveloppée dans
    `ConnexionPostgres` (interface compatible `sqlite3.Connection` pour les
    repositories)."""
    psycopg2 = _importer_psycopg2()
    conn = psycopg2.connect(
        host=hote, port=port, dbname=base, user=utilisateur, password=mot_de_passe,
    )
    return ConnexionPostgres(conn)


def debuter_transaction_exclusive(conn, table: str) -> None:
    """Acquiert un verrou d'écriture exclusif sur `table` avant même toute
    lecture, pour sérialiser des demandes concurrentes (ex. réservation de
    blocs de numéros — voir `FacturationService.reserver_bloc_numeros`) :
    `BEGIN IMMEDIATE` sur SQLite, `LOCK TABLE ... IN EXCLUSIVE MODE` sur
    PostgreSQL (portée reste la table, jamais toute la base — plus fin que
    SQLite, qui verrouille le fichier entier, mais offre la même garantie
    d'absence de chevauchement pour cette table précise)."""
    if est_postgresql(conn):
        conn.execute("BEGIN")
        conn.execute(f"LOCK TABLE {table} IN EXCLUSIVE MODE")
    else:
        conn.execute("BEGIN IMMEDIATE")


def colonnes_existantes(conn, table: str) -> set[str]:
    """Colonnes actuellement présentes dans `table` — `PRAGMA table_info`
    (SQLite) ou `information_schema.columns` (PostgreSQL). Utilisé par les
    migrations incrémentales (`base_repository._migrer`)."""
    if est_postgresql(conn):
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ?",
            (table,),
        ).fetchall()
        return {r["column_name"] for r in rows}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
