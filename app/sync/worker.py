"""Worker de synchronisation montante (machine de facturation) : thread
daemon à sondage périodique, traite la file dans l'ordre chronologique strict
un élément à la fois. Une erreur — réseau ou métier — sur l'item N bloque
N+1 : les dépendances causales entre opérations (modification après création,
facture client après facture usine de même numéro, fusion pouvant affecter la
résolution client d'une facture suivante) rendent un traitement « best effort
désordonné » risqué, alors que le volume (un seul poste de facturation) rend
le coût d'un blocage strict borné. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import (
    ApiSyncClient,
    ErreurAuthentification,
    ErreurInjoignable,
    ErreurMetierDistante,
    ErreurPermission,
)
from app.sync.models import StatutSync
from app.sync.queue_repository import QueueSyncRepository

_PALIERS_BACKOFF = (5, 15, 30, 60, 120)  # secondes — erreurs réseau transitoires


class SyncWorker:
    """Un seul thread daemon, une seule connexion SQLite (ouverte dans le
    thread lui-même — jamais celle du thread appelant)."""

    def __init__(self, chemin_cache_db: Path, api: ApiSyncClient,
                 intervalle_secondes: int = 120,
                 on_statut_change: Callable[[StatutSync], None] | None = None) -> None:
        self._chemin_cache_db = chemin_cache_db
        self._api = api
        self._intervalle_secondes = intervalle_secondes
        self._on_statut_change = on_statut_change
        self._reveil = threading.Event()
        self._arret = threading.Event()
        self._thread: threading.Thread | None = None
        self._palier_backoff = 0
        self._delai_prochain = 0.0  # 1re passe immédiate au démarrage du thread
        self._verrou_statut = threading.Lock()
        self._statut = StatutSync()

    # Cycle de vie ------------------------------------------------------------
    def demarrer(self) -> None:
        if self._thread is not None:
            return
        self._arret.clear()
        self._thread = threading.Thread(target=self._boucle, daemon=True,
                                        name="promatelas-sync-worker")
        self._thread.start()

    def arreter(self) -> None:
        self._arret.set()
        self._reveil.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def declencher_immediat(self) -> None:
        """Vérification immédiate à la détection de reconnexion — réinitialise
        aussi le backoff pour repartir sur un cycle complet."""
        self._palier_backoff = 0
        self._reveil.set()

    def statut(self) -> StatutSync:
        with self._verrou_statut:
            return self._statut

    # Boucle interne (thread worker) -------------------------------------------
    def _boucle(self) -> None:
        conn = creer_connexion(self._chemin_cache_db)
        queue = QueueSyncRepository(conn)
        # Récupération après un arrêt brutal (crash, coupure de courant) : une
        # ligne restée "en_cours" ne doit jamais bloquer la file indéfiniment.
        queue.reinitialiser_en_cours()
        try:
            while not self._arret.is_set():
                try:
                    self._traiter_file(queue)
                except Exception:
                    # Filet de sécurité : une erreur imprévue (ex. verrou
                    # SQLite concurrent, réponse serveur inattendue non
                    # couverte par les exceptions déjà distinguées ci-dessus)
                    # ne doit JAMAIS tuer ce thread daemon — sans console
                    # (`--windowed`), elle serait invisible et arrêterait
                    # silencieusement toute synchro montante jusqu'au
                    # redémarrage de l'app.
                    self._enregistrer_backoff()
                self._reveil.wait(self._delai_prochain)
                self._reveil.clear()
        finally:
            conn.close()

    def _traiter_file(self, queue: QueueSyncRepository) -> None:
        if not self._api.tester_connexion():
            self._enregistrer_backoff()
            self._maj_statut(queue, en_ligne=False)
            return

        while True:
            item = queue.prochaine_a_traiter()
            if item is None:
                self._reinitialiser_backoff()
                break
            queue.marquer_en_cours(item.id)
            try:
                self._api.envoyer_operation(item.type_operation, item.cle_correlation,
                                            item.payload, item.cree_le)
            except ErreurInjoignable:
                queue.remettre_en_attente(item.id)
                self._enregistrer_backoff()
                break
            except (ErreurMetierDistante, ErreurAuthentification, ErreurPermission) as exc:
                queue.marquer_erreur(item.id, str(exc))
                self._reinitialiser_backoff()
                break
            else:
                queue.marquer_synchronise(item.id)
                # continue : rejoue l'item suivant dans le même passage

        self._maj_statut(queue, en_ligne=True)

    def _enregistrer_backoff(self) -> None:
        self._delai_prochain = _PALIERS_BACKOFF[
            min(self._palier_backoff, len(_PALIERS_BACKOFF) - 1)]
        self._palier_backoff += 1

    def _reinitialiser_backoff(self) -> None:
        self._palier_backoff = 0
        self._delai_prochain = self._intervalle_secondes

    def _maj_statut(self, queue: QueueSyncRepository, en_ligne: bool) -> None:
        with self._verrou_statut:
            self._statut = StatutSync(
                en_ligne=en_ligne,
                en_attente=queue.compter_en_attente(),
                erreur=queue.compter_erreur(),
                derniere_synchro=datetime.now().isoformat(timespec="seconds"),
            )
            snapshot = self._statut
        if self._on_statut_change is not None:
            self._on_statut_change(snapshot)
