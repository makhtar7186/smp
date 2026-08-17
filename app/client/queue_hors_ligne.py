"""File d'attente locale légère pour les versements saisis hors ligne (API
injoignable). Volontairement pas une base de données ni une couche de
logique métier : un simple fichier JSON, rejoué dans l'ordre au retour de
connexion. Ne sert JAMAIS de source pour un solde affiché — le solde vient
toujours de l'API ; hors ligne, l'UI doit afficher « N versement(s) en
attente » plutôt qu'un solde recalculé localement (voir CLAUDE.md, section
« Paiements »)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date

from app.client.config_client import CHEMIN_CONFIG_CLIENT

CHEMIN_QUEUE = CHEMIN_CONFIG_CLIENT.parent / "versements_en_attente.json"


@dataclass
class VersementEnAttente:
    facture_id: int
    montant: int
    date_versement: str  # ISO YYYY-MM-DD
    remarque: str = ""


def charger() -> list[VersementEnAttente]:
    """Lit la file locale (vide si absente ou corrompue)."""
    if not CHEMIN_QUEUE.exists():
        return []
    try:
        donnees = json.loads(CHEMIN_QUEUE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [VersementEnAttente(**item) for item in donnees]


def sauvegarder(items: list[VersementEnAttente]) -> None:
    CHEMIN_QUEUE.write_text(
        json.dumps([asdict(item) for item in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ajouter(facture_id: int, montant: int, date_versement: date, remarque: str = "") -> None:
    items = charger()
    items.append(VersementEnAttente(
        facture_id=facture_id, montant=montant,
        date_versement=date_versement.isoformat(), remarque=remarque,
    ))
    sauvegarder(items)


def retirer(index: int) -> None:
    items = charger()
    if 0 <= index < len(items):
        items.pop(index)
        sauvegarder(items)
