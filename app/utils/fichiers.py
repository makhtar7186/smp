"""Ouverture de fichiers générés dans l'application associée du système."""
from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path


def ouvrir_fichier(chemin: Path | str) -> None:
    """Ouvre un fichier (PDF, Excel…) avec l'application par défaut du système.

    L'utilisateur peut alors l'imprimer ou l'enregistrer ailleurs. `os.startfile`
    n'existe que sous Windows (le mode client tourne aussi sous macOS) — repli
    sur `open` (macOS) / `xdg-open` (Linux), puis sur le navigateur si tout échoue.
    """
    chemin = str(chemin)
    try:
        if sys.platform.startswith("win"):
            os.startfile(chemin)  # noqa: S606 — comportement voulu (visionneuse)
        elif sys.platform == "darwin":
            subprocess.run(["open", chemin], check=True)
        else:
            subprocess.run(["xdg-open", chemin], check=True)
    except (OSError, subprocess.CalledProcessError):
        webbrowser.open(Path(chemin).as_uri())
