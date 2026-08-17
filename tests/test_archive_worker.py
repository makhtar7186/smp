"""Tests de ArchiveStatutSyncWorker : synchronisation descendante du statut
d'archivage — sans ce worker, une facture créée localement puis archivée sur
le boss resterait visible indéfiniment dans l'historique local, qui n'a
sinon aucun moyen de le savoir. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService
from app.sync.api_sync_client import ErreurInjoignable
from app.sync.archive_worker import ArchiveStatutSyncWorker


def _facture(conn, numero: int) -> None:
    FacturationService(conn).enregistrer_facture(
        numero=numero, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=1, prix_unitaire=10000)],
    )


class _FauxApiSync:
    def __init__(self, numeros_archives=None, exception=None) -> None:
        self._numeros_archives = numeros_archives or []
        self._exception = exception
        self.appels: list[list[int]] = []

    def statut_archivage(self, numeros: list[int]) -> list[int]:
        self.appels.append(list(numeros))
        if self._exception is not None:
            raise self._exception
        return self._numeros_archives


def test_marque_archivee_localement_une_facture_archivee_sur_le_boss(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    _facture(conn, 1)
    _facture(conn, 2)

    api = _FauxApiSync(numeros_archives=[1])
    worker = ArchiveStatutSyncWorker(chemin_db, api)
    worker.synchroniser(conn)

    assert api.appels == [[1, 2]]
    lignes = conn.execute("SELECT numero, archivee FROM factures ORDER BY numero").fetchall()
    assert {(r["numero"], r["archivee"]) for r in lignes} == {(1, 1), (2, 0)}


def test_reversion_desarchivee_sur_le_boss_se_repercute_localement(tmp_path: Path) -> None:
    """Une facture désarchivée sur le boss doit aussi redevenir visible
    localement (synchronisation dans les deux sens)."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    _facture(conn, 1)
    conn.execute("UPDATE factures SET archivee = 1 WHERE numero = 1")
    conn.commit()

    api = _FauxApiSync(numeros_archives=[])  # plus archivée côté boss
    worker = ArchiveStatutSyncWorker(chemin_db, api)
    worker.synchroniser(conn)

    ligne = conn.execute("SELECT archivee FROM factures WHERE numero = 1").fetchone()
    assert ligne["archivee"] == 0


def test_aucune_facture_locale_ne_leve_pas(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    api = _FauxApiSync()
    worker = ArchiveStatutSyncWorker(chemin_db, api)
    worker.synchroniser(conn)  # ne doit pas lever, ni appeler l'API
    assert api.appels == []


def test_erreur_reseau_est_avalee_sans_lever(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    _facture(conn, 1)

    api = _FauxApiSync(exception=ErreurInjoignable("timeout"))
    worker = ArchiveStatutSyncWorker(chemin_db, api)
    worker.synchroniser(conn)  # ne doit pas lever

    ligne = conn.execute("SELECT archivee FROM factures WHERE numero = 1").fetchone()
    assert ligne["archivee"] == 0  # inchangé


def test_demarrer_arreter_thread_reel_sans_crash(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    creer_connexion(chemin_db).close()
    api = _FauxApiSync()
    worker = ArchiveStatutSyncWorker(chemin_db, api, intervalle_secondes=30)
    worker.demarrer()
    worker.declencher_immediat()
    worker.arreter()
