"""Sauvegarde périodique PostgreSQL → SQLite (sens inverse de
`postgres_migration_service.py`) : une fois la base boss basculée sur
PostgreSQL (`config.definir_moteur_bdd("postgresql")`), PostgreSQL devient la
source de vérité, mais garder un instantané SQLite à jour sert de filet de
secours simple à consulter/restaurer (n'importe quel outil SQLite, jamais
`pg_dump`/un serveur PostgreSQL à reconstruire) — cohérent avec la
philosophie du reste du projet, qui n'exige jamais d'outillage externe pour
consulter les données.

Toujours un **remplacement complet** (DELETE puis réinsertion de
`TABLES_MIGREES`), jamais une synchronisation incrémentale : le schéma ne
trace aucune date de modification par ligne, un diff incrémental serait donc
invérifiable. Un remplacement complet reste largement acceptable à la
fréquence hebdomadaire visée (voir `SqliteBackupWorker`) pour un volume de
données de cette taille (facturation d'une PME).

Réutilise volontairement `TABLES_MIGREES` de `postgres_migration_service.py`
(mêmes tables, même périmètre) plutôt qu'une liste dupliquée : les tables
hors de ce périmètre (`mouvements_stock`, tables de cache/synchro propres à
une machine de facturation...) ne sont ni vidées ni resauvegardées — une
limitation déjà acceptée par l'outil de migration initial, simplement
partagée ici. Les clés étrangères sont désactivées le temps du remplacement
complet : `mouvements_stock.produit_id` référence `produits(id)` en
`ON DELETE CASCADE`, donc un simple `DELETE FROM produits` sous clés
étrangères actives effacerait silencieusement le journal de stock (jamais
repeuplé ensuite, hors périmètre) à chaque sauvegarde.
"""
from __future__ import annotations

import sqlite3
import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.services.postgres_migration_service import (
    TABLES_MIGREES,
    ConfigPostgres,
    ErreurMigrationPostgres,
    _importer_psycopg2,
)

NOM_FICHIER_SAUVEGARDE = "promatelas_backup.db"
NOM_FICHIER_JOURNAL = "sauvegarde_sqlite.log"
INTERVALLE_SAUVEGARDE_SECONDES = 7 * 24 * 3600  # hebdomadaire
_DELAI_PREMIERE_SAUVEGARDE_SECONDES = 60  # laisse le serveur finir de démarrer


@dataclass
class RapportSauvegardeTable:
    table: str
    lignes: int = 0
    erreur: str = ""


@dataclass
class RapportSauvegarde:
    reussie: bool = False
    tables: list[RapportSauvegardeTable] = field(default_factory=list)
    erreur_globale: str = ""

    @property
    def total_lignes(self) -> int:
        return sum(t.lignes for t in self.tables)


class SqliteBackupService:
    """Exporte l'intégralité de `TABLES_MIGREES` depuis PostgreSQL vers un
    fichier SQLite local — symétrique de `PostgresMigrationService`, en sens
    inverse. Une seule méthode, appelable directement (tests, bouton manuel
    éventuel) sans passer par le planificateur `SqliteBackupWorker`."""

    def sauvegarder(self, config_pg: ConfigPostgres, chemin_sqlite: Path) -> RapportSauvegarde:
        rapport = RapportSauvegarde()
        try:
            psycopg2 = _importer_psycopg2()
        except ErreurMigrationPostgres as exc:
            rapport.erreur_globale = str(exc)
            return rapport

        try:
            conn_pg = psycopg2.connect(
                host=config_pg.hote, port=config_pg.port, dbname=config_pg.base,
                user=config_pg.utilisateur, password=config_pg.mot_de_passe,
                connect_timeout=5,
            )
        except Exception as exc:  # noqa: BLE001 — toute erreur psycopg2 → message clair
            rapport.erreur_globale = str(exc)
            return rapport

        # Schéma canonique déjà à jour (tables + migrations) — même chemin
        # que tout autre cache SQLite du projet (voir CLAUDE.md, « Gestion
        # de stock ») : `chemin_db` explicite, donc toujours SQLite quel que
        # soit `config.lire_moteur_bdd()`.
        conn_sqlite = creer_connexion(chemin_db=chemin_sqlite)

        try:
            # Voir docstring du module : protège les tables hors périmètre
            # (ex. mouvements_stock, CASCADE sur produits) d'un effacement
            # collatéral pendant le remplacement complet ci-dessous.
            conn_sqlite.execute("PRAGMA foreign_keys = OFF")
            for table in reversed(TABLES_MIGREES):
                conn_sqlite.execute(f"DELETE FROM {table}")
            with conn_pg.cursor() as cur_pg:
                for table in TABLES_MIGREES:
                    rapport.tables.append(self._copier_table(cur_pg, conn_sqlite, table))
            rapport.reussie = not any(t.erreur for t in rapport.tables)
            if rapport.reussie:
                conn_sqlite.commit()
            else:
                conn_sqlite.rollback()
        except Exception as exc:  # noqa: BLE001 — jamais une trace psycopg2/sqlite3 brute
            conn_sqlite.rollback()
            rapport.erreur_globale = str(exc)
        finally:
            conn_sqlite.execute("PRAGMA foreign_keys = ON")
            conn_pg.close()
            conn_sqlite.close()
        return rapport

    def _copier_table(self, cur_pg, conn_sqlite: sqlite3.Connection, table: str) -> RapportSauvegardeTable:
        rapport = RapportSauvegardeTable(table=table)
        try:
            cur_pg.execute(f'SELECT * FROM "{table}"')
            # Index numérique (`d[0]`), pas `.name` : compatible avec toutes
            # les versions de psycopg2, le DB-API standard garantit cette
            # position dans chaque tuple `description`.
            colonnes = [d[0] for d in cur_pg.description]
            lignes = cur_pg.fetchall()
            rapport.lignes = len(lignes)
            if lignes:
                marqueurs = ", ".join("?" for _ in colonnes)
                colonnes_sql = ", ".join(colonnes)
                conn_sqlite.executemany(
                    f"INSERT INTO {table} ({colonnes_sql}) VALUES ({marqueurs})",
                    lignes,
                )
        except Exception as exc:  # noqa: BLE001 — remonté dans le rapport, pas levé
            rapport.erreur = str(exc)
        return rapport


