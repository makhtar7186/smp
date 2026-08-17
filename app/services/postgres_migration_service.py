"""Scaffolding de bascule SQLite → PostgreSQL : test de connexion, extraction
complète, insertion avec vérification d'intégrité, mode dry-run. Réutilise le
schéma canonique PostgreSQL de `base_repository._schema_postgresql` (mêmes
contraintes — clés étrangères, UNIQUE composites — que la base boss réelle
créée par `creer_connexion()`), jamais un schéma simplifié propre à cet
outil : une migration réelle laisse ainsi une base immédiatement conforme à
ce qu'attend une bascule effective (`config.definir_moteur_bdd("postgresql")`).

`psycopg2` est importé paresseusement (jamais au chargement du module) :
SMP.exe/SMP-Client.exe n'ont pas besoin de cette dépendance
tant que personne n'utilise cette fonctionnalité — voir requirements.txt."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from app.repositories.base_repository import _schema_postgresql

# Tables métier migrées, dans un ordre qui respecte les dépendances logiques
# (une table n'apparaît qu'après celles qu'elle référence) — jamais les
# tables de cache/synchro propres à UNE machine de facturation
# (reservations_numeros, numeros_reserves, queue_synchronisation,
# historique_fusions_clients) : sans valeur une fois les données
# centralisées sur une base PostgreSQL unique.
TABLES_MIGREES: tuple[str, ...] = (
    "clients", "produits", "factures", "lignes_vente",
    "remises", "versements", "proformas", "lignes_proforma",
)

# Colonnes `xxx_id` → table référencée, pour la vérification d'intégrité
# post-migration (repli simple : pas d'introspection générique des clés
# étrangères SQLite, la liste est courte et stable).
_COLONNES_CLES_ETRANGERES: dict[str, tuple[str, str]] = {
    "client_id": ("client_id", "clients"),
    "produit_id": ("produit_id", "produits"),
    "facture_id": ("facture_id", "factures"),
    "proforma_id": ("proforma_id", "proformas"),
}


class ErreurMigrationPostgres(Exception):
    """Connexion PostgreSQL indisponible, module manquant, ou échec de
    migration — toujours un message clair, jamais une trace psycopg2 brute
    remontée telle quelle à l'UI."""


@dataclass
class ConfigPostgres:
    """Coordonnées de connexion à la base PostgreSQL cible."""

    hote: str = "localhost"
    port: int = 5432
    base: str = "promatelas"
    utilisateur: str = "promatelas"
    mot_de_passe: str = ""


@dataclass
class RapportTable:
    table: str
    lignes_source: int = 0
    lignes_inserees: int = 0
    erreur: str = ""


@dataclass
class RapportMigration:
    dry_run: bool = True
    tables: list[RapportTable] = field(default_factory=list)
    anomalies_integrite: list[str] = field(default_factory=list)
    reussie: bool = False
    erreur_globale: str = ""

    @property
    def total_lignes(self) -> int:
        return sum(t.lignes_inserees for t in self.tables)


def _importer_psycopg2():
    try:
        import psycopg2
        import psycopg2.extras  # noqa: F401 — execute_values, utilisé par l'appelant
    except ImportError as exc:
        raise ErreurMigrationPostgres(
            "Le module psycopg2 n'est pas installé sur ce poste "
            "(pip install psycopg2-binary)."
        ) from exc
    return psycopg2


