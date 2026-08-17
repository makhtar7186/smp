"""Conversion d'un montant entier en toutes lettres (français), pour la
mention légale « Cette présente facture est arrêtée à la somme de : ... »
(voir CLAUDE.md, PdfService). Implémentation autonome (aucune dépendance
externe type num2words, absente de requirements.txt) suivant l'orthographe
traditionnelle : « et » pour 21/31/41/51/61/71 (jamais pour 81/91), accord de
« quatre-vingts »/« cents » uniquement en fin de groupe, « mille » invariable
et sans article, pluriel de « million(s) »/« milliard(s) »."""
from __future__ import annotations

_UNITES = [
    "zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit",
    "neuf", "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize",
    "dix-sept", "dix-huit", "dix-neuf",
]
_DIZAINES = {
    2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante",
}


def _moins_de_cent(n: int) -> str:
    """Convertit un nombre de 0 à 99."""
    if n < 20:
        return _UNITES[n]
    if n < 70:
        dizaine, reste = divmod(n, 10)
        mot = _DIZAINES[dizaine]
        if reste == 0:
            return mot
        if reste == 1:
            return f"{mot} et un"
        return f"{mot}-{_UNITES[reste]}"
    if n < 80:
        # 70-79 : soixante-dix, soixante et onze, soixante-douze...
        reste = n - 60
        if reste == 11:
            return "soixante et onze"
        return f"soixante-{_UNITES[reste]}"
    # 80-99 : quatre-vingts, quatre-vingt-un, quatre-vingt-dix...
    reste = n - 80
    if reste == 0:
        return "quatre-vingts"
    return f"quatre-vingt-{_UNITES[reste]}"


def _moins_de_mille(n: int) -> str:
    """Convertit un nombre de 0 à 999."""
    if n < 100:
        return _moins_de_cent(n)
    centaines, reste = divmod(n, 100)
    if centaines == 1:
        prefixe = "cent"
    else:
        prefixe = f"{_UNITES[centaines]} cent" + ("s" if reste == 0 else "")
    if reste == 0:
        return prefixe
    return f"{prefixe} {_moins_de_cent(reste)}"


_TRANCHES = [
    (1_000_000_000, "milliard", "milliards"),
    (1_000_000, "million", "millions"),
    (1_000, "mille", "mille"),  # « mille » est invariable
]


def nombre_en_lettres_fr(montant: int) -> str:
    """Convertit un entier (positif, négatif ou nul) en toutes lettres.

    >>> nombre_en_lettres_fr(0)
    'zéro'
    >>> nombre_en_lettres_fr(81)
    'quatre-vingt-un'
    >>> nombre_en_lettres_fr(201)
    'deux cent un'
    >>> nombre_en_lettres_fr(1001)
    'mille un'
    >>> nombre_en_lettres_fr(2000)
    'deux mille'
    """
    montant = int(montant)
    if montant == 0:
        return "zéro"
    if montant < 0:
        return f"moins {nombre_en_lettres_fr(-montant)}"

    reste = montant
    groupes: list[str] = []
    for valeur, singulier, pluriel in _TRANCHES:
        if reste < valeur:
            continue
        quantite, reste = divmod(reste, valeur)
        if valeur == 1_000:
            # « mille » : jamais « un mille », toujours invariable.
            groupes.append(singulier if quantite == 1 else f"{_moins_de_mille(quantite)} {singulier}")
        else:
            mot = singulier if quantite == 1 else pluriel
            groupes.append(f"{_moins_de_mille(quantite)} {mot}")
    if reste or not groupes:
        groupes.append(_moins_de_mille(reste))
    return " ".join(groupes)
