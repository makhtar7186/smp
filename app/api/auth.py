"""Authentification par jeton statique (en-tête `X-API-Key`), avec résolution
d'un rôle par jeton — voir CLAUDE.md, section « Accès distant »."""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, status

from app import config


@dataclass
class Identite:
    """Identité résolue à partir du jeton reçu."""

    role: str          # un des rôles de config.ROLES_API ('role_client',
                       # 'role_principal', 'role_facturation', 'role_stock')
    machine: str = ""  # dérivé de l'en-tête optionnel X-Machine-Id (traçabilité)


def identifier(
    x_api_key: str = Header(default=""),
    x_machine_id: str = Header(default=""),
) -> Identite:
    """Résout le jeton reçu vers un rôle. 401 si aucun jeton connu ne
    correspond (comparaison à temps constant pour chaque candidat, afin
    d'éviter un timing attack sur un jeton partagé entre plusieurs machines)."""
    for role in config.ROLES_API:
        attendu = config.lire_api_token(role)
        if attendu and hmac.compare_digest(x_api_key, attendu):
            return Identite(role=role, machine=x_machine_id)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Jeton API invalide ou manquant (en-tête X-API-Key).",
    )


def exiger_role(*roles_autorises: str):
    """Fabrique de dépendance : 403 si le rôle résolu n'est pas dans la liste
    autorisée. Usage : `Depends(exiger_role("role_client"))`."""

    def _dependance(identite: Identite = Depends(identifier)) -> Identite:
        if identite.role not in roles_autorises:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Action non autorisée pour ce rôle.",
            )
        return identite

    return _dependance


def verifier_token(identite: Identite = Depends(identifier)) -> None:
    """Conservée pour compatibilité : accepte n'importe quel rôle valide —
    exactement ce qu'utilisent les routes `/factures` existantes, en lecture
    pour les deux rôles."""
    return None
