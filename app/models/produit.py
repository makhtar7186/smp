"""Entité Produit (catalogue à plat : article + option dimension/litrage)."""
from __future__ import annotations

from dataclasses import dataclass

TYPE_OPTION_DIMENSION = "dimension"
TYPE_OPTION_LITRAGE = "litrage"
TYPES_OPTION: tuple[str, ...] = (TYPE_OPTION_DIMENSION, TYPE_OPTION_LITRAGE)


@dataclass
class Produit:
    """Article du catalogue : nom + option dimension ou litrage (avec sa
    propre valeur), prix FCFA. Chaque combinaison (nom, type_option,
    valeur_option) est une ligne de catalogue indépendante — ex. « BIDON »
    en litrage 1L, 5L, 20L est 3 lignes distinctes, chacune avec son prix."""

    id: int | None = None
    nom: str = ""              # ex. "BIDON"
    type_option: str = ""      # 'dimension' | 'litrage' | '' (sans option)
    valeur_option: str = ""    # ex. "5L" ou "40x60"
    prix: int = 0               # FCFA
    actif: bool = True
    quantite_stock: int = 0    # géré exclusivement par l'app Stock (lecture ici)
    # Id du produit CÔTÉ BOSS, appris via la synchro descendante du
    # référentiel — jamais utilisé sur la base boss elle-même (toujours 0
    # là-bas, `id` y fait déjà foi). Sur le cache d'une machine de
    # facturation, sert de clé de corrélation stable pour retrouver un
    # produit après un renommage (nom/option modifiés depuis l'app Stock) —
    # une recherche par (nom, type_option, valeur_option) échouerait sinon,
    # créant un doublon local au lieu de mettre à jour l'existant. Voir
    # CLAUDE.md, section « Machine de facturation ».
    id_serveur: int = 0

    @property
    def designation(self) -> str:
        """Libellé complet, ex. « BIDON 5L »."""
        return f"{self.nom} {self.valeur_option}".strip()

    @property
    def libelle_recherche(self) -> str:
        """Libellé court pour les suggestions de recherche (facturation, page
        Produits) : nom + valeur, sans le prix."""
        return self.designation
