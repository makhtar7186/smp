"""Point d'entrée du serveur API autonome (accès distant en lecture seule).

Volontairement indépendant de la fenêtre Tkinter principale : ce processus
continue de tourner si l'application principale est fermée. Il peut être
démarré/arrêté depuis la page « API distante » de l'application, lancé
automatiquement à l'ouverture de session Windows (dossier de démarrage), ou
double-cliqué directement — voir CLAUDE.md, section « Accès distant ».
"""
from __future__ import annotations

import sys
import traceback

from app import config


def _preparer_flux_sans_console() -> None:
    """En exécutable `--windowed` sans handle stdout/stderr hérité (double-clic
    direct, ou lancement depuis le dossier de démarrage Windows), PyInstaller
    laisse `sys.stdout`/`sys.stderr` à `None`. uvicorn plante alors dès la
    configuration de ses logs (`ColourizedFormatter` appelle `.isatty()`
    dessus). On les redirige vers un fichier journal dans ce cas — inutile
    quand ce processus a été lancé via `ApiManagementService.demarrer()`, qui
    fournit déjà des flux redirigés (Popen avec `stdout=`/`stderr=`)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    config.preparer_dossiers()
    journal = open(config.DOSSIER_DATA / "api_serveur.log", "a", encoding="utf-8")
    sys.stdout = journal
    sys.stderr = journal


if __name__ == "__main__":
    _preparer_flux_sans_console()
    try:
        from app.api.server import demarrer
        demarrer()
    except Exception:  # noqa: BLE001 — exécutable --windowed, pas de console
        config.preparer_dossiers()
        with open(config.DOSSIER_DATA / "api_erreurs.log", "a",
                 encoding="utf-8") as fichier:
            fichier.write(traceback.format_exc() + "\n" + "-" * 70 + "\n")
        raise
