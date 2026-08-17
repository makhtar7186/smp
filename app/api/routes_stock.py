"""Endpoints de gestion de stock — réservés au rôle `role_stock` : c'est
l'app Stock (poste dédié à l'entrepôt) qui les consomme. Catalogue en
lecture, création de produits + entrées/ajustements en écriture (via la file
FIFO, même schéma que les versements dans `routes_paiements.py`), historique
par produit. Voir `app/services/stock_service.py::StockService` pour la
logique métier — jamais touchée directement ici."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import Identite, exiger_role
from app.api.deps import obtenir_stock
from app.api.schemas import (
    AjustementStockIn,
    EntreeStockIn,
    MouvementStockOut,
    ProduitCreationIn,
    ProduitModificationIn,
    ProduitStockOut,
)
from app.api.write_queue import obtenir_file
from app.repositories.base_repository import creer_connexion
from app.services.stock_service import StockService
from app.utils.validation import ErreurMetier

routeur_stock = APIRouter(prefix="/stock", dependencies=[Depends(exiger_role("role_stock"))])


def _produit_out(p) -> ProduitStockOut:
    return ProduitStockOut(
        id=p.id, nom=p.nom, type_option=p.type_option, valeur_option=p.valeur_option,
        prix=p.prix, actif=p.actif, quantite_stock=p.quantite_stock,
    )


def _mouvement_out(m) -> MouvementStockOut:
    return MouvementStockOut(
        id=m.id, produit_id=m.produit_id, type_mouvement=m.type_mouvement,
        quantite=m.quantite, reference=m.reference, source=m.source,
        machine_id=m.machine_id, cree_le=m.cree_le,
    )


@routeur_stock.get("/produits", response_model=list[ProduitStockOut])
def lister_produits(
    stock: StockService = Depends(obtenir_stock),
) -> list[ProduitStockOut]:
    """Catalogue complet (actifs et inactifs) avec la quantité en stock
    courante de chaque article."""
    return [_produit_out(p) for p in stock.lister_produits()]


@routeur_stock.post("/produits", response_model=ProduitStockOut)
def creer_produit(
    corps: ProduitCreationIn,
    identite: Identite = Depends(exiger_role("role_stock")),
) -> ProduitStockOut:
    """Ajoute un nouvel article au catalogue (stock initial à 0) — seule voie
    de création désormais, la facturation ne créant plus de produit à la
    volée. Même sérialisation FIFO que les entrées/ajustements."""

    def _tache():
        conn = creer_connexion()
        try:
            return StockService(conn).creer_produit(
                corps.nom, corps.type_option, corps.valeur_option, corps.prix)
        finally:
            conn.close()

    try:
        produit = obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return _produit_out(produit)


@routeur_stock.put("/produits/{produit_id}", response_model=ProduitStockOut)
def modifier_produit(
    produit_id: int,
    corps: ProduitModificationIn,
    identite: Identite = Depends(exiger_role("role_stock")),
) -> ProduitStockOut:
    """Modifie nom/option d'un article existant — jamais son prix (réglage
    exclusif de l'app Facturation). Même sérialisation FIFO."""

    def _tache():
        conn = creer_connexion()
        try:
            return StockService(conn).modifier_produit(
                produit_id, corps.nom, corps.type_option, corps.valeur_option)
        finally:
            conn.close()

    try:
        produit = obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return _produit_out(produit)


@routeur_stock.delete("/produits/{produit_id}", response_model=None)
def supprimer_produit(
    produit_id: int,
    identite: Identite = Depends(exiger_role("role_stock")),
) -> dict:
    """Supprime un article du catalogue — refusé (400) s'il est encore
    référencé par des ventes déjà enregistrées. Même sérialisation FIFO."""

    def _tache():
        conn = creer_connexion()
        try:
            StockService(conn).supprimer_produit(produit_id)
        finally:
            conn.close()

    try:
        obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return {"statut": "ok"}


@routeur_stock.post("/produits/{produit_id}/entree", response_model=MouvementStockOut)
def entrer_stock(
    produit_id: int,
    corps: EntreeStockIn,
    identite: Identite = Depends(exiger_role("role_stock")),
) -> MouvementStockOut:
    """Enregistre une entrée (approvisionnement) — quantité strictement
    positive. Passe par la file FIFO : chaque tâche ouvre sa propre connexion
    SQLite dans le thread worker, jamais celle du thread de requête."""

    def _tache():
        conn = creer_connexion()
        try:
            return StockService(conn).entrer_stock(
                produit_id, corps.quantite, note=corps.note,
                machine_id=identite.machine)
        finally:
            conn.close()

    try:
        mouvement = obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return _mouvement_out(mouvement)


@routeur_stock.post("/produits/{produit_id}/ajustement", response_model=MouvementStockOut)
def ajuster_stock(
    produit_id: int,
    corps: AjustementStockIn,
    identite: Identite = Depends(exiger_role("role_stock")),
) -> MouvementStockOut:
    """Enregistre un ajustement correctif (delta signé, ex. après un
    inventaire physique) — même sérialisation FIFO que les entrées."""

    def _tache():
        conn = creer_connexion()
        try:
            return StockService(conn).ajuster_stock(
                produit_id, corps.delta, motif=corps.motif,
                machine_id=identite.machine)
        finally:
            conn.close()

    try:
        mouvement = obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return _mouvement_out(mouvement)


@routeur_stock.get("/produits/{produit_id}/historique", response_model=list[MouvementStockOut])
def historique_stock(
    produit_id: int,
    stock: StockService = Depends(obtenir_stock),
) -> list[MouvementStockOut]:
    """Mouvements d'un produit, les plus récents d'abord."""
    return [_mouvement_out(m) for m in stock.historique(produit_id)]
