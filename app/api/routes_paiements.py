"""Endpoints Paiements (versements, remises, recherche client) — première
brèche dans une API jusque-là 100% lecture seule (voir `app/api/routes.py`,
qui reste inchangé). Les écritures sont ici **rôle-aware** :

- versements : écriture réservée à `role_client` (403 pour `role_principal`).
- remise par facture : écriture réservée à `role_principal` (403 pour
  `role_client`) — c'est l'app principale qui écrit les factures, donc leur
  remise ; tracée (`remise_modifiee_par`).
- remise annuelle : écriture ouverte aux deux rôles (gérée par l'app
  cliente, consultable/modifiable aussi côté principal) ; tracée (`modifie_par`).
- lecture (factures/soldes/historique/totaux/synthèse/recherche client) :
  ouverte aux deux rôles.

Voir CLAUDE.md, section « Paiements », pour le modèle de droits complet.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import Identite, exiger_role, identifier, verifier_token
from app.api.deps import obtenir_paiements
from app.api.schemas import (
    ClientResumeOut,
    FacturePaiementDetailOut,
    FactureSoldeResumeOut,
    ImportLegacyIn,
    ImportLegacyOut,
    LigneIgnoreeImportOut,
    LigneVenteOut,
    RemiseAnnuelleIn,
    RemiseAnnuelleOut,
    RemiseFactureIn,
    SoldeFactureOut,
    SyntheseClientOut,
    TotauxPaiementsOut,
    VersementIn,
    VersementOut,
)
from app.api.write_queue import obtenir_file
from app.repositories.base_repository import creer_connexion
from app.services.import_paiements_legacy_service import (
    ImporterPaiementsLegacyService,
    LigneImportLegacy,
)
from app.services.paiement_service import PaiementService
from app.utils.validation import ErreurMetier

routeur_paiements = APIRouter(prefix="/paiements", dependencies=[Depends(verifier_token)])
routeur_clients = APIRouter(prefix="/clients", dependencies=[Depends(verifier_token)])


def _versement_out(v) -> VersementOut:
    return VersementOut(
        id=v.id, facture_id=v.facture_id, date_versement=v.date_versement,
        montant=v.montant, machine_origine=v.machine_origine,
        role_origine=v.role_origine, remarque=v.remarque, created_at=v.created_at,
    )


def _solde_out(s) -> SoldeFactureOut:
    return SoldeFactureOut(
        facture_id=s.facture_id, total=s.total, verse=s.verse, restant=s.restant,
    )


@routeur_paiements.get("/factures", response_model=list[FactureSoldeResumeOut])
def lister_factures_paiements(
    recherche: str = "",
    client_id: int | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    paiements: PaiementService = Depends(obtenir_paiements),
) -> list[FactureSoldeResumeOut]:
    """Factures usine avec solde, filtrables par nom client/numéro de facture
    et par période (`date_debut`/`date_fin` — sert notamment la page « Vue
    client », qui filtre les factures d'un client sur une période précise).
    `inclure_archivees=True` : chaque application gère son propre système
    d'archivage (voir CLAUDE.md, section « Archivage ») — l'archivage de
    l'application principale ne masque pas de factures au poste distant."""
    resultat = paiements.lister_avec_solde(
        recherche=recherche, client_id=client_id, date_debut=date_debut,
        date_fin=date_fin, inclure_archivees=True,
    )
    return [
        FactureSoldeResumeOut(
            id=facture.id, numero=facture.numero, date_facture=facture.date_facture,
            client_nom=facture.client_nom, destination=facture.destination,
            telephone=facture.telephone,
            total=solde.total, verse=solde.verse, restant=solde.restant,
        )
        for facture, solde in resultat
    ]


def _facture_ou_404(paiements: PaiementService, facture_id: int):
    facture = paiements.obtenir_facture(facture_id)
    if facture is None:
        raise HTTPException(status_code=404, detail="Facture introuvable.")
    solde = paiements.calculer_solde_facture(facture_id)
    return facture, solde


@routeur_paiements.get("/facture/{facture_id}", response_model=FacturePaiementDetailOut)
def obtenir_facture_paiement(
    facture_id: int,
    paiements: PaiementService = Depends(obtenir_paiements),
) -> FacturePaiementDetailOut:
    """Détail d'une facture pour la page Paiements / Vue client : en-tête,
    solde, historique des versements et contenu (lignes)."""
    facture, solde = _facture_ou_404(paiements, facture_id)
    versements = paiements.historique_versements(facture_id)
    return FacturePaiementDetailOut(
        id=facture.id, numero=facture.numero, date_facture=facture.date_facture,
        client_nom=facture.client_nom, destination=facture.destination,
        remise_taux=facture.remise_taux,
        remise_modifiee_par=facture.remise_modifiee_par,
        remise_modifiee_le=facture.remise_modifiee_le,
        solde=_solde_out(solde),
        versements=[_versement_out(v) for v in versements],
        lignes=[
            LigneVenteOut(
                designation=l.designation,
                quantite=l.quantite, prix_unitaire=l.prix_unitaire,
                total=l.total, remarque=l.remarque,
            )
            for l in facture.lignes
        ],
    )


@routeur_paiements.post("/facture/{facture_id}/versement", response_model=VersementOut)
def creer_versement(
    facture_id: int,
    corps: VersementIn,
    identite: Identite = Depends(exiger_role("role_client")),
) -> VersementOut:
    """Enregistre un versement — réservé à `role_client` (403 sinon). Passe
    par la file FIFO : chaque tâche ouvre sa propre connexion SQLite dans le
    thread worker, jamais celle du thread de requête."""

    def _tache():
        conn = creer_connexion()
        try:
            return PaiementService(conn).enregistrer_versement(
                facture_id, corps.montant, corps.date_versement,
                machine_origine=identite.machine, role_origine=identite.role,
                remarque=corps.remarque,
            )
        finally:
            conn.close()

    try:
        versement = obtenir_file().executer(_tache)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return _versement_out(versement)


@routeur_paiements.post("/import-legacy", response_model=ImportLegacyOut)
def importer_paiements_legacy(
    corps: ImportLegacyIn,
    identite: Identite = Depends(exiger_role("role_client")),
) -> ImportLegacyOut:
    """Import ponctuel d'un résumé de paiements historiques (facture
    « coquille » + versement par ligne) — réservé à `role_client`, seul rôle
    déjà autorisé en écriture sur les paiements. Traite tout le lot en une
    seule tâche FIFO (potentiellement de nombreuses lignes) plutôt qu'un
    appel par ligne — acceptable : outil de migration ponctuelle, pas une
    opération fréquente. Voir CLAUDE.md, section « Import des paiements
    historiques »."""

    def _tache():
        conn = creer_connexion()
        try:
            lignes = [
                LigneImportLegacy(
                    numero=l.numero, date_facture=l.date_facture,
                    client_nom=l.client_nom, montant=l.montant,
                    versement=l.versement, commentaire=l.commentaire,
                )
                for l in corps.lignes
            ]
            return ImporterPaiementsLegacyService(conn).importer(lignes)
        finally:
            conn.close()

    rapport = obtenir_file().executer(_tache)
    return ImportLegacyOut(
        importees=rapport.importees,
        ignorees=[LigneIgnoreeImportOut(numero=l.numero, raison=l.raison)
                 for l in rapport.ignorees],
        avertissements=[LigneIgnoreeImportOut(numero=l.numero, raison=l.raison)
                        for l in rapport.avertissements],
    )


@routeur_paiements.post("/facture/{facture_id}/remise")
def appliquer_remise_facture(
    facture_id: int,
    corps: RemiseFactureIn,
    identite: Identite = Depends(exiger_role("role_principal")),
    paiements: PaiementService = Depends(obtenir_paiements),
) -> dict:
    """Applique/modifie la remise ponctuelle d'une facture — réservé à
    `role_principal` (403 pour `role_client`) : c'est l'application
    principale qui écrit les factures et donc leur remise, l'app cliente ne
    gère que la remise **annuelle** (voir `appliquer_remise_annuelle` et
    CLAUDE.md, section « Paiements »)."""
    try:
        paiements.appliquer_remise_facture(facture_id, corps.remise_taux, identite.role)
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return {"statut": "ok"}


@routeur_clients.post("/{client_id}/remise-annuelle", response_model=RemiseAnnuelleOut)
def appliquer_remise_annuelle(
    client_id: int,
    corps: RemiseAnnuelleIn,
    identite: Identite = Depends(identifier),
    paiements: PaiementService = Depends(obtenir_paiements),
) -> RemiseAnnuelleOut:
    """Applique/modifie la remise annuelle d'un client — les deux rôles
    peuvent écrire, avec traçabilité."""
    try:
        remise = paiements.appliquer_remise_annuelle(
            client_id, corps.annee, corps.ca_annuel, corps.taux, corps.note,
            identite.role,
        )
    except ErreurMetier as exc:
        raise HTTPException(status_code=400, detail=exc.cle_message) from exc
    return RemiseAnnuelleOut(
        id=remise.id, client_id=remise.client_id, annee=remise.annee,
        ca_annuel=remise.ca_annuel, taux=remise.taux, montant=remise.montant,
        note=remise.note, modifie_par=remise.modifie_par, modifie_le=remise.modifie_le,
    )


@routeur_paiements.get("/totaux", response_model=TotauxPaiementsOut)
def totaux_paiements(
    date_debut: date | None = None,
    date_fin: date | None = None,
    client_id: int | None = None,
    paiements: PaiementService = Depends(obtenir_paiements),
) -> TotauxPaiementsOut:
    totaux = paiements.totaux_globaux(
        date_debut=date_debut, date_fin=date_fin, client_id=client_id,
        inclure_archivees=True,
    )
    return TotauxPaiementsOut(
        total_facture=totaux.total_facture, total_verse=totaux.total_verse,
        total_restant=totaux.total_restant,
    )


@routeur_paiements.get("/client/{client_id}/synthese", response_model=SyntheseClientOut)
def synthese_client(
    client_id: int,
    annee: int | None = None,
    date_debut: date | None = None,
    date_fin: date | None = None,
    paiements: PaiementService = Depends(obtenir_paiements),
) -> SyntheseClientOut:
    """`date_debut`/`date_fin` permettent de bien définir une période précise
    (ex. un mois), prioritaire sur `annee` dès que l'une des deux est fournie."""
    synthese = paiements.total_depense_par_client(
        client_id, annee=annee, date_debut=date_debut, date_fin=date_fin)
    return SyntheseClientOut(
        total_facture=synthese.total_facture, total_verse=synthese.total_verse,
        total_restant=synthese.total_restant, total_remises=synthese.total_remises,
    )


@routeur_clients.get("/recherche", response_model=list[ClientResumeOut])
def rechercher_clients(
    q: str = "",
    paiements: PaiementService = Depends(obtenir_paiements),
) -> list[ClientResumeOut]:
    """Recherche client en lecture seule (nom/adresse/téléphone) — les deux
    rôles."""
    return [
        ClientResumeOut(id=c.id, nom=c.nom, adresse=c.adresse)
        for c in paiements.rechercher_clients(q)
    ]
