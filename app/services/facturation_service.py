"""Service de facturation : numérotation continue, validation et enregistrement."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.models import Client, Facture, LigneVente, Produit
from app.repositories.client_repository import ClientRepository
from app.repositories.db_backend import debuter_transaction_exclusive
from app.repositories.facture_repository import FactureRepository
from app.repositories.machine_activite_repository import MachineActiviteRepository
from app.repositories.produit_repository import ProduitRepository
from app.repositories.reservation_repository import ReservationNumeroRepository
from app.utils.validation import ErreurValidation

_TYPE_FACTURE_RESERVATION = "usine"  # seul type existant — conservé pour le
                                      # sous-système de réservation de blocs
                                      # (voir CLAUDE.md, Machine de facturation)


class FacturationService:
    """Règles métier de la facturation."""

    def __init__(self, conn: sqlite3.Connection, *,
                 queue: "QueueSyncRepository | None" = None,
                 reservations: ReservationNumeroRepository | None = None) -> None:
        self._factures = FactureRepository(conn)
        self._clients = ClientRepository(conn)
        self._produits = ProduitRepository(conn)
        self._machines = MachineActiviteRepository(conn)
        self._queue = queue
        self._reservations = reservations

    # Numérotation ------------------------------------------------------------
    def _plancher_numero(self) -> int:
        """Plus haut numéro déjà utilisé OU déjà distribué en bloc à une
        machine de facturation — numérotation **continue** : jamais de remise
        à zéro ni de plafond."""
        return max(
            self._factures.dernier_numero() or 0,
            0 if self._reservations is None
            else (self._reservations.dernier_max_reserve(_TYPE_FACTURE_RESERVATION) or 0),
        )

    def prochain_numero(self) -> int:
        """Prochain numéro : simple incrément du plus haut numéro connu
        (facturé ou déjà réservé en bloc à une machine de facturation)."""
        return self._plancher_numero() + 1

    def dernier_numero_connu(self) -> int:
        """Plus haut numéro connu (facturé ou réservé), **sans aucun verrou**
        — lecture pure, jamais une réservation. Alimente le sondage continu
        du palier 1 (`GET /factures/dernier-numero`, appelé toutes les 3-5 s
        par `NumeroPollerWorker`) : contrairement à `reserver_bloc_numeros`,
        n'écrit rien et ne sérialise jamais les appels concurrents — voir
        CLAUDE.md, section « Numérotation résiliente »."""
        return self._plancher_numero()

    def reserver_bloc_numeros(self, quantite: int, machine_id: str = "") -> list[int]:
        """Réserve un bloc contigu de `quantite` numéros, consommable
        localement par une machine de facturation. Nécessite un
        `ReservationNumeroRepository` (boss uniquement)."""
        if self._reservations is None:
            raise ErreurValidation("sync_reservation_indisponible")
        if quantite <= 0:
            return []
        # Acquiert le verrou d'écriture sur reservations_numeros avant même la
        # lecture du plancher (BEGIN IMMEDIATE sur SQLite, LOCK TABLE ...
        # IN EXCLUSIVE MODE sur PostgreSQL) : deux machines demandant un bloc
        # au même instant sont ainsi strictement sérialisées.
        conn = self._reservations.conn
        debuter_transaction_exclusive(conn, "reservations_numeros")
        try:
            numero_min = self._plancher_numero() + 1
            numero_max = numero_min + quantite - 1
            self._reservations.reserver_bloc(
                _TYPE_FACTURE_RESERVATION, numero_min, numero_max, machine_id)
        except Exception:
            conn.rollback()
            raise
        return list(range(numero_min, numero_max + 1))

    def reserver_numero_jit(self, machine_id: str = "") -> int:
        """Réservation d'UN SEUL numéro (palier 1, JIT) — avec reprise d'un
        numéro abandonné : si la toute dernière réservation jamais faite
        (toutes machines confondues) est elle-même de taille 1, appartient à
        CETTE machine, et n'a donné lieu à aucune facture réelle, elle n'a
        pu être utilisée par personne d'autre (chaque réservation est
        exclusive à la machine qui l'a reçue) — on la propose de nouveau
        plutôt que d'avancer, pour ne jamais perdre un numéro à cause d'une
        session fermée sans facturer (ex. « Oui » au popup puis fermeture de
        l'app sans enregistrer). Volontairement restreint aux réservations
        de taille 1 : reprendre un BLOC (palier 2, pool de secours) serait
        risqué — le boss ne sait pas combien de numéros de ce bloc la
        machine a déjà silencieusement consommés dans son pool local. Sinon,
        réserve normalement le numéro suivant. Voir CLAUDE.md, section
        « Numérotation résiliente »."""
        if self._reservations is None:
            raise ErreurValidation("sync_reservation_indisponible")
        conn = self._reservations.conn
        debuter_transaction_exclusive(conn, "reservations_numeros")
        try:
            dernier_facture = self._factures.dernier_numero() or 0
            derniere = self._reservations.derniere_reservation(_TYPE_FACTURE_RESERVATION)
            if (derniere is not None and derniere[0] == derniere[1]
                    and derniere[2] == machine_id and derniere[1] > dernier_facture):
                conn.rollback()  # lecture seule : rien à valider, numéro repris tel quel
                return derniere[1]
            numero = max(dernier_facture, derniere[1] if derniere else 0) + 1
            self._reservations.reserver_bloc(
                _TYPE_FACTURE_RESERVATION, numero, numero, machine_id)
        except Exception:
            conn.rollback()
            raise
        return numero

    # Activité des machines (numérotation résiliente) --------------------------
    def toucher_activite(self, machine_id: str) -> None:
        """Enregistre une activité de `machine_id` — porté par tout appel
        existant (référentiels descendants), jamais une requête dédiée. Voir
        CLAUDE.md, section « Numérotation résiliente »."""
        self._machines.toucher(machine_id)

    def info_activite(self, machine_id: str) -> tuple[int, int]:
        """`(n, rang)` : nombre de postes de facturation actuellement actifs
        (ce poste inclus) et rang de `machine_id` parmi eux — communiqués à
        la machine appelante avec chaque réservation de numéros, pour son
        calcul déterministe de repli hors ligne (palier 3)."""
        return self._machines.info_activite(machine_id)

    def numero_existe(self, numero: int) -> bool:
        """Vrai si ce numéro est déjà utilisé."""
        return self._factures.numero_existe(numero)

    def chercher_facture_par_numero(self, numero: int) -> Facture | None:
        """Dernière facture (en-tête seul) portant ce numéro — utilisé pour
        retrouver l'id réel d'une facture à partir de son numéro (rejeu d'une
        `modification_facture` depuis la file de synchronisation, où l'id
        local n'a aucun sens côté serveur)."""
        return self._factures.chercher_par_numero(numero)

    # Enregistrement ----------------------------------------------------------
    def valider_ligne(self, ligne: LigneVente) -> None:
        """Une ligne est valide si quantité > 0 et prix ≥ 0."""
        if ligne.quantite <= 0:
            raise ErreurValidation("fact_quantite_positive")
        if ligne.prix_unitaire < 0:
            raise ErreurValidation("fact_prix_positif")

    def enregistrer_facture(
        self,
        numero: int,
        date_facture: date,
        nom_client: str,
        destination: str,
        lignes: list[LigneVente],
        etabli_par: str = "",
        remise_taux: float = 0.0,
        machine_id: str = "",
        telephone: str = "",
        matricule: str = "",
    ) -> Facture:
        """Valide et enregistre une NOUVELLE facture (toujours une insertion).

        Crée le client au besoin, et décrémente le stock des produits vendus
        dans la même transaction (voir CLAUDE.md, section « Gestion de
        stock »). `_rattacher_produit` retrouve le produit du catalogue
        correspondant à la désignation de chaque ligne et, à défaut de
        correspondance, en crée un à la volée : ce filet de sécurité au
        niveau service reste inchangé (utile aux tests et au rejeu de
        synchronisation), mais la création de produit se fait désormais
        exclusivement depuis l'app Stock en usage normal — l'UI de
        facturation (`FacturationView._ajouter_ligne`) refuse déjà d'ajouter
        au panier une désignation sans correspondance au catalogue, avant
        même d'atteindre ce service. `remise_taux` (0 à 100) applique une
        remise
        propre à CETTE facture, distincte de la remise annuelle par client.
        La TVA (`config.TVA_TAUX_DEFAUT`, 18 %) est obligatoire et appliquée
        automatiquement — prélevée SUR le total net (après remise) plutôt
        qu'ajoutée en plus : voir `Facture.tva_montant`/`total_ht`/`total_ttc`.
        """
        facture = self._preparer_facture(
            numero, date_facture, nom_client, destination, lignes,
            etabli_par, remise_taux, telephone, matricule)
        ventes_stock = [(l.produit_id, l.quantite) for l in lignes if l.produit_id]
        return self._factures.enregistrer(facture, ventes_stock=ventes_stock,
                                          machine_id=machine_id)

    def modifier_facture(
        self,
        facture_id: int,
        numero: int,
        date_facture: date,
        nom_client: str,
        destination: str,
        lignes: list[LigneVente],
        etabli_par: str = "",
        remise_taux: float = 0.0,
        machine_id: str = "",
        telephone: str = "",
        matricule: str = "",
    ) -> Facture:
        """Corrige une facture déjà enregistrée (même validations que la
        création) : en-tête et lignes sont intégralement remplacés, sans
        supprimer puis tout ressaisir. Le numéro peut être changé. Les
        mouvements de stock de l'ancienne version sont annulés puis
        remplacés par ceux des nouvelles lignes (voir `FactureRepository`)."""
        facture = self._preparer_facture(
            numero, date_facture, nom_client, destination, lignes,
            etabli_par, remise_taux, telephone, matricule)
        facture.id = facture_id
        ventes_stock = [(l.produit_id, l.quantite) for l in lignes if l.produit_id]
        self._factures.modifier(facture, ventes_stock=ventes_stock, machine_id=machine_id)
        return facture

    def _preparer_facture(
        self, numero: int, date_facture: date, nom_client: str, destination: str,
        lignes: list[LigneVente], etabli_par: str, remise_taux: float = 0.0,
        telephone: str = "", matricule: str = "",
    ) -> Facture:
        """Validations et résolutions (client, produits) communes à la
        création et à la modification d'une facture."""
        from app import config

        nom_client = str(nom_client or "").strip()
        if not nom_client:
            raise ErreurValidation("fact_client_requis")
        if not lignes:
            raise ErreurValidation("fact_panier_vide")
        if not 0 <= remise_taux <= 100:
            raise ErreurValidation("fact_remise_invalide")
        for ligne in lignes:
            self.valider_ligne(ligne)
            self._rattacher_produit(ligne)
        client: Client = self._clients.obtenir_ou_creer(nom_client, adresse=destination)
        return Facture(
            numero=numero,
            date_facture=date_facture,
            client_id=client.id,
            client_nom=client.nom,
            destination=destination.strip(),
            telephone=telephone.strip(),
            matricule=matricule.strip(),
            etabli_par=etabli_par.strip(),
            remise_taux=remise_taux,
            tva_taux=config.TVA_TAUX_DEFAUT,
            lignes=lignes,
        )

    def _rattacher_produit(self, ligne: LigneVente) -> None:
        """Rattache la ligne à un produit du catalogue, créé s'il n'existe pas
        (désignation inconnue saisie manuellement). Le produit auto-créé n'a
        pas d'option dimension/litrage, au prix pratiqué sur la ligne."""
        if ligne.produit_id is not None:
            return
        designation = str(ligne.designation or "").strip()
        if not designation:
            return
        for produit in self._produits.lister():
            if produit.designation.strip().upper() == designation.upper():
                ligne.produit_id = produit.id
                return
        produit = self._produits.creer(
            Produit(nom=designation, prix=ligne.prix_unitaire)
        )
        ligne.produit_id = produit.id

    # Référentiels (synchro descendante vers le cache de la machine de
    # facturation) ------------------------------------------------------------
    def lister_referentiel_produits(self) -> list[Produit]:
        """Tous les produits du catalogue (actifs et inactifs), pour la
        synchro descendante vers le cache local."""
        return self._produits.lister()

    def lister_referentiel_clients(self) -> list[dict]:
        """Tous les clients, pour la synchro descendante vers le cache local."""
        return [
            {
                "nom": client.nom,
                "telephone": client.telephone,
                "adresse": client.adresse,
                "modifie_le": client.modifie_le,
            }
            for client in self._clients.lister()
        ]

    # Consultation ------------------------------------------------------------
    def obtenir_facture(self, facture_id: int) -> Facture | None:
        """Facture complète avec ses lignes."""
        return self._factures.obtenir(facture_id)

    def lister_factures(
        self,
        date_debut: date | None = None,
        date_fin: date | None = None,
        client_id: int | None = None,
        inclure_archivees: bool = False,
    ) -> list[Facture]:
        """Historique filtrable (période, client). Les factures archivées
        sont exclues par défaut."""
        return self._factures.lister(date_debut, date_fin, client_id, inclure_archivees)

    def supprimer_facture(self, facture_id: int, machine_id: str = "") -> None:
        """Suppression définitive d'une facture et de ses lignes — restitue
        le stock des produits vendus (voir CLAUDE.md, section « Gestion de
        stock »)."""
        self._factures.supprimer(facture_id, machine_id=machine_id)

    def archiver_periode(
        self, date_debut: date, date_fin: date, client_id: int | None = None,
    ) -> int:
        """Masque de l'historique des ventes et des statistiques les factures
        de la période (ex. clôture de fin de mois)."""
        return self._factures.archiver(date_debut, date_fin, client_id)

    def desarchiver_periode(
        self, date_debut: date, date_fin: date, client_id: int | None = None,
    ) -> int:
        """Réaffiche des factures archivées de la période dans l'historique."""
        return self._factures.desarchiver(date_debut, date_fin, client_id)

    def archiver_ids(self, ids: list[int]) -> int:
        """Archive une sélection précise de factures (page Archive)."""
        return self._factures.archiver_ids(ids)

    def desarchiver_ids(self, ids: list[int]) -> int:
        """Réaffiche une sélection précise de factures archivées."""
        return self._factures.desarchiver_ids(ids)

    def numeros_archives(self, numeros: list[int]) -> list[int]:
        """Parmi ces numéros, ceux actuellement archivés — sert la
        synchronisation descendante du statut d'archivage vers le cache
        d'une machine de facturation."""
        return self._factures.numeros_archives(numeros)
