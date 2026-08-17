"""Endpoints d'administration à distance (Archive) — réservés au rôle
`role_facturation` : c'est la machine de facturation, configurée en mode
« facturation à distance », qui les consomme. Le suivi des marges, les
« factures clients » (revendeurs) et l'import Excel ont été retirés : il
n'existe plus qu'un seul type de facture, et l'import Excel n'est plus une
fonctionnalité de l'application. Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.api.auth import exiger_role
from app.api.deps import obtenir_facturation, obtenir_pdf
from app.api.schemas import (
    ArchiveResultatOut,
    ArchiverIdsIn,
    ArchiverPeriodeIn,
    FactureAdminResumeOut,
    FactureDetailOut,
    LigneVenteOut,
    StatutArchivageIn,
    StatutArchivageOut,
)
from app.api.write_queue import obtenir_file
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService

routeur_admin = APIRouter(prefix="/admin", dependencies=[Depends(exiger_role("role_facturation"))])


def _facture_ou_404(facturation: FacturationService, facture_id: int):
    facture = facturation.obtenir_facture(facture_id)
    if facture is None:
        raise HTTPException(status_code=404, detail="Facture introuvable.")
    return facture


def _facture_detail_out(facture) -> FactureDetailOut:
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


# Archive ---------------------------------------------------------------------
@routeur_admin.get("/factures", response_model=list[FactureAdminResumeOut])
def lister_factures_admin(
    archivee: bool | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    client_id: int | None = None,
    facturation: FacturationService = Depends(obtenir_facturation),
) -> list[FactureAdminResumeOut]:
    """Équivalent distant de `ArchiveView.rafraichir()` : toutes les factures
    (actives et archivées), filtrables par statut d'archivage."""
    factures = facturation.lister_factures(
        date_debut=date_debut, date_fin=date_fin, client_id=client_id,
        inclure_archivees=True,
    )
    if archivee is not None:
        factures = [f for f in factures if f.archivee == archivee]
    return [
        FactureAdminResumeOut(
            id=f.id, numero=f.numero, date_facture=f.date_facture,
            client_nom=f.client_nom, destination=f.destination,
            telephone=f.telephone,
            total=f.total_liste, remise_taux=f.remise_taux, nb_lignes=f.nb_lignes,
            archivee=f.archivee,
        )
        for f in factures
    ]


@routeur_admin.get("/factures/{facture_id}", response_model=FactureDetailOut)
def obtenir_facture_admin(
    facture_id: int,
    facturation: FacturationService = Depends(obtenir_facturation),
) -> FactureDetailOut:
    """Détail d'une facture — équivalent `role_facturation` de
    `GET /factures/{id}` (`routes.py`), inaccessible à ce rôle."""
    return _facture_detail_out(_facture_ou_404(facturation, facture_id))


@routeur_admin.get("/factures/{facture_id}/pdf")
def telecharger_pdf_admin(
    facture_id: int,
    facturation: FacturationService = Depends(obtenir_facturation),
    pdf: PdfService = Depends(obtenir_pdf),
) -> FileResponse:
    facture = _facture_ou_404(facturation, facture_id)
    chemin = pdf.generer_facture(facture)
    return FileResponse(chemin, media_type="application/pdf", filename=chemin.name)


@routeur_admin.get("/factures/{facture_id}/bordereau")
def telecharger_bordereau_admin(
    facture_id: int,
    facturation: FacturationService = Depends(obtenir_facturation),
    pdf: PdfService = Depends(obtenir_pdf),
) -> FileResponse:
    facture = _facture_ou_404(facturation, facture_id)
    chemin = pdf.generer_bordereau(facture)
    return FileResponse(chemin, media_type="application/pdf", filename=chemin.name)


def _tache_archivage(fonction_service: str, *args):
    def _tache():
        conn = creer_connexion()
        try:
            methode = getattr(FacturationService(conn), fonction_service)
            return methode(*args)
        finally:
            conn.close()
    return obtenir_file().executer(_tache)


@routeur_admin.post("/factures/archiver-ids", response_model=ArchiveResultatOut)
def archiver_ids(corps: ArchiverIdsIn) -> ArchiveResultatOut:
    return ArchiveResultatOut(nb=_tache_archivage("archiver_ids", corps.ids))


@routeur_admin.post("/factures/desarchiver-ids", response_model=ArchiveResultatOut)
def desarchiver_ids(corps: ArchiverIdsIn) -> ArchiveResultatOut:
    return ArchiveResultatOut(nb=_tache_archivage("desarchiver_ids", corps.ids))


@routeur_admin.post("/factures/archiver-periode", response_model=ArchiveResultatOut)
def archiver_periode(corps: ArchiverPeriodeIn) -> ArchiveResultatOut:
    return ArchiveResultatOut(nb=_tache_archivage(
        "archiver_periode", corps.date_debut, corps.date_fin, corps.client_id))


@routeur_admin.post("/factures/desarchiver-periode", response_model=ArchiveResultatOut)
def desarchiver_periode(corps: ArchiverPeriodeIn) -> ArchiveResultatOut:
    return ArchiveResultatOut(nb=_tache_archivage(
        "desarchiver_periode", corps.date_debut, corps.date_fin, corps.client_id))


@routeur_admin.post("/factures/statut-archivage", response_model=StatutArchivageOut)
def statut_archivage(
    corps: StatutArchivageIn,
    facturation: FacturationService = Depends(obtenir_facturation),
) -> StatutArchivageOut:
    """Parmi les numéros connus localement par une machine de facturation,
    indique lesquels sont actuellement archivés sur le boss — alimente la
    synchronisation descendante du statut d'archivage
    (`app/sync/archive_worker.py::ArchiveStatutSyncWorker`), pour que
    l'historique local masque aussi les factures archivées après coup."""
    return StatutArchivageOut(numeros_archives=facturation.numeros_archives(corps.numeros))
