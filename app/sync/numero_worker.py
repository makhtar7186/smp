"""Alimentation périodique du POOL DE SECOURS local (numérotation résiliente,
palier 2 — voir CLAUDE.md, section « Numérotation résiliente ») : jamais le
chemin nominal (palier 1, JIT à la demande depuis l'interface, voir
`app/sync/numero_resilient.py`), seulement une réserve pour absorber une
coupure momentanée sans tomber immédiatement au calcul déterministe hors
ligne (palier 3). Thread daemon séparé du `SyncWorker` (file montante) et du
`ReferentielSyncWorker` (référentiels) — ne fait jamais qu'écrire dans
`numeros_reserves`/`etat_numerotation`, jamais de lecture/écriture métier."""
from __future__ import annotations

import threading
from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import ApiSyncClient, ErreurApiSync
from app.sync.etat_numerotation import EtatNumerotationRepository
from app.sync.numero_reservation import NumeroReservationRepository

_INTERVALLE_DEFAUT = 60  # secondes — plus fréquent que les référentiels : bloque la facturation si vide


def taille_bloc_secours(n_connu: int) -> int:
    """Taille du bloc de secours selon le nombre de postes de facturation
    actuellement actifs — plus petite à plusieurs postes pour limiter
    l'écart de numérotation en cas d'entrelacement (spécification : N=1 →
    30, N≥2 → 5 par poste)."""
    return 30 if n_connu <= 1 else 5


class NumeroReservationWorker:
    """Thread daemon indépendant : demande un nouveau bloc de secours dès que
    le pool local passe sous le seuil (une fraction de la taille de bloc
    courante), ou immédiatement au démarrage et sur `declencher_immediat()`."""

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
                                        name="promatelas-numero-worker")
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
        dans les tests, sans dépendre du thread/minuteur. Palier 2 : ne se
        déclenche que si le poller de fond (palier 1) est en coupure soutenue
        — sinon la confirmation silencieuse à l'enregistrement suffit,
        inutile de maintenir un pool de secours actif en permanence (voir
        CLAUDE.md, « Numérotation résiliente »)."""
        try:
            etat_repo = EtatNumerotationRepository(conn)
            if not etat_repo.coupure_soutenue():
                return
            numeros_repo = NumeroReservationRepository(conn)
            etat = etat_repo.lire()
            bloc = taille_bloc_secours(etat.n_connu)
            seuil = max(1, bloc // 3)
            if numeros_repo.compter_disponibles("usine") >= seuil:
                return
            resultat = self._api.reserver_numeros(bloc)
            numeros = resultat["numeros"]
            numeros_repo.ajouter_bloc("usine", numeros)
            etat_repo.definir_n_rang(
                resultat.get("n_postes_actifs", 1), resultat.get("rang", 0))
            if numeros:
                etat_repo.definir_base_si_superieur(max(numeros))
        except ErreurApiSync:
            pass  # hors ligne ou erreur transitoire : nouvelle tentative au prochain passage
