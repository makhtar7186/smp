"""Schémas Pydantic exposés par l'API — projections en lecture seule des
modèles métier (`app.models`), jamais les dataclasses elles-mêmes."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class LigneVenteOut(BaseModel):
    designation: str
    quantite: float
    prix_unitaire: int
    total: int
    remarque: str = ""


class FactureResumeOut(BaseModel):
    """Une ligne de l'historique (sans le détail des lignes de vente)."""

    id: int
    numero: int
    date_facture: date
    client_nom: str
    destination: str
    telephone: str = ""
    total: int
    remise_taux: float
    nb_lignes: int


class FactureDetailOut(BaseModel):
    """Facture complète (en-tête + lignes) pour consultation/impression."""

    id: int
    numero: int
    date_facture: date
    client_nom: str
    destination: str
    etabli_par: str
    remise_taux: float
    total: int
    remise_montant: int
    total_net: int
    lignes: list[LigneVenteOut]


class ErreurOut(BaseModel):
    detail: str


# Paiements (versements) --------------------------------------------------------
class VersementIn(BaseModel):
    montant: int
    date_versement: date
    remarque: str = ""


class VersementOut(BaseModel):
    id: int
    facture_id: int
    date_versement: date
    montant: int
    machine_origine: str
    role_origine: str
    remarque: str
    created_at: str


class SoldeFactureOut(BaseModel):
    facture_id: int
    total: int
    verse: int
    restant: int


class FactureSoldeResumeOut(BaseModel):
    """Ligne de la liste `/paiements/factures` : facture + solde agrégé."""

    id: int
    numero: int
    date_facture: date
    client_nom: str
    destination: str
    telephone: str = ""
    total: int
    verse: int
    restant: int


class FacturePaiementDetailOut(BaseModel):
    """Détail d'une facture pour la page Paiements : en-tête, solde, historique."""

    id: int
    numero: int
    date_facture: date
    client_nom: str
    destination: str
    remise_taux: float
    remise_modifiee_par: str
    remise_modifiee_le: str
    solde: SoldeFactureOut
    versements: list[VersementOut]
    lignes: list[LigneVenteOut]


class RemiseFactureIn(BaseModel):
    remise_taux: float


class RemiseAnnuelleIn(BaseModel):
    annee: int
    ca_annuel: int
    taux: float
    note: str = ""


class RemiseAnnuelleOut(BaseModel):
    id: int
    client_id: int
    annee: int
    ca_annuel: int
    taux: float
    montant: int
    note: str
    modifie_par: str
    modifie_le: str


class TotauxPaiementsOut(BaseModel):
    total_facture: int
    total_verse: int
    total_restant: int


class SyntheseClientOut(BaseModel):
    total_facture: int
    total_verse: int
    total_restant: int
    total_remises: int


class ClientResumeOut(BaseModel):
    """Recherche client — volontairement minimal (nom + adresse), la
    recherche par téléphone étant gérée côté serveur (`ClientRepository.rechercher`)
    mais pas renvoyée ici (mêmes champs qu'avant l'évolution stock/plastique)."""

    id: int
    nom: str
    adresse: str


# Import des paiements historiques (App Client) ---------------------------------
class LigneImportLegacyIn(BaseModel):
    """Une ligne déjà validée côté App Client (numéro/montant numériques —
    voir `app/client/ui.py`, qui lit le fichier Excel local et filtre les
    lignes malformées avant l'envoi)."""

    numero: int
    date_facture: date
    client_nom: str
    montant: int
    versement: int = 0
    commentaire: str = ""


class ImportLegacyIn(BaseModel):
    lignes: list[LigneImportLegacyIn]


class LigneIgnoreeImportOut(BaseModel):
    numero: int
    raison: str


class ImportLegacyOut(BaseModel):
    importees: int
    ignorees: list[LigneIgnoreeImportOut]
    avertissements: list[LigneIgnoreeImportOut]


# Synchronisation offline-first (machine de facturation) -----------------------
class ReserverNumerosIn(BaseModel):
    quantite: int
    machine_id: str = ""


class DernierNumeroOut(BaseModel):
    """Lecture seule, sans verrou — voir `GET /factures/dernier-numero`,
    palier 1 (sondage continu) de la numérotation résiliente."""

    dernier_numero: int


