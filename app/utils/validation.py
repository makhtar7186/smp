"""Exceptions métier et validations de saisie."""
from __future__ import annotations


class ErreurMetier(Exception):
    """Erreur métier générique — le message (clé i18n) est destiné à l'utilisateur."""

    def __init__(self, cle_message: str) -> None:
        super().__init__(cle_message)
        self.cle_message = cle_message


class ErreurValidation(ErreurMetier):
    """Saisie utilisateur invalide."""


class ErreurImport(ErreurMetier):
    """Erreur lors de l'import Excel."""


def valider_entier_positif(texte: str, strict: bool = False) -> int:
    """Convertit un texte en entier ≥ 0 (ou > 0 si strict). Lève ErreurValidation."""
    try:
        valeur = int(str(texte).strip().replace(" ", ""))
    except (ValueError, TypeError) as exc:
        raise ErreurValidation("nombre_invalide") from exc
    if valeur < 0 or (strict and valeur == 0):
        raise ErreurValidation("nombre_invalide")
    return valeur


def valider_nombre_positif(texte: str, strict: bool = False) -> int | float:
    """Convertit un texte en nombre ≥ 0 (ou > 0 si strict), décimales acceptées
    (ex. « 2,5 » ou « 2.5 » pour une épaisseur ou une quantité). Lève
    ErreurValidation. Retourne un `int` quand la valeur est entière (évite de
    stocker 9.0 en base, ce qui afficherait « 9.0 » au lieu de « 9 » une fois
    concaténé en SQL), un `float` sinon."""
    try:
        valeur = float(str(texte).strip().replace(" ", "").replace(",", "."))
    except (ValueError, TypeError) as exc:
        raise ErreurValidation("nombre_invalide") from exc
    if valeur < 0 or (strict and valeur == 0):
        raise ErreurValidation("nombre_invalide")
    return int(valeur) if valeur == int(valeur) else valeur


def valider_non_vide(texte: str) -> str:
    """Valide qu'un champ texte n'est pas vide. Retourne le texte nettoyé."""
    texte = str(texte or "").strip()
    if not texte:
        raise ErreurValidation("champ_obligatoire")
    return texte
