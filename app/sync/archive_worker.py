"""Synchronisation descendante du statut d'archivage (clé naturelle
`numero`) depuis la machine boss vers le cache local de la machine de
facturation : une facture archivée sur le boss (page Archive) n'a sinon
aucune raison de disparaître de l'historique local, qui gère son propre
`factures.archivee` sans jamais recevoir la moindre mise à jour de la part
du boss. Thread daemon indépendant du `SyncWorker`/`ReferentielSyncWorker`/
`NumeroReservationWorker` — ne fait jamais qu'écrire le statut `archivee`
local, jamais de logique métier. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import threading
from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.repositories.facture_repository import FactureRepository
from app.sync.api_sync_client import ApiSyncClient, ErreurApiSync

_INTERVALLE_DEFAUT = 300  # secondes — même ordre de grandeur que les référentiels


class ArchiveStatutSyncWorker:
    """Thread daemon : vérifie périodiquement, pour les numéros usine connus
    localement, lesquels sont désormais archivés sur le boss."""

    def __init__(self, chemin_cache_db: Path, api: ApiSyncClient,
                 intervalle_secondes: int = _INTERVALLE_DEFAUT) -> None:
        self._chemin_cache_db = chemin_cache_db
        self._api = api
        self._intervalle_secondes = intervalle_secondes
        self._reveil = threading.Event()
        self._arret = threading.Event()
        self._thread: threading.Thread | None = None

    def demarrer(self) -> None:
        if self._thread is not None:
            return
        self._arret.clear()
        self._thread = threading.Thread(target=self._boucle, daemon=True,
                                        name="promatelas-archive-statut-worker")
        self._thread.start()

    def arreter(self) -> None:
        self._arret.set()
        self._reveil.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def declencher_immediat(self) -> None:
        self._reveil.set()

    def _boucle(self) -> None:
        conn = creer_connexion(self._chemin_cache_db)
        try:
            while not self._arret.is_set():
                try:
                    self.synchroniser(conn)
                except Exception:
                    # Filet de sécurité : voir ReferentielSyncWorker._boucle
                    # pour la justification (jamais tuer ce thread daemon).
                    pass
                self._reveil.wait(self._intervalle_secondes)
                self._reveil.clear()
        finally:
            conn.close()

    def synchroniser(self, conn) -> None:
        """Exposé en public (plutôt que privé) pour être appelable
        directement dans les tests, sans dépendre du thread/minuteur."""
        try:
            factures = FactureRepository(conn)
            tous_numeros = factures.numeros_connus()
            if not tous_numeros:
                return
            numeros_archives = self._api.statut_archivage(tous_numeros)
            factures.synchroniser_archivage(tous_numeros, numeros_archives)
        except ErreurApiSync:
            pass  # hors ligne ou erreur transitoire : nouvelle tentative au prochain passage
