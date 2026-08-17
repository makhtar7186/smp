"""Import ponctuel des paiements historiques (App Client), depuis un fichier
Excel de l'ancien système qui ne conserve pas les factures sous forme de
liste exploitable — seul un résumé par facture (date, numéro, client,
montant, versement) est réimportable. Voir CLAUDE.md, section « Import des
paiements historiques ».

Crée, pour chaque ligne, une facture « coquille » (une seule ligne de vente
synthétique portant le montant total, sans produit ni mouvement de stock) et
le versement correspondant si renseigné — jamais via `FacturationService`,
qui appliquerait la TVA courante, auto-créerait un produit au catalogue et
décrémenterait le stock, tout cela non pertinent pour un montant historique."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from app.models import Facture, LigneVente
from app.repositories.client_repository import ClientRepository
from app.repositories.facture_repository import FactureRepository
from app.services.paiement_service import PaiementService

_DESIGNATION_LIGNE_IMPORT = "Import historique"


@dataclass
class LigneImportLegacy:
    """Une ligne du résumé de paiements historiques (déjà validée/parsée côté
    App Client — un numéro/montant non numérique dans le fichier source ne
    doit jamais atteindre ce service)."""

    numero: int
    date_facture: date
    client_nom: str
    montant: int
    versement: int = 0
    commentaire: str = ""


@dataclass
class LigneIgnoreeImport:
    numero: int
    raison: str  # clé i18n : 'numero_invalide' | 'montant_invalide' | 'numero_deja_utilise'


@dataclass
class RapportImportLegacy:
    importees: int = 0
    ignorees: list[LigneIgnoreeImport] = field(default_factory=list)
    avertissements: list[LigneIgnoreeImport] = field(default_factory=list)


class ImporterPaiementsLegacyService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._factures = FactureRepository(conn)
        self._clients = ClientRepository(conn)
        self._paiements = PaiementService(conn)

    def importer(self, lignes: list[LigneImportLegacy]) -> RapportImportLegacy:
        """Traite les lignes dans l'ordre, une facture par ligne. Une ligne en
        échec (numéro déjà utilisé, montant invalide) est ignorée et
        reportée — n'interrompt jamais le reste du lot.

        Seule l'unicité du numéro est exigée (contrainte `UNIQUE` déjà en
        base, voir `idx_factures_numero_unique`) — **pas** que le numéro
        importé soit inférieur au plus haut numéro réel déjà utilisé : dans
        la pratique, la numérotation de l'ancien système et celle de ce
        système démarrent souvent chacune à des petits nombres proches, donc
        les deux plages se chevauchent normalement (une précédente version
        de cette vérification rejetait à tort des lignes historiques
        légitimes pour cette raison). La numérotation de ce système reste de
        toute façon « auto-incrémentée mais modifiable » (voir CLAUDE.md,
        section 1) : un import qui fait avancer le plus haut numéro connu
        n'est pas une violation d'invariant, juste un écart de numérotation
        déjà accepté ailleurs dans l'application."""
        rapport = RapportImportLegacy()
        for ligne in lignes:
            raison = self._verifier(ligne)
            if raison is not None:
                rapport.ignorees.append(LigneIgnoreeImport(ligne.numero, raison))
                continue
            try:
                self._importer_ligne(ligne)
            except sqlite3.IntegrityError:
                rapport.ignorees.append(
                    LigneIgnoreeImport(ligne.numero, "numero_deja_utilise"))
                continue
            rapport.importees += 1
        return rapport

    def _verifier(self, ligne: LigneImportLegacy) -> str | None:
        if ligne.numero <= 0:
            return "numero_invalide"
        if ligne.montant <= 0:
            return "montant_invalide"
        return None

    def _importer_ligne(self, ligne: LigneImportLegacy) -> None:
        client = self._clients.obtenir_ou_creer(ligne.client_nom, adresse="")
        facture = Facture(
            numero=ligne.numero,
            date_facture=ligne.date_facture,
            client_id=client.id,
            client_nom=client.nom,
            remise_taux=0.0,
            tva_taux=0.0,  # jamais réappliquer la TVA courante à un montant historique
            lignes=[LigneVente(
                designation=_DESIGNATION_LIGNE_IMPORT,
                quantite=1, prix_unitaire=ligne.montant,
            )],
        )
        self._factures.enregistrer(facture, ventes_stock=None)
        if ligne.versement:
            self._paiements.enregistrer_versement(
                facture.id, ligne.versement, ligne.date_facture,
                machine_origine="import_legacy", role_origine="import_legacy",
                remarque=ligne.commentaire,
            )
