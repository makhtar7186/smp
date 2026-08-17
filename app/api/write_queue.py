"""File d'attente FIFO pour sérialiser les écritures de versement.

Un worker unique traite les tâches une par une, pour éliminer tout risque
d'écriture concurrente SQLite même si plusieurs machines clientes enregistrent
un versement au même moment. Le mode WAL (activé globalement dans
`base_repository.creer_connexion`) permet aux lectures de continuer pendant
qu'une écriture est en cours. Voir CLAUDE.md, section « Paiements »."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class _Tache:
    fonction: Callable[[], Any]
    resultat: "queue.Queue"


class FileEcriture:
    """Sérialise l'exécution de fonctions arbitraires dans un unique thread
    worker, dans l'ordre FIFO d'arrivée. Chaque fonction doit ouvrir et fermer
    sa propre connexion SQLite à l'intérieur du worker (jamais réutiliser
    celle du thread appelant, sqlite3 n'étant pas thread-safe sur une
    connexion partagée)."""

    def __init__(self) -> None:
        self._file: "queue.Queue[_Tache]" = queue.Queue()
        self._thread = threading.Thread(
            target=self._boucle, daemon=True, name="promatelas-api-write")
        self._thread.start()

    def _boucle(self) -> None:
        while True:
            tache = self._file.get()
            try:
                tache.resultat.put(("ok", tache.fonction()))
            except Exception as exc:  # noqa: BLE001 — propagé à l'appelant
                tache.resultat.put(("erreur", exc))

    def executer(self, fonction: Callable[[], Any]) -> Any:
        """Bloque jusqu'à ce que `fonction` ait été exécutée par le worker
        (FIFO), puis renvoie son résultat ou relève son exception."""
        resultat: "queue.Queue" = queue.Queue(maxsize=1)
        self._file.put(_Tache(fonction, resultat))
        statut, valeur = resultat.get()
        if statut == "erreur":
            raise valeur
        return valeur


_file_globale = FileEcriture()


def obtenir_file() -> FileEcriture:
    """Instance module-level unique, partagée par tous les workers du
    threadpool FastAPI — un seul thread worker pour tout le process serveur."""
    return _file_globale
