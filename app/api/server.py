"""Lance le serveur API. Utilisable seul (`python -m app.api.server`) ou
depuis l'application principale (thread de fond, voir `demarrer_arriere_plan`).

Le trafic n'est pas chiffré ici (HTTPS non activé) : on part du principe que
la machine distante se connecte via le tunnel Tailscale, déjà chiffré de
bout en bout. Pour servir en HTTPS malgré tout (ex. accès hors Tailscale),
passer `ssl_keyfile=`/`ssl_certfile=` à `uvicorn.run(...)` ci-dessous.

`uvicorn.run` reçoit directement l'objet `app` (plutôt que la chaîne
`"app.api.app:app"`, qui déclencherait un import dynamique par nom de module) :
PyInstaller ne détecte pas les imports résolus par chaîne lors de son analyse
statique du bundle, ce qui ferait planter le serveur une fois packagé en
exécutable (`Could not import module "app.api.app"`) alors qu'il fonctionne
depuis les sources.

Ce processus est le seul, dans toute l'architecture, garanti de tourner en
continu (voir CLAUDE.md, « Serveur autonome ») : c'est donc ici, et
seulement ici, qu'est démarrée `SqliteBackupWorker` — la sauvegarde
hebdomadaire PostgreSQL → SQLite (voir `app/services/sqlite_backup_service.py`),
sans effet tant que la base boss n'a pas été basculée sur PostgreSQL.
"""
from __future__ import annotations

import threading

import uvicorn

from app import config
from app.api.app import app as _application
from app.services.sqlite_backup_service import SqliteBackupWorker

_worker_sauvegarde_sqlite: SqliteBackupWorker | None = None


def _demarrer_sauvegarde_sqlite() -> None:
    """Idempotent : un seul worker par processus, quel que soit le nombre
    d'appels (`demarrer()`/`demarrer_arriere_plan()` ne sont normalement
    jamais appelées plus d'une fois dans le même processus, mais un garde
    explicite coûte peu)."""
    global _worker_sauvegarde_sqlite
    if _worker_sauvegarde_sqlite is None:
        _worker_sauvegarde_sqlite = SqliteBackupWorker()
        _worker_sauvegarde_sqlite.demarrer()


def demarrer(host: str | None = None, port: int | None = None) -> None:
    """Démarre le serveur API en bloquant (usage : script séparé ou service)."""
    _demarrer_sauvegarde_sqlite()
    uvicorn.run(
        _application,
        host=host or config.lire_api_host(),
        port=port or config.lire_api_port(),
        log_level="info",
    )


def demarrer_arriere_plan(host: str | None = None, port: int | None = None) -> threading.Thread:
    """Démarre le serveur API dans un thread démon, pour cohabiter avec la
    boucle Tkinter de l'application principale. Le thread s'arrête seul à la
    fermeture du processus (daemon=True)."""
    _demarrer_sauvegarde_sqlite()
    hote = host or config.lire_api_host()
    portail = port or config.lire_api_port()

    def _cible() -> None:
        uvicorn.run(_application, host=hote, port=portail, log_level="warning")

    thread = threading.Thread(target=_cible, daemon=True, name="promatelas-api")
    thread.start()
    return thread


if __name__ == "__main__":
    demarrer()