class SqliteBackupWorker:
    """Thread démon : tant que la base boss tourne sur PostgreSQL
    (`config.lire_moteur_bdd() == "postgresql"`), sauvegarde `TABLES_MIGREES`
    vers un fichier SQLite local une fois par semaine. Premier cycle ~1 min
    après le démarrage (pas d'attente d'une semaine complète avant la toute
    première sauvegarde), jamais bloquant pour le serveur, jamais fatal en
    cas d'échec (voir CLAUDE.md, « Un thread daemon ne doit jamais mourir
    sur une exception imprévue »).

    Aucune mémorisation de la date de dernière sauvegarde entre deux
    lancements du serveur : l'intervalle redémarre à chaque redémarrage du
    processus. Un serveur redémarré plus souvent qu'une fois par semaine se
    sauvegarde donc aussi plus souvent — sans conséquence négative, une
    sauvegarde de plus ne coûte qu'un peu de temps CPU au démarrage."""

    def __init__(self, intervalle_secondes: int = INTERVALLE_SAUVEGARDE_SECONDES) -> None:
        self._intervalle = intervalle_secondes
        self._arret = threading.Event()
        self._thread: threading.Thread | None = None

    def demarrer(self) -> None:
        self._thread = threading.Thread(
            target=self._boucle, daemon=True, name="smp-sauvegarde-sqlite",
        )
        self._thread.start()

    def arreter(self) -> None:
        """Réveille immédiatement l'attente en cours — pas d'attente
        résiduelle jusqu'à une semaine à la fermeture du processus (le
        thread étant démon, ce n'est qu'un confort pour un arrêt propre)."""
        self._arret.set()

    def _boucle(self) -> None:
        if self._arret.wait(_DELAI_PREMIERE_SAUVEGARDE_SECONDES):
            return
        while not self._arret.is_set():
            try:
                self._cycle()
            except Exception:  # noqa: BLE001 — ne jamais tuer ce thread
                self._journaliser_texte(traceback.format_exc() + "\n" + "-" * 70)
            if self._arret.wait(self._intervalle):
                return

    def _cycle(self) -> None:
        from app import config

        if config.lire_moteur_bdd() != "postgresql":
            return  # SQLite est déjà la source de vérité : rien à sauvegarder
        config_pg = ConfigPostgres(**config.lire_config_postgres())
        chemin_backup = config.DOSSIER_DATA / NOM_FICHIER_SAUVEGARDE
        rapport = SqliteBackupService().sauvegarder(config_pg, chemin_backup)
        if rapport.reussie:
            self._journaliser_texte(f"OK — {rapport.total_lignes} lignes")
        else:
            self._journaliser_texte(f"ÉCHEC — {rapport.erreur_globale}")

    def _journaliser_texte(self, texte: str) -> None:
        from app import config

        config.preparer_dossiers()
        horodatage = datetime.now().isoformat(timespec="seconds")
        with open(config.DOSSIER_DATA / NOM_FICHIER_JOURNAL, "a", encoding="utf-8") as journal:
            journal.write(f"{horodatage} {texte}\n")
