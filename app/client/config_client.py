"""Configuration persistante du mode client (adresse, port, jeton API).

Stockée séparément de `app.config` : le mode client n'ouvre jamais la base
SQLite principale et peut être packagé en exécutable autonome distinct
(`SMP-Client.exe`).
"""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

if getattr(sys, "frozen", False):
    _EXECUTABLE = Path(sys.executable).resolve()
    if _EXECUTABLE.parent.name == "MacOS" and _EXECUTABLE.parent.parent.name == "Contents":
        # Bundle .app macOS : voir app/config.py pour l'explication complète
        # (même bug, même correctif — sys.executable pointe vers le binaire
        # interne du bundle, pas vers son dossier parent).
        _DOSSIER = _EXECUTABLE.parents[3]
    else:
        _DOSSIER = _EXECUTABLE.parent
else:
    _DOSSIER = Path(__file__).resolve().parent.parent.parent

CHEMIN_CONFIG_CLIENT: Path = _DOSSIER / "client_config.json"


_ATTRIBUT_WINDOWS_CACHE = 0x2  # FILE_ATTRIBUTE_HIDDEN
_ATTRIBUTS_WINDOWS_INVALIDES = 0xFFFFFFFF  # INVALID_FILE_ATTRIBUTES


def _masquer(chemin: Path) -> None:
    """Cache ce fichier de l'explorateur de fichiers (Finder macOS /
    Explorateur Windows) — voir app/config.py::_masquer pour l'explication
    complète (même fonction, dupliquée ici : ce module reste volontairement
    indépendant de `app.config`, voir la docstring en tête de fichier)."""
    if os.environ.get("SMP_NE_PAS_MASQUER"):
        return
    if sys.platform == "darwin":
        try:
            os.chflags(str(chemin), stat.UF_HIDDEN)
        except OSError:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            attributs = kernel32.GetFileAttributesW(str(chemin))
            if attributs != _ATTRIBUTS_WINDOWS_INVALIDES:
                kernel32.SetFileAttributesW(str(chemin), attributs | _ATTRIBUT_WINDOWS_CACHE)
        except OSError:
            pass


@dataclass
class ConfigClient:
    """Coordonnées de connexion à la machine principale."""

    hote: str = ""
    port: int = 8420
    token: str = ""
    machine_id: str = ""  # optionnel : identifiant de ce poste, envoyé en X-Machine-Id
                          # (traçabilité des versements — voir CLAUDE.md, section « Paiements »)
    langue: str = "fr"    # 'fr' ou 'zh' — persisté ici, pas dans app/data/settings.json
                          # (le mode client n'a pas de base SQLite locale)

    @property
    def base_url(self) -> str:
        return f"http://{self.hote}:{self.port}"

    @property
    def complete(self) -> bool:
        return bool(self.hote and self.token)


def charger() -> ConfigClient:
    """Lit la configuration sauvegardée (vide si premier lancement)."""
    if not CHEMIN_CONFIG_CLIENT.exists():
        return ConfigClient()
    try:
        donnees = json.loads(CHEMIN_CONFIG_CLIENT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ConfigClient()
    return ConfigClient(
        hote=donnees.get("hote", ""),
        port=int(donnees.get("port", 8420)),
        token=donnees.get("token", ""),
        machine_id=donnees.get("machine_id", ""),
        langue=donnees.get("langue", "fr"),
    )


def sauvegarder(config: ConfigClient) -> None:
    """Persiste la configuration pour les lancements suivants."""
    CHEMIN_CONFIG_CLIENT.write_text(
        json.dumps({"hote": config.hote, "port": config.port, "token": config.token,
                    "machine_id": config.machine_id, "langue": config.langue},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _masquer(CHEMIN_CONFIG_CLIENT)
