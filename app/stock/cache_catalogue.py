"""Cache local léger du catalogue (dernière réponse réussie de
`GET /stock/produits`) — permet à l'app Stock de rester consultable quand le
serveur est momentanément injoignable. Volontairement pas une base de
données : un simple fichier JSON, écrasé à chaque rafraîchissement réussi
(voir CLAUDE.md, section « App Stock — mode hors ligne »). Même idiome que
`app/client/queue_hors_ligne.py`."""
from __future__ import annotations

import json
from datetime import datetime

from app.stock.config_stock import CHEMIN_CONFIG_STOCK

CHEMIN_CACHE_CATALOGUE = CHEMIN_CONFIG_STOCK.parent / "stock_catalogue_cache.json"


def sauvegarder(produits: list[dict]) -> None:
    """Écrase le cache avec le catalogue tout juste reçu du serveur."""
    CHEMIN_CACHE_CATALOGUE.write_text(
        json.dumps(
            {"horodatage": datetime.now().isoformat(timespec="seconds"),
             "produits": produits},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )


def charger() -> tuple[list[dict], str]:
    """Relit `(produits, horodatage)` du dernier cache réussi, ou `([], "")`
    si absent ou corrompu (jamais d'exception : un cache manquant n'est
    qu'un mode dégradé supplémentaire)."""
    if not CHEMIN_CACHE_CATALOGUE.exists():
        return [], ""
    try:
        donnees = json.loads(CHEMIN_CACHE_CATALOGUE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [], ""
    return donnees.get("produits", []), donnees.get("horodatage", "")
