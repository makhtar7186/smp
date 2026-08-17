"""Variante de `ClientMaintenanceService` utilisée sur la machine de
facturation : après une fusion locale (déjà non atomique dans la classe
mère — chaque repository commite séparément, y compris côté boss), enfile
l'opération `fusion_client` avec les clés naturelles des deux fiches. Voir
CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

import sqlite3

from app.services.client_maintenance_service import ClientMaintenanceService, ResultatFusion
from app.sync.payloads import cle_correlation_fusion, construire_payload_fusion_client
from app.sync.queue_repository import QueueSyncRepository


class ClientMaintenanceServiceHorsLigne(ClientMaintenanceService):
    """`fusionner` délègue intégralement à la classe mère, puis enfile
    l'opération de synchro dans une transaction dédiée courte : si le
    processus s'arrête entre la fin de la fusion locale et cet enfilage,
    cette fusion précise ne sera jamais renvoyée au serveur (limite
    documentée — l'échec d'enfilage est remonté à l'utilisateur, jamais
    avalé silencieusement)."""

    def __init__(self, conn: sqlite3.Connection, queue: QueueSyncRepository) -> None:
        super().__init__(conn)
        self._queue = queue

    def fusionner(self, id_a_garder: int, id_a_supprimer: int) -> ResultatFusion:
        cible_avant = self._clients.obtenir(id_a_garder)
        source_avant = self._clients.obtenir(id_a_supprimer)
        resultat = super().fusionner(id_a_garder, id_a_supprimer)
        payload = construire_payload_fusion_client(cible_avant, source_avant)
        cle = cle_correlation_fusion(cible_avant, source_avant)
        self._queue.enfiler("fusion_client", cle, payload)
        return resultat
