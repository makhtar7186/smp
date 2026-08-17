"""Archivage local des factures côté mode client — indépendant de
l'archivage de l'application principale (colonne `factures.archivee`, page
« Archive »). Chaque application gère son **propre** système d'archivage
(voir CLAUDE.md, section « Archivage ») : ce que l'application principale
archive n'affecte pas ce que le poste distant voit, et inversement. Persisté
dans un simple fichier JSON local (pas une base, pas de logique métier), à
côté de `client_config.json` — jamais envoyé au serveur."""
from __future__ import annotations

import json

from app.client.config_client import CHEMIN_CONFIG_CLIENT

CHEMIN_ARCHIVE_CLIENT = CHEMIN_CONFIG_CLIENT.parent / "factures_archivees_client.json"


def charger() -> set[int]:
    """Identifiants des factures archivées localement (vide si absent ou
    corrompu)."""
    if not CHEMIN_ARCHIVE_CLIENT.exists():
        return set()
    try:
        return set(json.loads(CHEMIN_ARCHIVE_CLIENT.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return set()


def sauvegarder(ids: set[int]) -> None:
    CHEMIN_ARCHIVE_CLIENT.write_text(
        json.dumps(sorted(ids)), encoding="utf-8")


def archiver(facture_id: int) -> None:
    archiver_plusieurs([facture_id])


def desarchiver(facture_id: int) -> None:
    desarchiver_plusieurs([facture_id])


def archiver_plusieurs(facture_ids: list[int]) -> None:
    """Archive plusieurs factures en une seule lecture/écriture du fichier
    (sélection multiple depuis l'onglet Historique)."""
    ids = charger()
    ids.update(facture_ids)
    sauvegarder(ids)


def desarchiver_plusieurs(facture_ids: list[int]) -> None:
    ids = charger()
    ids.difference_update(facture_ids)
    sauvegarder(ids)
