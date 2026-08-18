"""Configuration persistante de la connexion PostgreSQL (onglet Serveur,
migration — voir app/services/postgres_migration_service.py).

Stockée séparément de client_config.json/sync_config.json (même dossier,
même idiome) : concerne uniquement l'outil de migration, pas la connexion à
l'API distante elle-même. Comme le jeton API dans client_config.json, le mot
de passe est stocké en clair — cohérent avec le reste de la configuration de
cette application desktop mono-utilisateur (voir CLAUDE.md)."""
from __future__ import annotations

import json
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
    CHEMIN_CONFIG_POSTGRES.write_text(
        json.dumps({
            "hote": config.hote, "port": config.port, "base": config.base,
            "utilisateur": config.utilisateur, "mot_de_passe": config.mot_de_passe,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