class PostgresMigrationService:
    """Extraction depuis la base SQLite locale (connexion déjà ouverte),
    transformation et insertion dans PostgreSQL. `migrer(dry_run=True)`
    exécute la migration réelle dans une transaction PostgreSQL puis
    l'annule (ROLLBACK) plutôt que de simuler les insertions à côté — un
    dry-run valide ainsi les contraintes réelles (types, unicité) sans aucun
    risque de corruption des données existantes."""

    def __init__(self, conn_sqlite: sqlite3.Connection) -> None:
        self._sqlite = conn_sqlite

    # Connexion --------------------------------------------------------------
    def tester_connexion(self, config: ConfigPostgres) -> tuple[bool, str]:
        """Retourne (succès, message) — ne modifie jamais PostgreSQL. Le
        message est soit la version du serveur (succès), soit une raison
        d'échec lisible (mot de passe refusé, hôte injoignable, base
        inexistante...)."""
        try:
            psycopg2 = _importer_psycopg2()
        except ErreurMigrationPostgres as exc:
            return False, str(exc)
        try:
            conn = self._connecter(psycopg2, config)
        except Exception as exc:  # noqa: BLE001 — toute erreur psycopg2 → message clair
            return False, str(exc)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = cur.fetchone()[0]
            return True, version
        finally:
            conn.close()

    def _connecter(self, psycopg2, config: ConfigPostgres):
        return psycopg2.connect(
            host=config.hote, port=config.port, dbname=config.base,
            user=config.utilisateur, password=config.mot_de_passe,
            connect_timeout=5,
        )

    # Migration ----------------------------------------------------------------
    def migrer(self, config: ConfigPostgres, dry_run: bool = True) -> RapportMigration:
        """Migre `TABLES_MIGREES` vers PostgreSQL. En dry-run (défaut), tout
        se déroule dans une vraie transaction PostgreSQL (schéma créé,
        données insérées, intégrité vérifiée) puis annulé — rien n'est
        persisté, mais toute erreur réelle (contrainte, type, connexion) est
        détectée exactement comme en migration réelle."""
        rapport = RapportMigration(dry_run=dry_run)
        try:
            psycopg2 = _importer_psycopg2()
        except ErreurMigrationPostgres as exc:
            rapport.erreur_globale = str(exc)
            return rapport
        try:
            conn_pg = self._connecter(psycopg2, config)
        except Exception as exc:  # noqa: BLE001
            rapport.erreur_globale = str(exc)
            return rapport

        try:
            with conn_pg.cursor() as cur:
                # Schéma canonique complet (mêmes contraintes — clés
                # étrangères, UNIQUE composites — que la base boss réelle,
                # voir `base_repository._schema_postgresql`) : jamais un
                # schéma simplifié propre à cet outil, qui divergerait
                # silencieusement de celui utilisé par `creer_connexion()`
                # lors d'une bascule réelle.
                cur.execute(_schema_postgresql())
                for table in TABLES_MIGREES:
                    rapport.tables.append(self._migrer_table(psycopg2, cur, table))
                self._recaler_sequences(cur, [t.table for t in rapport.tables
                                              if not t.erreur])
                rapport.anomalies_integrite = self._verifier_integrite(cur)
            rapport.reussie = (
                not rapport.anomalies_integrite
                and not any(t.erreur for t in rapport.tables)
            )
            if dry_run or not rapport.reussie:
                conn_pg.rollback()
            else:
                conn_pg.commit()
        except Exception as exc:  # noqa: BLE001 — jamais une trace brute à l'UI
            conn_pg.rollback()
            rapport.erreur_globale = str(exc)
        finally:
            conn_pg.close()
        return rapport

    def _colonnes(self, table: str) -> list[tuple[str, str, bool]]:
        """(nom, type_sqlite, est_cle_primaire) pour chaque colonne, dans
        l'ordre déclaré — reflète toujours le schéma réel (voir
        `base_repository._SCHEMA`), jamais une liste dupliquée à la main."""
        rows = self._sqlite.execute(f"PRAGMA table_info({table})").fetchall()
        return [(r["name"], r["type"], bool(r["pk"])) for r in rows]

    def _migrer_table(self, psycopg2, cur, table: str) -> RapportTable:
        from psycopg2.extras import execute_values

        rapport = RapportTable(table=table)
        colonnes = self._colonnes(table)
        noms_colonnes = [c[0] for c in colonnes]
        # Le schéma (CREATE TABLE, contraintes) est déjà en place — voir
        # `migrer()`, schéma canonique appliqué une fois avant cette boucle.

        lignes = self._sqlite.execute(f"SELECT * FROM {table}").fetchall()
        rapport.lignes_source = len(lignes)
        if not lignes:
            return rapport

        try:
            valeurs = [tuple(row[nom] for nom in noms_colonnes) for row in lignes]
            colonnes_sql = ", ".join(f'"{nom}"' for nom in noms_colonnes)
            execute_values(
                cur, f'INSERT INTO "{table}" ({colonnes_sql}) VALUES %s', valeurs,
            )
            rapport.lignes_inserees = cur.rowcount if cur.rowcount != -1 else len(valeurs)
        except Exception as exc:  # noqa: BLE001 — remonté dans le rapport, pas levé
            rapport.erreur = str(exc)
        return rapport

    def _recaler_sequences(self, cur, tables_migrees: list[str]) -> None:
        """Les id SQLite d'origine sont préservés tels quels à l'insertion
        (jamais régénérés) pour que les références entre tables restent
        valides — la séquence PostgreSQL créée par SERIAL doit donc être
        recalée sur le plus haut id importé, sinon la première insertion
        normale après bascule entrerait en collision avec un id existant."""
        for table in tables_migrees:
            cur.execute(
                f'SELECT setval(pg_get_serial_sequence(%s, %s),'
                f' COALESCE((SELECT MAX(id) FROM "{table}"), 1), '
                f' (SELECT MAX(id) FROM "{table}") IS NOT NULL)',
                (table, "id"),
            )

    def _verifier_integrite(self, cur) -> list[str]:
        """Comptage des lignes (source vs. insérées, déjà dans `RapportTable`)
        + contrôle des clés : toute colonne `xxx_id` non nulle doit référencer
        une ligne existante dans la table cible migrée juste avant elle."""
        anomalies: list[str] = []
        for table in TABLES_MIGREES:
            colonnes = [c[0] for c in self._colonnes(table)]
            for colonne in colonnes:
                cible = _COLONNES_CLES_ETRANGERES.get(colonne)
                if cible is None:
                    continue
                _, table_cible = cible
                cur.execute(
                    f'SELECT COUNT(*) FROM "{table}" t'
                    f' WHERE t."{colonne}" IS NOT NULL'
                    f' AND NOT EXISTS ('
                    f'   SELECT 1 FROM "{table_cible}" c WHERE c.id = t."{colonne}"'
                    f' )'
                )
                orphelins = cur.fetchone()[0]
                if orphelins:
                    anomalies.append(
                        f"{table}.{colonne} : {orphelins} référence(s) orpheline(s)"
                        f" vers {table_cible}"
                    )
        return anomalies
