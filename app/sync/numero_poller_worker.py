"""Sondage continu du plus haut numéro de facture connu côté boss (palier 1,
nominal — voir CLAUDE.md, section « Numérotation résiliente ») : interroge
`GET /factures/dernier-numero` (endpoint léger, sans verrou) toutes les 3-5 s
et met à jour `etat_numerotation.base_connu`/`dernier_poll_reussi`. Thread
daemon séparé des trois autres workers de synchro — ne fait jamais qu'écrire
dans `etat_numerotation`, jamais de lecture/écriture métier."""
from __future__ import annotations

import threading
from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import ApiSyncClient, ErreurApiSync
from app.sync.etat_numerotation import EtatNumerotationRepository

_INTERVALLE_DEFAUT = 4  # secondes — cadence 3-5s demandée par la spécification


class NumeroPollerWorker:
    """Thread daemon indépendant : rafraîchit `base_connu` en arrière-plan
    pour que `NumeroResilientService.suggerer_numero()` reste instantané
    (jamais de réseau au moment de la suggestion)."""

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
                                        name="promatelas-numero-poller")
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
        """Exposé en public (plutôt que privé) pour être appelable directement
        dans les tests, sans dépendre du thread/minuteur."""
        etat_repo = EtatNumerotationRepository(conn)
        try:
            dernier = self._api.dernier_numero_connu()
        except ErreurApiSync:
            return  # hors ligne ou erreur transitoire : nouvelle tentative au prochain passage
        etat_repo.definir_base_si_superieur(dernier)
        etat_repo.marquer_poll_reussi()
