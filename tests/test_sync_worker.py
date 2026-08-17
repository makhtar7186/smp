"""Tests de SyncWorker : ordre chronologique strict, blocage sur erreur
réseau (avec backoff) vs erreur métier (sans retry automatique) — voir
CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import ErreurInjoignable, ErreurMetierDistante
from app.sync.queue_repository import QueueSyncRepository
from app.sync.worker import _PALIERS_BACKOFF, SyncWorker


class _FauxApiSync:
    """Remplace ApiSyncClient : pas de réseau réel, comportements programmés
    à l'avance (un par appel d'`envoyer_operation`)."""

    def __init__(self, comportements: list | None = None, en_ligne: bool = True) -> None:
        self._comportements = list(comportements or [])
        self._en_ligne = en_ligne
        self.appels: list[str] = []

    def tester_connexion(self) -> bool:
        return self._en_ligne

    def envoyer_operation(self, type_operation, cle_correlation, payload, cree_le):
        self.appels.append(cle_correlation)
        comportement = self._comportements.pop(0)
        if isinstance(comportement, Exception):
            raise comportement
        return comportement or {"statut": "ok"}


def _worker(chemin_db: Path, api) -> SyncWorker:
    return SyncWorker(chemin_db, api, intervalle_secondes=999)


def test_traite_toutes_les_operations_dans_l_ordre(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    queue = QueueSyncRepository(conn)
    queue.enfiler("creation_client", "c1", {})
    queue.enfiler("creation_produit", "c2", {})
    queue.enfiler("creation_facture", "c3", {})

    api = _FauxApiSync([{}, {}, {}])
    worker = _worker(chemin_db, api)
    worker._traiter_file(queue)

    assert api.appels == ["c1", "c2", "c3"]
    assert queue.compter_en_attente() == 0
    assert queue.compter_erreur() == 0
    assert worker.statut().en_ligne is True
    assert worker.statut().en_attente == 0


def test_erreur_reseau_bloque_les_operations_suivantes_et_programme_un_backoff(
    tmp_path: Path,
) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    queue = QueueSyncRepository(conn)
    queue.enfiler("creation_client", "c1", {})
    queue.enfiler("creation_produit", "c2", {})

    api = _FauxApiSync([ErreurInjoignable("timeout")])
    worker = _worker(chemin_db, api)
    worker._traiter_file(queue)

    assert api.appels == ["c1"], "c2 ne doit jamais être tentée après l'échec de c1"
    assert queue.compter_en_attente() == 2  # c1 revient en_attente, c2 n'a jamais bougé
    assert queue.compter_erreur() == 0
    assert worker._delai_prochain == _PALIERS_BACKOFF[0]
    assert worker._palier_backoff == 1


def test_backoff_s_allonge_puis_se_reinitialise_sur_succes(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    queue = QueueSyncRepository(conn)

    api = _FauxApiSync(en_ligne=False)
    worker = _worker(chemin_db, api)
    worker._traiter_file(queue)  # 1er échec réseau : palier 0
    assert worker._delai_prochain == _PALIERS_BACKOFF[0]
    worker._traiter_file(queue)  # 2e échec réseau : palier 1
    assert worker._delai_prochain == _PALIERS_BACKOFF[1]

    queue.enfiler("creation_client", "c1", {})
    api2 = _FauxApiSync([{}])
    worker._api = api2
    worker._traiter_file(queue)
    assert worker._palier_backoff == 0
    assert worker._delai_prochain == worker._intervalle_secondes


def test_erreur_metier_marque_erreur_bloque_la_suite_sans_retry_auto(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    queue = QueueSyncRepository(conn)
    id1 = queue.enfiler("creation_facture", "usine:1", {})
    queue.enfiler("creation_facture", "usine:2", {})

    api = _FauxApiSync([ErreurMetierDistante("fact_panier_vide")])
    worker = _worker(chemin_db, api)
    worker._traiter_file(queue)

    assert api.appels == ["usine:1"]
    assert queue.compter_erreur() == 1
    assert queue.compter_en_attente() == 1  # la 2e opération n'a jamais été tentée
    # Pas de retry automatique : un second passage ne retente pas l'item en erreur.
    worker._traiter_file(queue)
    assert api.appels == ["usine:1"]

    # Reprise explicite de l'utilisateur (bouton « Réessayer »).
    queue.reessayer(id1)
    api2 = _FauxApiSync([{}, {}])
    worker._api = api2
    worker._traiter_file(queue)
    assert api2.appels == ["usine:1", "usine:2"]
    assert queue.compter_erreur() == 0
    assert queue.compter_en_attente() == 0


def test_hors_ligne_ne_tente_aucune_operation(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    queue = QueueSyncRepository(conn)
    queue.enfiler("creation_client", "c1", {})

    api = _FauxApiSync(en_ligne=False)
    worker = _worker(chemin_db, api)
    worker._traiter_file(queue)

    assert api.appels == []
    assert queue.compter_en_attente() == 1
    assert worker.statut().en_ligne is False


def test_demarrer_arreter_thread_reel_sans_crash(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    creer_connexion(chemin_db).close()
    api = _FauxApiSync(en_ligne=False)
    worker = SyncWorker(chemin_db, api, intervalle_secondes=30)
    worker.demarrer()
    worker.declencher_immediat()
    worker.arreter()
