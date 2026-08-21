"""Configuration persistante de l'app Stock (adresse, port, jeton API).

Stockée séparément de `app.config`/`app.client.config_client` : l'app Stock
n'ouvre jamais la base SQLite principale et peut être packagée en exécutable
autonome distinct (`SMP-Stock.exe`) — même schéma que
`app/client/config_client.py`.
"""
from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

if getattr(sys, "frozen", False):
    _DOSSIER = Path(sys.executable).resolve().parent
else:
    _DOSSIER = Path(__file__).resolve().parent.parent.parent

CHEMIN_CONFIG_STOCK: Path = _DOSSIER / "stock_config.json"

_ATTRIBUT_WINDOWS_CACHE = 0x2  # FILE_ATTRIBUTE_HIDDEN
_ATTRIBUTS_WINDOWS_INVALIDES = 0xFFFFFFFF  # INVALID_FILE_ATTRIBUTES


def _masquer(chemin: Path) -> None:
    """Cache ce fichier de l'explorateur de fichiers — voir
    app/config.py::_masquer pour l'explication complète (même fonction,
    dupliquée ici : ce module reste volontairement indépendant de
    `app.config`, voir la docstring en tête de fichier)."""
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


def _demasquer(chemin: Path) -> None:
    """Retire l'attribut caché juste avant une réécriture — voir
    app/config.py::_demasquer pour l'explication complète (sous Windows,
    réécrire un fichier déjà `FILE_ATTRIBUTE_HIDDEN` échoue sinon avec
    Permission denied)."""
    if sys.platform != "win32" or os.environ.get("SMP_NE_PAS_MASQUER"):
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        attributs = kernel32.GetFileAttributesW(str(chemin))
        if attributs != _ATTRIBUTS_WINDOWS_INVALIDES:
            kernel32.SetFileAttributesW(str(chemin), attributs & ~_ATTRIBUT_WINDOWS_CACHE)
    except OSError:
        pass


@dataclass
class ConfigStock:
    """Coordonnées de connexion au serveur (jeton `role_stock`)."""

    hote: str = ""
    port: int = 8420
    token: str = ""
    machine_id: str = ""  # optionnel : identifiant de ce poste, envoyé en X-Machine-Id
    langue: str = "fr"    # 'fr' ou 'zh' — persisté ici, pas dans app/data/settings.json

    @property
    def base_url(self) -> str:
        return f"http://{self.hote}:{self.port}"

    @property
    def complete(self) -> bool:
        return bool(self.hote and self.token)


def charger() -> ConfigStock:
    """Lit la configuration sauvegardée (vide si premier lancement)."""
    if not CHEMIN_CONFIG_STOCK.exists():
        return ConfigStock()
    try:
        donnees = json.loads(CHEMIN_CONFIG_STOCK.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ConfigStock()
    return ConfigStock(
        hote=donnees.get("hote", ""),
        port=int(donnees.get("port", 8420)),
        token=donnees.get("token", ""),
        machine_id=donnees.get("machine_id", ""),
        langue=donnees.get("langue", "fr"),
    )


def sauvegarder(config: ConfigStock) -> None:
    """Persiste la configuration pour les lancements suivants."""
    _demasquer(CHEMIN_CONFIG_STOCK)
    CHEMIN_CONFIG_STOCK.write_text(
        json.dumps({"hote": config.hote, "port": config.port, "token": config.token,
                    "machine_id": config.machine_id, "langue": config.langue},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _masquer(CHEMIN_CONFIG_STOCK)
