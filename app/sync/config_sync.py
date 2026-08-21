"""Configuration persistante de la machine de facturation (coordonnées de
connexion à la machine boss, identité de ce poste, intervalles de
synchronisation). Stockée séparément de `app.config`/`app.client.config_client`
— la machine de facturation a son propre cache SQLite mais n'est ni la
machine principale (boss) ni le mode client léger existant."""
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

CHEMIN_CONFIG_SYNC: Path = _DOSSIER / "sync_config.json"

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

_INTERVALLE_SYNC_DEFAUT = 120        # secondes — file montante (filet de
# rattrapage : chaque opération réveille de toute façon le worker
# immédiatement dès son commit, voir `QueueSyncRepository.notifier_immediat`)
_INTERVALLE_REFERENTIELS_DEFAUT = 20  # secondes — pull descendant produits/
# clients (prix, stock, nouveaux articles) ; pas de canal de notification
# push côté serveur, donc un intervalle court reste la seule façon de garder
# le cache local proche du boss en temps quasi réel


@dataclass
class ConfigSync:
    """Coordonnées de connexion à la machine boss (base + API) et identité de
    cette machine de facturation."""

    hote: str = ""
    port: int = 8420
    token: str = ""              # jeton du rôle `role_facturation`
    machine_id: str = ""
    intervalle_sync_secondes: int = _INTERVALLE_SYNC_DEFAUT
    intervalle_referentiels_secondes: int = _INTERVALLE_REFERENTIELS_DEFAUT

    @property
    def base_url(self) -> str:
        return f"http://{self.hote}:{self.port}"

    @property
    def complete(self) -> bool:
        return bool(self.hote and self.token and self.machine_id)


def charger() -> ConfigSync:
    """Lit la configuration sauvegardée (vide si premier lancement)."""
    if not CHEMIN_CONFIG_SYNC.exists():
        return ConfigSync()
    try:
        donnees = json.loads(CHEMIN_CONFIG_SYNC.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ConfigSync()
    return ConfigSync(
        hote=donnees.get("hote", ""),
        port=int(donnees.get("port", 8420)),
        token=donnees.get("token", ""),
        machine_id=donnees.get("machine_id", ""),
        intervalle_sync_secondes=int(
            donnees.get("intervalle_sync_secondes", _INTERVALLE_SYNC_DEFAUT)),
        intervalle_referentiels_secondes=int(
            donnees.get("intervalle_referentiels_secondes",
                       _INTERVALLE_REFERENTIELS_DEFAUT)),
    )


def sauvegarder(config: ConfigSync) -> None:
    """Persiste la configuration pour les lancements suivants."""
    _demasquer(CHEMIN_CONFIG_SYNC)
    CHEMIN_CONFIG_SYNC.write_text(
        json.dumps({
            "hote": config.hote, "port": config.port, "token": config.token,
            "machine_id": config.machine_id,
            "intervalle_sync_secondes": config.intervalle_sync_secondes,
            "intervalle_referentiels_secondes": config.intervalle_referentiels_secondes,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _masquer(CHEMIN_CONFIG_SYNC)
