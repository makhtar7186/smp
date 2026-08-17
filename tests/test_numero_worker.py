"""Tests de NumeroReservationWorker : alimentation automatique du POOL DE
SECOURS local (palier 2, numérotation résiliente) — sans ce worker, une
coupure momentanée tomberait immédiatement au calcul déterministe hors ligne
(palier 3). Voir CLAUDE.md, section « Numérotation résiliente »."""
from __future__ import annotations

from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import ErreurInjoignable
from app.sync.etat_numerotation import EtatNumerotationRepository
from app.sync.numero_reservation import NumeroReservationRepository
from app.sync.numero_worker import NumeroReservationWorker, taille_bloc_secours


class _FauxApiSync:
    """Remplace ApiSyncClient : pas de réseau réel, réponses programmées à
    l'avance (une par appel de `reserver_numeros`)."""

    def __init__(self, reponses: list | None = None) -> None:
        self._reponses = list(reponses or [])
        self.appels: list[int] = []

    def reserver_numeros(self, quantite: int, delai_court: bool = False) -> dict:
        self.appels.append(quantite)
        reponse = self._reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


def test_taille_bloc_secours_depend_du_nombre_de_postes() -> None:
    assert taille_bloc_secours(1) == 30
    assert taille_bloc_secours(2) == 5
    assert taille_bloc_secours(5) == 5


def test_pool_vide_demande_un_bloc_taille_par_defaut(tmp_path: Path) -> None:
    """N inconnu (jamais communiqué) est traité comme N=1 — bloc de 30."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    numeros_repo = NumeroReservationRepository(conn)

    api = _FauxApiSync([{"numeros": list(range(260001, 260031)),
                         "n_postes_actifs": 1, "rang": 0}])
    worker = NumeroReservationWorker(chemin_db, api)
    worker.synchroniser(conn)

    assert api.appels == [30]
    assert numeros_repo.compter_disponibles("usine") == 30
    assert numeros_repo.prochain_disponible("usine") == 260001


def test_reponse_met_a_jour_n_et_rang_connus(tmp_path: Path) -> None:
    """Le bloc suivant doit utiliser la taille correspondant au N appris à
    la réponse précédente (ici N passe à 2 → blocs de 5)."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    numeros_repo = NumeroReservationRepository(conn)

    api = _FauxApiSync([
        {"numeros": [1, 2, 3, 4, 5], "n_postes_actifs": 1, "rang": 0},
    ])
    worker = NumeroReservationWorker(chemin_db, api)
    worker.synchroniser(conn)
    assert api.appels == [30]  # N encore inconnu (défaut 1) au premier appel

    # Un deuxième poste apparaît : le boss le signale à la prochaine réponse.
    numeros_repo.marquer_utilise(1)
    numeros_repo.marquer_utilise(2)
    numeros_repo.marquer_utilise(3)
    numeros_repo.marquer_utilise(4)
    numeros_repo.marquer_utilise(5)  # pool à 0 : redemande au prochain passage
    api._reponses.append({"numeros": [101, 102, 103, 104, 105],
                          "n_postes_actifs": 2, "rang": 1})
    worker.synchroniser(conn)
    assert api.appels == [30, 30]  # le worker ne connaissait toujours pas N=2 avant cet appel

    etat = EtatNumerotationRepository(conn).lire()
    assert (etat.n_connu, etat.rang_connu) == (2, 1)
    assert etat.base_connu == 105


def test_pool_suffisant_ne_redemande_rien(tmp_path: Path) -> None:
    """N inconnu (défaut 1) → bloc 30, seuil = 30 // 3 = 10 : un pool de 15
    numéros reste au-dessus du seuil, aucune demande."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    numeros_repo = NumeroReservationRepository(conn)
    numeros_repo.ajouter_bloc("usine", list(range(260001, 260016)))

    api = _FauxApiSync([])
    worker = NumeroReservationWorker(chemin_db, api)
    worker.synchroniser(conn)  # lèverait IndexError si un appel était tenté

    assert api.appels == []
    assert numeros_repo.compter_disponibles("usine") == 15


def test_erreur_reseau_est_avalee_sans_lever(tmp_path: Path) -> None:
    """Hors ligne ou erreur transitoire : nouvelle tentative au prochain
    passage, jamais de crash du thread daemon."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)

    api = _FauxApiSync([ErreurInjoignable("timeout")])
    worker = NumeroReservationWorker(chemin_db, api)
    worker.synchroniser(conn)  # ne doit pas lever

    numeros_repo = NumeroReservationRepository(conn)
    assert numeros_repo.compter_disponibles("usine") == 0


def test_poller_actif_ne_declenche_jamais_le_pool_de_secours(tmp_path: Path) -> None:
    """Palier 2 : ne se déclenche que si le poller de fond (palier 1) est en
    coupure soutenue — voir CLAUDE.md. Un poll récemment réussi doit
    empêcher toute demande de bloc, même un pool vide."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    EtatNumerotationRepository(conn).marquer_poll_reussi()

    api = _FauxApiSync([])
    worker = NumeroReservationWorker(chemin_db, api)
    worker.synchroniser(conn)  # lèverait IndexError si un appel était tenté

    assert api.appels == []


def test_demarrer_arreter_thread_reel_sans_crash(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    creer_connexion(chemin_db).close()
    api = _FauxApiSync([{"numeros": [260001], "n_postes_actifs": 1, "rang": 0}])
    worker = NumeroReservationWorker(chemin_db, api, intervalle_secondes=30)
    worker.demarrer()
    worker.declencher_immediat()
    worker.arreter()
