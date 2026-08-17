"""Endpoints en lecture seule : historique des factures + PDF associés.

Ce routeur reste 100% lecture seule (les écritures — versements, remises —
vivent dans `app/api/routes_paiements.py`). Chaque endpoint délègue à
`FacturationService`/`PdfService` (jamais aux repositories directement),
comme le reste de l'application. Il n'existe plus qu'un seul type de
facture (voir CLAUDE.md) — toute facture enregistrée est exposée ici."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.auth import verifier_token
from app.api.deps import obtenir_facturation, obtenir_pdf
from app.api.schemas import FactureDetailOut, FactureResumeOut, LigneVenteOut
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService

routeur = APIRouter(dependencies=[Depends(verifier_token)])


def _facture_ou_404(facturation: FacturationService, facture_id: int):
    facture = facturation.obtenir_facture(facture_id)
    if facture is None:
        raise HTTPException(status_code=404, detail="Facture introuvable.")
    return facture


@routeur.get("/factures", response_model=list[FactureResumeOut])
def lister_factures(
    date_debut: date | None = None,
    date_fin: date | None = None,
    client_id: int | None = None,
    facturation: FacturationService = Depends(obtenir_facturation),
) -> list[FactureResumeOut]:
    """Historique des factures, filtrable par période et client — mêmes
    filtres que la vue « Historique ventes » de l'application principale.

    `inclure_archivees=True` : chaque application gère son **propre** système
    d'archivage (voir CLAUDE.md, section « Archivage ») — l'archivage de
    l'application principale (`FacturationService.archiver_ids`, page
    « Archive ») ne doit pas masquer des factures au poste distant, qui gère
    son propre archivage local (`app/client/archive_client.py`), indépendant."""
    factures = facturation.lister_factures(
        date_debut=date_debut, date_fin=date_fin, client_id=client_id,
        inclure_archivees=True,
    )
    return [
        FactureResumeOut(
            id=f.id, numero=f.numero, date_facture=f.date_facture,
            client_nom=f.client_nom, destination=f.destination,
            telephone=f.telephone,
            total=f.total_liste, remise_taux=f.remise_taux, nb_lignes=f.nb_lignes,
        )
        for f in factures
    ]


@routeur.get("/factures/{facture_id}", response_model=FactureDetailOut)
def obtenir_facture(
    facture_id: int,
    facturation: FacturationService = Depends(obtenir_facturation),
) -> FactureDetailOut:
    """Détail d'une facture (en-tête + lignes)."""
    facture = _facture_ou_404(facturation, facture_id)
    return FactureDetailOut(
        id=facture.id, numero=facture.numero, date_facture=facture.date_facture,
        client_nom=facture.client_nom, destination=facture.destination,
        etabli_par=facture.etabli_par, remise_taux=facture.remise_taux,
        total=facture.total, remise_montant=facture.remise_montant,
        total_net=facture.total_net,
        lignes=[
            LigneVenteOut(
                designation=l.designation,
                quantite=l.quantite, prix_unitaire=l.prix_unitaire,
                total=l.total, remarque=l.remarque,
            )
            for l in facture.lignes
        ],
    )


@routeur.get("/factures/{facture_id}/pdf")
def telecharger_pdf(
    facture_id: int,
    facturation: FacturationService = Depends(obtenir_facturation),
    pdf: PdfService = Depends(obtenir_pdf),
) -> FileResponse:
    """PDF de la facture (régénéré à la demande depuis la base), pour
    impression depuis le poste distant."""
    facture = _facture_ou_404(facturation, facture_id)
    chemin = pdf.generer_facture(facture)
    return FileResponse(chemin, media_type="application/pdf", filename=chemin.name)


@routeur.get("/factures/{facture_id}/bordereau")
def telecharger_bordereau(
    facture_id: int,
    facturation: FacturationService = Depends(obtenir_facturation),
    pdf: PdfService = Depends(obtenir_pdf),
) -> FileResponse:
    """Bordereau de livraison PDF (mêmes lignes, sans prix)."""
    facture = _facture_ou_404(facturation, facture_id)
    chemin = pdf.generer_bordereau(facture)
    return FileResponse(chemin, media_type="application/pdf", filename=chemin.name)
