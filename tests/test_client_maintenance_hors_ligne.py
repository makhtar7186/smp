"""Tests de ClientMaintenanceServiceHorsLigne : la fusion locale enfile
l'opération `fusion_client` avec les clés naturelles des deux fiches."""
from __future__ import annotations

from app.models import Client
from app.repositories.client_repository import ClientRepository
from app.sync.client_maintenance_hors_ligne import ClientMaintenanceServiceHorsLigne
from app.sync.queue_repository import QueueSyncRepository


def test_fusionner_enfile_l_operation_avec_cles_naturelles(conn) -> None:
    clients = ClientRepository(conn)
    cible = clients.creer(Client(nom="CIBLE", adresse="DAKAR"))
    source = clients.creer(Client(nom="SOURCE", adresse="THIES"))

    queue = QueueSyncRepository(conn)
    service = ClientMaintenanceServiceHorsLigne(conn, queue=queue)
    resultat = service.fusionner(cible.id, source.id)

    assert resultat.client.nom == "CIBLE"
    operations = queue.lister()
    assert len(operations) == 1
    assert operations[0].type_operation == "fusion_client"
    assert operations[0].payload["cible_nom"] == "CIBLE"
    assert operations[0].payload["source_nom"] == "SOURCE"
    assert operations[0].payload["source_adresse"] == "THIES"
