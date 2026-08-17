"""Aide à la recherche multi-termes : permet de chercher plusieurs valeurs à
la fois (ex. « ALPHA, BETA ») dans une même barre de recherche. Utilisé par
les repositories/services (ex. `ClientRepository.rechercher`,
`PaiementService.lister_avec_solde`) et par les filtres locaux du mode
client (`app/client/ui.py`)."""
from __future__ import annotations


def decouper_termes(q: str) -> list[str]:
    """Découpe une recherche en termes (séparés par une virgule), normalisés
    en minuscules, espaces superflus retirés, termes vides ignorés."""
    return [terme.strip().lower() for terme in q.split(",") if terme.strip()]


def correspond(valeur: str, termes: list[str]) -> bool:
    """Vrai si au moins un terme est une sous-chaîne de `valeur` (insensible
    à la casse, quelle que soit la casse déjà appliquée aux termes) — logique
    OU entre les termes."""
    valeur_normalisee = (valeur or "").lower()
    return any(terme.lower() in valeur_normalisee for terme in termes)
