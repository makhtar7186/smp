"""Variante de `FacturationService` utilisée uniquement sur la machine de
facturation : la numérotation est tirée exclusivement du pool local réservé
(jamais de numéro généré ad hoc hors ligne), et chaque écriture est enfilée
dans la MÊME transaction que l'écriture locale. Voir CLAUDE.md, section
« Machine de facturation »."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.models import Facture, LigneVente
from app.services.facturation_service import FacturationService
from app.sync.numero_reservation import NumeroReservationRepository
from app.sync.payloads import cle_correlation_facture, construire_payload_facture
from app.sync.queue_repository import QueueSyncRepository
from app.utils.validation import ErreurValidation


class FacturationServiceHorsLigne(FacturationService):
    """Facturation offline-first : numérotation par pool réservé, écriture +
    enfilage de synchro (+ mouvements de stock) atomiques."""

    def __init__(self, conn: sqlite3.Connection, queue: QueueSyncRepository,
                 numeros: NumeroReservationRepository) -> None:
        super().__init__(conn, queue=queue)
        self._numeros = numeros

    def prochain_numero(self) -> int:
        """Ignore délibérément la logique `MAX(numero)+1` de la classe mère
        (qui suppose une base faisant autorité) : tire du pool réservé
        auprès du serveur, jamais d'improvisation hors ligne."""
        numero = self._numeros.prochain_disponible("usine")
        if numero is None:
            raise ErreurValidation("sync_pool_numeros_epuise")
        return numero

    # `reserver_bloc_numeros` hérité de FacturationService lève déjà
    # ErreurValidation("sync_reservation_indisponible") en l'absence de
    # ReservationNumeroRepository (jamais construit ici) — pas de surcharge
    # nécessaire.

    def enregistrer_facture(
        self, numero: int, date_facture: date, nom_client: str, destination: str,
        lignes: list[LigneVente], etabli_par: str = "", remise_taux: float = 0.0,
        machine_id: str = "", telephone: str = "", matricule: str = "",
    ) -> Facture:
        # Garde-fou : un numéro saisi manuellement doit appartenir au pool
        # réservé — jamais de numéro improvisé hors ligne.
        if not self._numeros.est_disponible(numero):
            raise ErreurValidation("sync_numero_non_reserve")
        facture = self._preparer_facture(
            numero, date_facture, nom_client, destination, lignes,
            etabli_par, remise_taux, telephone, matricule)
        ventes_stock = [(l.produit_id, l.quantite) for l in lignes if l.produit_id]
        payload = construire_payload_facture(
            numero, date_facture, nom_client, destination, lignes,
            etabli_par, remise_taux, telephone, matricule)
        cle = cle_correlation_facture(numero)
        resultat = self._factures.enregistrer(
            facture, queue=self._queue, payload=payload,
            type_operation="creation_facture", cle_correlation=cle,
            ventes_stock=ventes_stock, machine_id=machine_id)
        self._numeros.marquer_utilise(numero)
        return resultat

    def modifier_facture(
        self, facture_id: int, numero: int, date_facture: date, nom_client: str,
        destination: str, lignes: list[LigneVente], etabli_par: str = "",
        remise_taux: float = 0.0, machine_id: str = "",
        telephone: str = "", matricule: str = "",
    ) -> Facture:
        facture = self._preparer_facture(
            numero, date_facture, nom_client, destination, lignes,
            etabli_par, remise_taux, telephone, matricule)
        facture.id = facture_id
        ventes_stock = [(l.produit_id, l.quantite) for l in lignes if l.produit_id]
        payload = construire_payload_facture(
            numero, date_facture, nom_client, destination, lignes,
            etabli_par, remise_taux, telephone, matricule)
        cle = cle_correlation_facture(numero)
        return self._factures.modifier(
            facture, queue=self._queue, payload=payload,
            type_operation="modification_facture", cle_correlation=cle,
            ventes_stock=ventes_stock, machine_id=machine_id)

    def supprimer_facture(self, facture_id: int, machine_id: str = "") -> None:
        """Supprime localement (avec restitution de stock, voir
        `FactureRepository.supprimer`) ET enfile la suppression — sans cela,
        le boss continuerait de voir une facture qui n'existe plus ici. Même
        clé de corrélation (`facture:{numero}`) qu'une création/modification
        de cette facture : si celle-ci était encore en attente de synchro
        (créée puis supprimée avant d'avoir jamais atteint le serveur), la
        file la remplace par cette suppression plutôt que d'empiler les
        deux — le rejeu constatera alors simplement qu'il n'y a rien à
        supprimer (voir `SyncReceptionService._rejouer_suppression_facture`)."""
        facture = self.obtenir_facture(facture_id)
        if facture is None:
            return
        payload = {"numero": facture.numero}
        cle = cle_correlation_facture(facture.numero)
        self._factures.supprimer(
            facture_id, machine_id=machine_id, queue=self._queue, payload=payload,
            type_operation="suppression_facture", cle_correlation=cle)
