"""Application FastAPI : montage des routes de l'accès distant.

`routes.py` (historique des factures + PDF) reste 100% lecture seule,
accessible aux deux rôles. `routes_paiements.py` ajoute la gestion des
paiements (versements, remises, recherche client), avec des permissions
**par ressource** : l'écriture de versements est réservée à `role_client`,
tandis que les remises (par facture et annuelle) sont partagées entre les
deux rôles. `routes_stock.py` (rôle `role_stock`) expose le catalogue et le
journal de stock (entrées/ajustements) à l'app Stock. Voir CLAUDE.md, section
« Accès distant »."""
from __future__ import annotations

from fastapi import FastAPI

from app.api.routes import routeur
from app.api.routes_admin import routeur_admin
from app.api.routes_paiements import routeur_clients, routeur_paiements
from app.api.routes_stats import routeur_remises_lecture, routeur_stats
from app.api.routes_stock import routeur_stock
from app.api.routes_sync import routeur_sync

app = FastAPI(
    title="Accès distant",
    description="Consultation/impression de l'historique des factures "
                 "et gestion des paiements (versements, remises) depuis un "
                 "poste distant, via Tailscale. Permissions par ressource : "
                 "voir le tableau des rôles dans CLAUDE.md.",
    version="1.4.0",
)
app.include_router(routeur)
app.include_router(routeur_paiements)
app.include_router(routeur_clients)
app.include_router(routeur_sync)
app.include_router(routeur_stats)
app.include_router(routeur_remises_lecture)
app.include_router(routeur_admin)
app.include_router(routeur_stock)


@app.get("/health")
def sante() -> dict:
    """Sans authentification : sert uniquement à distinguer, côté client,
    « machine injoignable » de « jeton invalide »."""
    return {"statut": "ok"}
