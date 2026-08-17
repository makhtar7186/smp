"""Tests des repositories offline-first pour les créations autonomes de
produits/clients (pages Produits/Clients de la machine de facturation)."""
from __future__ import annotations

from app.models import Client, Produit
from app.sync.queue_repository import QueueSyncRepository
from app.sync.referentiels_hors_ligne import (
    ClientRepositoryHorsLigne,
    ProduitRepositoryHorsLigne,
)


def test_creer_produit_enfile_creation_produit(conn) -> None:
    queue = QueueSyncRepository(conn)
    repo = ProduitRepositoryHorsLigne(conn, queue)
    repo.creer(Produit(nom="SM TAPISSIER", type_option="dimension",
                       valeur_option="140X190", prix=10000))
    operations = queue.lister()
    assert len(operations) == 1
    assert operations[0].type_operation == "creation_produit"
    assert operations[0].payload["nom"] == "SM TAPISSIER"


def test_creer_client_enfile_creation_client(conn) -> None:
    queue = QueueSyncRepository(conn)
    repo = ClientRepositoryHorsLigne(conn, queue)
    repo.creer(Client(nom="NOUVEAU", adresse="DAKAR"))
    operations = queue.lister()
    assert len(operations) == 1
    assert operations[0].type_operation == "creation_client"
    assert operations[0].payload["nom"] == "NOUVEAU"


def test_modifier_produit_enfile_modification_produit_avec_ancienne_identite(conn) -> None:
    """Le prix modifié localement doit se répercuter jusqu'au boss — pas
    seulement rester dans le cache local (voir CLAUDE.md, « Gestion de
    stock »). Le payload porte l'identité D'AVANT (nom inchangé ici) pour
    que le serveur puisse retrouver le produit par clé naturelle."""
    queue = QueueSyncRepository(conn)
    repo = ProduitRepositoryHorsLigne(conn, queue)
    produit = repo.creer(Produit(nom="BIDON", type_option="litrage",
                                 valeur_option="5L", prix=2500))
    produit.prix = 3000
    repo.modifier(produit)
    operations = queue.lister(["en_attente"])
    modif = [o for o in operations if o.type_operation == "modification_produit"]
    assert len(modif) == 1
    assert modif[0].payload["ancien_nom"] == "BIDON"
    assert modif[0].payload["prix"] == 3000


def test_modifier_client_enfile_modification_client_avec_ancienne_identite(conn) -> None:
    queue = QueueSyncRepository(conn)
    repo = ClientRepositoryHorsLigne(conn, queue)
    client = repo.creer(Client(nom="AVANT", adresse="DAKAR", telephone="770000000"))
    client.nom = "APRES"
    client.telephone = "771111111"
    repo.modifier(client)
    operations = queue.lister(["en_attente"])
    modif = [o for o in operations if o.type_operation == "modification_client"]
    assert len(modif) == 1
    assert modif[0].payload["ancien_nom"] == "AVANT"
    assert modif[0].payload["nom"] == "APRES"
    assert modif[0].payload["telephone"] == "771111111"
