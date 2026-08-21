"""Configuration persistante de la connexion PostgreSQL (onglet Serveur,
migration — voir app/services/postgres_migration_service.py).

Stockée séparément de client_config.json/sync_config.json (même dossier,
même idiome) : concerne uniquement l'outil de migration, pas la connexion à
l'API distante elle-même. Comme le jeton API dans client_config.json, le mot
de passe est stocké en clair — cohérent avec le reste de la configuration de
cette application desktop mono-utilisateur (voir CLAUDE.md)."""
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

CHEMIN_CONFIG_POSTGRES: Path = _DOSSIER / "postgres_config.json"


def _masquer(chemin: Path) -> None:
    """Cache ce fichier du Finder (macOS uniquement — jamais sous Windows,
    voir app/config.py::_masquer pour l'explication complète : le masquage
    Windows a été retiré après avoir provoqué des `PermissionError` en usage
    réel). Dupliquée ici : ce module reste volontairement indépendant de
    `app.config`, voir la docstring en tête de fichier."""
    if sys.platform != "darwin" or os.environ.get("SMP_NE_PAS_MASQUER"):
        return
    try:
        os.chflags(str(chemin), stat.UF_HIDDEN)
    except OSError:
        pass


def _nettoyer_masquage_windows_residuel(chemin: Path) -> None:
    """Retire l'attribut caché Windows résiduel — voir
    app/config.py::_nettoyer_masquage_windows_residuel pour l'explication
    complète. Appelée une seule fois, au chargement (`charger()`), jamais
    couplée à `sauvegarder()`."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        attributs = kernel32.GetFileAttributesW(str(chemin))
        if attributs != 0xFFFFFFFF and attributs & 0x2:  # FILE_ATTRIBUTE_HIDDEN
            kernel32.SetFileAttributesW(str(chemin), attributs & ~0x2)
    except OSError:
        pass


@dataclass
class ConfigPostgresStockee:
    """Coordonnées de connexion à la base PostgreSQL cible, persistées entre
    deux lancements."""

    hote: str = "localhost"
    port: int = 5432
    base: str = "promatelas"
    utilisateur: str = "promatelas"
    mot_de_passe: str = ""


def charger() -> ConfigPostgresStockee:
    """Lit la configuration sauvegardée (valeurs par défaut si absente)."""
    if not CHEMIN_CONFIG_POSTGRES.exists():
        return ConfigPostgresStockee()
    _nettoyer_masquage_windows_residuel(CHEMIN_CONFIG_POSTGRES)
    try:
        donnees = json.loads(CHEMIN_CONFIG_POSTGRES.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return ConfigPostgresStockee()
    return ConfigPostgresStockee(
        hote=donnees.get("hote", "localhost"),
        port=int(donnees.get("port", 5432)),
        base=donnees.get("base", "promatelas"),
        utilisateur=donnees.get("utilisateur", "promatelas"),
        mot_de_passe=donnees.get("mot_de_passe", ""),
    )


def sauvegarder(config: ConfigPostgresStockee) -> None:
    """Persiste la configuration pour les lancements suivants."""
    _nettoyer_masquage_windows_residuel(CHEMIN_CONFIG_POSTGRES)
    CHEMIN_CONFIG_POSTGRES.write_text(
        json.dumps({
            "hote": config.hote, "port": config.port, "base": config.base,
            "utilisateur": config.utilisateur, "mot_de_passe": config.mot_de_passe,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _masquer(CHEMIN_CONFIG_POSTGRES)
