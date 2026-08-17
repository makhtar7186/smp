"""File d'attente unifiée de synchronisation montante (cache de la machine de
facturation) — table `queue_synchronisation`, traitée dans l'ordre
chronologique strict par `app.sync.worker.SyncWorker`. Voir CLAUDE.md,
section « Machine de facturation »."""
from __future__ import annotations

import json
import sqlite3
from typing import Callable

from app.models import OperationSync
from app.repositories.base_repository import BaseRepository


def _vers_operation(row: sqlite3.Row) -> OperationSync:
    return OperationSync(
        id=row["id"],
        type_operation=row["type_operation"],
        cle_correlation=row["cle_correlation"],
        payload=json.loads(row["payload_json"]),
        statut=row["statut"],
        tentatives=row["tentatives"],
        derniere_erreur=row["derniere_erreur"],
        cree_le=row["cree_le"],
        traite_le=row["traite_le"],
        machine_id=row["machine_id"],
    )


class QueueSyncRepository(BaseRepository):
    """CRUD de la file d'attente. `enfiler_sans_commit` participe à la
    transaction déjà ouverte par l'appelant (ex. `FactureRepository.enregistrer`)
    — jamais de commit propre, pour garantir l'atomicité écriture+enfilage.

    `on_enfiler` (optionnel) est appelé à chaque opération réellement
    committée — jamais depuis `enfiler_sans_commit` elle-même, dont la
    transaction n'est pas encore visible pour le `SyncWorker` (connexion
    séparée) : l'appelant d'`enfiler_sans_commit` doit déclencher
    `notifier_immediat()` lui-même, une fois SON PROPRE commit effectué (voir
    `FactureRepository.enregistrer`/`modifier`). Sert à réveiller
    immédiatement la synchro montante dès qu'une opération est en attente,
    plutôt que d'attendre le prochain passage périodique — voir CLAUDE.md,
    section « Machine de facturation »."""

    def __init__(self, conn, on_enfiler: Callable[[], None] | None = None) -> None:
        super().__init__(conn)
        self._on_enfiler = on_enfiler

    def notifier_immediat(self) -> None:
        """Signale qu'une opération vient d'être committée et attend d'être
        synchronisée — sans effet si aucun `on_enfiler` n'a été fourni."""
        if self._on_enfiler is not None:
            self._on_enfiler()

    def _ligne_en_attente_ou_erreur(self, cle_correlation: str) -> sqlite3.Row | None:
        if not cle_correlation:
            return None
        return self.conn.execute(
            "SELECT id FROM queue_synchronisation WHERE cle_correlation = ?"
            " AND statut IN ('en_attente', 'erreur') ORDER BY id LIMIT 1",
            (cle_correlation,),
        ).fetchone()

    def enfiler_sans_commit(self, type_operation: str, cle_correlation: str,
                            payload: dict, machine_id: str = "") -> int:
        """Fusionne avec une opération encore en_attente/erreur de même
        `cle_correlation` (écrase son payload, remet `en_attente`) plutôt que
        d'empiler une opération orpheline — voir CLAUDE.md, « Corrélation
        client/serveur sans mapping d'ids »."""
        existante = self._ligne_en_attente_ou_erreur(cle_correlation)
        payload_json = json.dumps(payload, ensure_ascii=False)
        if existante is not None:
            self.conn.execute(
                "UPDATE queue_synchronisation SET type_operation = ?,"
                " payload_json = ?, statut = 'en_attente', derniere_erreur = ''"
                " WHERE id = ?",
                (type_operation, payload_json, existante["id"]),
            )
            return existante["id"]
        cur = self.conn.execute(
            "INSERT INTO queue_synchronisation"
            " (type_operation, cle_correlation, payload_json, machine_id)"
            " VALUES (?,?,?,?)",
            (type_operation, cle_correlation, payload_json, machine_id),
        )
        return cur.lastrowid

    def enfiler(self, type_operation: str, cle_correlation: str, payload: dict,
               machine_id: str = "") -> int:
        """Variante autonome (commit immédiat) pour les opérations qui ne
        participent pas à la transaction d'un autre repository (ex. fusion de
        client, déjà commitée en plusieurs étapes non atomiques — voir
        `ClientMaintenanceServiceHorsLigne`)."""
        item_id = self.enfiler_sans_commit(type_operation, cle_correlation, payload,
                                           machine_id)
        self.conn.commit()
        self.notifier_immediat()
        return item_id

    def prochaine_a_traiter(self) -> OperationSync | None:
        """La ligne non-synchronisée la plus ancienne DOIT être `en_attente`
        pour être retournée — si c'est une ligne `erreur` (ou `en_cours`), on
        retourne `None` : toute opération plus récente reste bloquée tant que
        celle-ci n'est pas explicitement résolue (`reessayer`), pour préserver
        l'ordre chronologique strict même à travers plusieurs passages du
        worker (pas seulement au sein d'un même passage)."""
        row = self.conn.execute(
            "SELECT * FROM queue_synchronisation WHERE statut != 'synchronise'"
            " ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is None or row["statut"] != "en_attente":
            return None
        return _vers_operation(row)

    def reinitialiser_en_cours(self) -> int:
        """Récupération après un arrêt brutal du worker : toute ligne restée
        `en_cours` (process tué en plein envoi) est remise `en_attente` — sans
        cela elle bloquerait indéfiniment toute la file, aucun autre worker ne
        pouvant jamais la débloquer. Appelé une fois au démarrage du worker."""
        cur = self.conn.execute(
            "UPDATE queue_synchronisation SET statut = 'en_attente' WHERE statut = 'en_cours'"
        )
        self.conn.commit()
        return cur.rowcount

    def marquer_en_cours(self, item_id: int) -> None:
        self.conn.execute(
            "UPDATE queue_synchronisation SET statut = 'en_cours' WHERE id = ?",
            (item_id,))
        self.conn.commit()

    def marquer_synchronise(self, item_id: int) -> None:
        self.conn.execute(
            "UPDATE queue_synchronisation SET statut = 'synchronise',"
            " traite_le = datetime('now'), derniere_erreur = '' WHERE id = ?",
            (item_id,))
        self.conn.commit()

    def marquer_erreur(self, item_id: int, message: str) -> None:
        self.conn.execute(
            "UPDATE queue_synchronisation SET statut = 'erreur',"
            " tentatives = tentatives + 1, derniere_erreur = ?,"
            " traite_le = datetime('now') WHERE id = ?",
            (message, item_id))
        self.conn.commit()

    def remettre_en_attente(self, item_id: int) -> None:
        """Erreur réseau transitoire : retour à `en_attente` pour un nouveau
        passage du worker (pas d'incrément de `tentatives`, distinct d'une
        erreur métier définitive)."""
        self.conn.execute(
            "UPDATE queue_synchronisation SET statut = 'en_attente' WHERE id = ?",
            (item_id,))
        self.conn.commit()

    def reessayer(self, item_id: int) -> None:
        """Action explicite de l'utilisateur sur une opération en `erreur` —
        jamais de retry automatique silencieux sur une erreur métier."""
        self.conn.execute(
            "UPDATE queue_synchronisation SET statut = 'en_attente',"
            " derniere_erreur = '' WHERE id = ? AND statut = 'erreur'",
            (item_id,))
        self.conn.commit()

    def compter_en_attente(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM queue_synchronisation"
            " WHERE statut IN ('en_attente', 'en_cours')"
        ).fetchone()
        return row["n"]

    def compter_erreur(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM queue_synchronisation WHERE statut = 'erreur'"
        ).fetchone()
        return row["n"]

    def lister(self, statuts: list[str] | None = None) -> list[OperationSync]:
        if statuts:
            marques = ",".join("?" * len(statuts))
            sql = (f"SELECT * FROM queue_synchronisation WHERE statut IN ({marques})"
                   " ORDER BY id")
            rows = self.conn.execute(sql, statuts).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM queue_synchronisation ORDER BY id").fetchall()
        return [_vers_operation(r) for r in rows]

    def statut_pour_facture(self, numero: int) -> str | None:
        """Dernier statut connu de la `cle_correlation` correspondante, ou
        `None` si cette facture n'a jamais été enfilée (ex. créée avant
        l'activation de la synchro) — pour le badge par facture de
        l'historique local."""
        row = self.conn.execute(
            "SELECT statut FROM queue_synchronisation WHERE cle_correlation = ?"
            " ORDER BY id DESC LIMIT 1",
            (f"facture:{numero}",),
        ).fetchone()
        return row["statut"] if row else None
