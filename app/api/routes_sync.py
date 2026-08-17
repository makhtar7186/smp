"""Endpoints de synchronisation offline-first (machine de facturation) :
réservation de blocs de numéros (numérotation continue), référentiels descendants (produits,
clients), et réception des opérations rejouées depuis la file d'attente
locale. Réservés au rôle `role_facturation` (voir CLAUDE.md, section
« Machine de facturation »)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import Identite, exiger_role
from app.api.deps import obtenir_facturation
from app.api.schemas import (
    ClientReferentielOut,
    DernierNumeroOut,
    OperationSyncIn,
    OperationSyncOut,
    ProduitReferentielOut,
    ReserverNumerosIn,
    ReserverNumerosOut,
)
from app.api.write_queue import obtenir_file
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService
from app.services.sync_reception_service import SyncReceptionService
from app.utils.validation import ErreurMetier

routeur_sync = APIRouter(dependencies=[Depends(exiger_role("role_facturation"))])


@routeur_sync.post("/factures/reserver-numeros", response_model=ReserverNumerosOut)
def reserver_numeros(
    corps: ReserverNumerosIn,
    identite: Identite = Depends(exiger_role("role_facturation")),
    facturation: FacturationService = Depends(obtenir_facturation),
) -> ReserverNumerosOut:
    """Réserve un bloc de numéros pour la machine appelante — numérotation
    continue, jamais tronqué. `quantite=1` (palier 1, JIT) passe par
    `reserver_numero_jit`, qui reprend un numéro abandonné par CETTE même
    machine plutôt que d'en brûler un nouveau (voir CLAUDE.md,
    « Numérotation résiliente ») ; toute autre quantité (palier 2, pool de
    secours) réserve normalement un bloc frais. Communique aussi
    `n_postes_actifs`/`rang` : cette requête vaut aussi heartbeat, comme les
    référentiels descendants."""
    machine_id = corps.machine_id or identite.machine
    try:
        if corps.quantite == 1:
            numeros = [facturation.reserver_numero_jit(machine_id)]
        else:
            numeros = facturation.reserver_bloc_numeros(
                corps.quantite, machine_id=machine_id)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    n, rang = facturation.info_activite(machine_id)
    return ReserverNumerosOut(numeros=numeros, n_postes_actifs=n, rang=rang)


@routeur_sync.get("/factures/dernier-numero", response_model=DernierNumeroOut)
def dernier_numero(
    identite: Identite = Depends(exiger_role("role_facturation")),
    facturation: FacturationService = Depends(obtenir_facturation),
) -> DernierNumeroOut:
    """Lecture seule, sans verrou — sondage continu (palier 1, toutes les
    3-5s) alimentant le numéro suggéré côté machine de facturation. Vaut
    aussi heartbeat, comme les référentiels descendants (voir CLAUDE.md,
    « Numérotation résiliente »)."""
    facturation.toucher_activite(identite.machine)
    return DernierNumeroOut(dernier_numero=facturation.dernier_numero_connu())


@routeur_sync.get("/referentiels/produits", response_model=list[ProduitReferentielOut])
def referentiel_produits(
    identite: Identite = Depends(exiger_role("role_facturation")),
    facturation: FacturationService = Depends(obtenir_facturation),
) -> list[ProduitReferentielOut]:
    # Heartbeat (numérotation résiliente) porté par ce canal déjà existant,
    # sans requête dédiée — voir CLAUDE.md, « Numérotation résiliente ».
    facturation.toucher_activite(identite.machine)
    return [
        ProduitReferentielOut(
            nom=p.nom, type_option=p.type_option, valeur_option=p.valeur_option,
            prix=p.prix, actif=p.actif, quantite_stock=p.quantite_stock,
            id_serveur=p.id,
        )
        for p in facturation.lister_referentiel_produits()
    ]


@routeur_sync.get("/referentiels/clients", response_model=list[ClientReferentielOut])
def referentiel_clients(
    identite: Identite = Depends(exiger_role("role_facturation")),
    facturation: FacturationService = Depends(obtenir_facturation),
) -> list[ClientReferentielOut]:
    facturation.toucher_activite(identite.machine)
    return [ClientReferentielOut(**c) for c in facturation.lister_referentiel_clients()]


@routeur_sync.post("/sync/operation", response_model=OperationSyncOut)
def recevoir_operation(
    corps: OperationSyncIn,
    identite: Identite = Depends(exiger_role("role_facturation")),
) -> OperationSyncOut:
    """Rejoue une opération de la file de synchronisation montante. Passe par
    la même file FIFO que les versements : chaque tâche ouvre sa propre
    connexion SQLite dans le thread worker, jamais celle du thread de requête."""

    def _tache():
        conn = creer_connexion()
        try:
            return SyncReceptionService(conn).rejouer(
                corps.type_operation, corps.cle_correlation, corps.payload,
                machine_id=identite.machine, cree_le=corps.cree_le)
        finally:
            conn.close()

    try:
        resultat = obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return OperationSyncOut(**resultat)