class ReserverNumerosOut(BaseModel):
    numeros: list[int]
    # Numérotation résiliente (voir CLAUDE.md) : communiqués à chaque
    # réservation pour que la machine appelante puisse, en cas de coupure
    # prolongée, calculer elle-même un bloc supplémentaire sans collision
    # avec les autres postes (palier 3, bloc(k) = base + (r + k×N) × b).
    n_postes_actifs: int = 1
    rang: int = 0


class OperationSyncIn(BaseModel):
    type_operation: str
    cle_correlation: str = ""
    payload: dict
    cree_le: str = ""


class OperationSyncOut(BaseModel):
    statut: str
    id_correlation_serveur: int | None = None


class ProduitReferentielOut(BaseModel):
    """Référentiel produit synchronisé vers le cache local de la machine de
    facturation. `id_serveur` (l'id du produit côté boss) sert de clé de
    corrélation stable pour retrouver un produit renommé — la clé naturelle
    (nom, type_option, valeur_option) seule échouerait sinon, un produit
    renommé depuis l'app Stock devenant introuvable par son ancien nom (voir
    CLAUDE.md, section « Machine de facturation »)."""

    nom: str
    type_option: str
    valeur_option: str
    prix: int
    actif: bool
    quantite_stock: int
    id_serveur: int = 0


class KPIOut(BaseModel):
    valeur: int
    precedent: int
    variation_pct: float | None = None


class DashboardKpisOut(BaseModel):
    ca_jour: KPIOut
    ca_mois: KPIOut
    ca_annee: KPIOut
    nb_ventes: KPIOut
    panier_moyen: int


class TopProduitOut(BaseModel):
    libelle: str
    valeur: int


class RepartitionGammeOut(BaseModel):
    gamme: str
    ca: int


class SerieCaPointOut(BaseModel):
    periode: str
    ca: int


class RemiseLigneOut(BaseModel):
    client_id: int
    client_nom: str
    client_adresse: str
    ca_annuel: int
    taux: float
    montant: int
    note: str


# Admin distant (machine de facturation, role_facturation) -------------------
class FactureAdminResumeOut(BaseModel):
    id: int
    numero: int
    date_facture: date
    client_nom: str
    destination: str
    telephone: str = ""
    total: int
    remise_taux: float
    nb_lignes: int
    archivee: bool


class ArchiverIdsIn(BaseModel):
    ids: list[int]


class ArchiverPeriodeIn(BaseModel):
    date_debut: date
    date_fin: date
    client_id: int | None = None


class ArchiveResultatOut(BaseModel):
    nb: int


class StatutArchivageIn(BaseModel):
    """Numéros connus localement par une machine de facturation — sert à
    demander au boss lesquels sont actuellement archivés (synchronisation
    descendante du statut d'archivage, voir CLAUDE.md)."""

    numeros: list[int]


class StatutArchivageOut(BaseModel):
    numeros_archives: list[int]


class ClientReferentielOut(BaseModel):
    """Référentiel client synchronisé vers le cache local."""

    nom: str
    telephone: str
    adresse: str
    modifie_le: str = ""


# Stock (role_stock) -----------------------------------------------------------
class ProduitStockOut(BaseModel):
    """Article du catalogue avec sa quantité en stock courante — voir
    `app/services/stock_service.py::StockService.lister_produits`."""

    id: int
    nom: str
    type_option: str
    valeur_option: str
    prix: int
    actif: bool
    quantite_stock: int


class MouvementStockOut(BaseModel):
    """Une ligne du journal de stock (append-only) — voir
    `app/models/mouvement_stock.py::MouvementStock`."""

    id: int
    produit_id: int
    type_mouvement: str
    quantite: int
    reference: str
    source: str
    machine_id: str
    cree_le: str


class ProduitCreationIn(BaseModel):
    """Création d'un nouvel article de catalogue — voir
    `StockService.creer_produit`. Seule voie de création désormais (la
    facturation ne crée plus de produit à la volée)."""

    nom: str
    type_option: str = ""
    valeur_option: str = ""
    prix: int = 0


class ProduitModificationIn(BaseModel):
    """Modification (nom/option) d'un article existant — voir
    `StockService.modifier_produit`. Jamais de prix ici (réglage exclusif de
    l'app Facturation)."""

    nom: str
    type_option: str = ""
    valeur_option: str = ""


class EntreeStockIn(BaseModel):
    quantite: int
    note: str = ""


class AjustementStockIn(BaseModel):
    delta: int
    motif: str = ""
