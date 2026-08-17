"""Tests de NumeroPollerWorker : sondage continu du plus haut numéro de
facture connu côté boss (palier 1, nominal — voir CLAUDE.md, section
« Numérotation résiliente »)."""
from __future__ import annotations

from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import ErreurInjoignable
from app.sync.etat_numerotation import EtatNumerotationRepository
from app.sync.numero_poller_worker import NumeroPollerWorker


class _FauxApiSync:
    def __init__(self, reponses: list | None = None) -> None:
        self._reponses = list(reponses or [])
        self.appels = 0

    def dernier_numero_connu(self) -> int:
        self.appels += 1
        reponse = self._reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


def test_sondage_reussi_avance_base_et_marque_le_poll(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    etat_repo = EtatNumerotationRepository(conn)
    api = _FauxApiSync([261611])
    worker = NumeroPollerWorker(chemin_db, api)

    worker.synchroniser(conn)

    etat = etat_repo.lire()
    assert etat.base_connu == 261611
    assert etat.dernier_poll_reussi != ""
    assert not etat_repo.coupure_soutenue()


def test_sondage_ne_fait_jamais_reculer_base_connu(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    etat_repo = EtatNumerotationRepository(conn)
    etat_repo.definir_base_si_superieur(300)
    api = _FauxApiSync([250])  # réponse serveur plus basse (improbable, mais jamais destructeur)
    worker = NumeroPollerWorker(chemin_db, api)

    worker.synchroniser(conn)

    assert etat_repo.lire().base_connu == 300


def test_erreur_reseau_est_avalee_sans_lever_ni_marquer_le_poll(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    etat_repo = EtatNumerotationRepository(conn)
    api = _FauxApiSync([ErreurInjoignable("timeout")])
    worker = NumeroPollerWorker(chemin_db, api)

    worker.synchroniser(conn)  # ne doit pas lever

    assert etat_repo.lire().dernier_poll_reussi == ""
    assert etat_repo.coupure_soutenue()


def test_demarrer_arreter_thread_reel_sans_crash(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    creer_connexion(chemin_db).close()
    api = _FauxApiSync([261611])
    worker = NumeroPollerWorker(chemin_db, api, intervalle_secondes=30)
    worker.demarrer()
    worker.declencher_immediat()
    worker.arreter()
