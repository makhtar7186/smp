"""Formatage des montants FCFA et des dates."""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from app import config

if TYPE_CHECKING:
    from app.models import Client


def format_fcfa(montant: int | float | None, avec_devise: bool = True) -> str:
    """Formate un montant en FCFA avec séparateur de milliers (espace).

    >>> format_fcfa(141300)
    '141 300 FCFA'
    """
    if montant is None:
        montant = 0
    texte = f"{int(round(montant)):,}".replace(",", " ")
    return f"{texte} {config.DEVISE}" if avec_devise else texte


def format_date(valeur: date | datetime | str | None) -> str:
    """Formate une date en JJ/MM/AAAA (accepte date, datetime ou ISO)."""
    if valeur is None:
        return ""
    if isinstance(valeur, str):
        valeur = datetime.strptime(valeur[:10], config.FORMAT_DATE_ISO).date()
    if isinstance(valeur, datetime):
        valeur = valeur.date()
    return valeur.strftime(config.FORMAT_DATE_AFFICHAGE)


def parse_date_affichage(texte: str) -> date:
    """Parse une date saisie en JJ/MM/AAAA. Lève ValueError si invalide."""
    return datetime.strptime(texte.strip(), config.FORMAT_DATE_AFFICHAGE).date()


def date_vers_iso(valeur: date) -> str:
    """Convertit une date en chaîne ISO YYYY-MM-DD (stockage)."""
    return valeur.strftime(config.FORMAT_DATE_ISO)


def iso_vers_date(texte: str) -> date:
    """Convertit une chaîne ISO YYYY-MM-DD en date."""
    return datetime.strptime(texte[:10], config.FORMAT_DATE_ISO).date()


def horodatage_sql() -> str:
    """Horodatage courant (UTC) au format exact de `datetime('now')` SQLite
    (`AAAA-MM-JJ HH:MM:SS`) — calculé côté Python plutôt que délégué au
    moteur SQL, pour un format identique que la base soit SQLite ou
    PostgreSQL (voir CLAUDE.md, section « Bascule PostgreSQL »)."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def format_nombre(valeur: float | int | None) -> str:
    """Formate un nombre (épaisseur, quantité) sans décimale inutile.

    >>> format_nombre(9)
    '9'
    >>> format_nombre(2.5)
    '2,5'
    """
    if valeur is None:
        return ""
    valeur = float(valeur)
    if valeur == int(valeur):
        return str(int(valeur))
    return f"{valeur:g}".replace(".", ",")


def libelle_client(client: "Client") -> str:
    """Étiquette d'affichage désambiguïsant les clients homonymes.

    >>> libelle_client(Client(nom="MOUSSA NDIAYE", adresse="DAKAR"))
    'MOUSSA NDIAYE — DAKAR'
    """
    return f"{client.nom} — {client.adresse}" if client.adresse else client.nom
