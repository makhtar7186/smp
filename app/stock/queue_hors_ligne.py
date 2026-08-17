"""File d'attente locale légère pour les mouvements de stock saisis hors
ligne (API injoignable) — entrées et ajustements uniquement. Volontairement
pas une base de données ni une couche de logique métier : un simple fichier
JSON, rejoué dans l'ordre au retour de connexion. Même idiome que
`app/client/queue_hors_ligne.py` (versements).

Création/modification/suppression de produit sont volontairement exclues de
cette file : elles nécessiteraient une corrélation d'id local ↔ serveur pour
qu'une entrée/ajustement mis en attente juste après puisse référencer un
produit pas encore synchronisé — exactement la source de complexité qui a
justifié toute l'architecture SQLite + workers de la machine de facturation
(voir CLAUDE.md, section « Machine de facturation »). Une entrée/ajustement
mis en file ici référence toujours un `produit_id` déjà connu du serveur
(lu depuis le catalogue en cache, voir `cache_catalogue.py`), donc aucun
problème de corrélation ne se pose."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from app.stock.config_stock import CHEMIN_CONFIG_STOCK

CHEMIN_QUEUE = CHEMIN_CONFIG_STOCK.parent / "stock_operations_en_attente.json"


@dataclass
class OperationStockEnAttente:
    type_operation: str  # 'entree' | 'ajustement'
    produit_id: int
    quantite: int  # positive pour une entrée, delta signé pour un ajustement
    note: str = ""
    date_saisie: str = ""  # ISO, horodatage local informatif


def charger() -> list[OperationStockEnAttente]:
    """Lit la file locale (vide si absente ou corrompue)."""
    if not CHEMIN_QUEUE.exists():
        return []
    try:
        donnees = json.loads(CHEMIN_QUEUE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [OperationStockEnAttente(**item) for item in donnees]


def sauvegarder(items: list[OperationStockEnAttente]) -> None:
    CHEMIN_QUEUE.write_text(
        json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ajouter(type_operation: str, produit_id: int, quantite: int, note: str = "") -> None:
    items = charger()
    items.append(OperationStockEnAttente(
        type_operation=type_operation, produit_id=produit_id, quantite=quantite,
        note=note, date_saisie=datetime.now().isoformat(timespec="seconds"),
    ))
    sauvegarder(items)


def retirer(index: int) -> None:
    items = charger()
    if 0 <= index < len(items):
        items.pop(index)
        sauvegarder(items)
