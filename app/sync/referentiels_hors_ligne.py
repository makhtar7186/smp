"""Variantes de `ProduitRepository`/`ClientRepository` utilisées uniquement
par les pages Produits/Clients de la machine de facturation, pour les
créations et modifications **autonomes** (hors saisie d'une facture — où
l'auto-création de produit/client est intégralement gérée par le rejeu de
`creation_facture`, voir `FacturationServiceHorsLigne`, qui construit ses
PROPRES instances non enfilées de ces repositories, jamais celles-ci, pour
éviter un double enfilage). Voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import sqlite3

from app.models import Client, Produit
from app.repositories.client_repository import ClientRepository
from app.repositories.produit_repository import ProduitRepository
from app.sync.payloads import (
    cle_correlation_client,
    cle_correlation_client_modification,
    cle_correlation_produit,
    cle_correlation_produit_modification,
    construire_payload_client,
    construire_payload_client_modification,
    construire_payload_produit,
    construire_payload_produit_modification,
)
from app.sync.queue_repository import QueueSyncRepository


class ProduitRepositoryHorsLigne(ProduitRepository):
    """`creer` enfile `creation_produit`, `modifier` enfile
    `modification_produit` — tous deux en plus de l'écriture locale.
    `supprimer`/`fusionner` restent hérités tels quels : leurs effets
    restent locaux à cette machine (suppressions non synchronisées, par
    choix — voir CLAUDE.md, « Machine de facturation »)."""

    def __init__(self, conn: sqlite3.Connection, queue: QueueSyncRepository) -> None:
        super().__init__(conn)
        self._queue = queue

    def creer(self, produit: Produit) -> Produit:
        cree = super().creer(produit)
        payload = construire_payload_produit(
            cree.nom, cree.type_option, cree.valeur_option, cree.prix)
        cle = cle_correlation_produit(cree.nom, cree.type_option, cree.valeur_option)
        self._queue.enfiler("creation_produit", cle, payload)
        return cree

    def modifier(self, produit: Produit) -> None:
        """Capture l'identité AVANT modification (encore en base à cet
        instant précis) pour servir de clé de corrélation côté serveur —
        `produit` porte déjà les nouvelles valeurs, fournies par l'appelant
        (voir `ProduitsView._enregistrer`)."""
        ancien = self.obtenir(produit.id)
        super().modifier(produit)
        if ancien is None:
            return
        payload = construire_payload_produit_modification(
            ancien.nom, ancien.type_option, ancien.valeur_option,
            produit.nom, produit.type_option, produit.valeur_option,
            produit.prix, produit.actif)
        cle = cle_correlation_produit_modification(
            ancien.nom, ancien.type_option, ancien.valeur_option)
        self._queue.enfiler("modification_produit", cle, payload)


class ClientRepositoryHorsLigne(ClientRepository):
    """`creer` enfile `creation_client`, `modifier` enfile
    `modification_client` — tous deux en plus de l'écriture locale.
    `supprimer` reste hérité tel quel (effet local uniquement) ; la fusion
    passe par `ClientMaintenanceServiceHorsLigne`, pas par ce repository."""

    def __init__(self, conn: sqlite3.Connection, queue: QueueSyncRepository) -> None:
        super().__init__(conn)
        self._queue = queue

    def creer(self, client: Client) -> Client:
        cree = super().creer(client)
        payload = construire_payload_client(cree.nom, cree.telephone, cree.adresse)
        cle = cle_correlation_client(cree.nom, cree.adresse)
        self._queue.enfiler("creation_client", cle, payload)
        return cree

    def modifier(self, client: Client) -> None:
        """Même principe que `ProduitRepositoryHorsLigne.modifier` : capture
        l'identité (nom, adresse) AVANT modification pour la corrélation."""
        ancien = self.obtenir(client.id)
        super().modifier(client)
        if ancien is None:
            return
        payload = construire_payload_client_modification(
            ancien.nom, ancien.adresse, client.nom, client.telephone, client.adresse)
        cle = cle_correlation_client_modification(ancien.nom, ancien.adresse)
        self._queue.enfiler("modification_client", cle, payload)
