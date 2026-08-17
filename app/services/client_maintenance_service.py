"""Fusion de fiches clients — correction des erreurs de saisie (homonymes
accidentels) sur une base déjà en service."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.models import Client
from app.repositories.client_repository import ClientRepository
from app.repositories.facture_repository import FactureRepository
from app.repositories.remise_repository import RemiseRepository
from app.utils.validation import ErreurValidation


@dataclass
class ResultatFusion:
    """Bilan d'une fusion de deux fiches clients."""

    client: Client
    factures_transferees: int


class ClientMaintenanceService:
    """Corrige des fiches clients existantes sans repartir de zéro : fusionne
    des doublons (typo d'adresse, homonyme non voulu)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._clients = ClientRepository(conn)
        self._factures = FactureRepository(conn)
        self._remises = RemiseRepository(conn)

    def localites_facturees(self, client_id: int) -> list[tuple[str, int]]:
        """Destinations distinctes des factures de ce client, avec leur nombre."""
        return self._factures.compter_destinations(client_id)

    def fusionner_doublon_telephone(self, client: Client) -> None:
        """Si le téléphone de `client` (déjà affecté en mémoire, pas encore
        enregistré) correspond à un AUTRE client déjà en base, fusionne ce
        dernier DANS `client` avant que l'appelant n'enregistre sa
        modification — sans cela, l'écriture violerait
        `idx_clients_telephone_unique`. Le numéro de téléphone est
        l'élément d'identification le plus fiable (voir CLAUDE.md,
        « Clients ») : deux fiches qui finissent par le partager sont
        considérées comme la même personne et fusionnées automatiquement,
        plutôt que de bloquer l'enregistrement. `client` (celui en cours
        d'édition) survit toujours, avec les valeurs que l'usager vient de
        saisir ; l'autre fiche est supprimée après réattribution de son
        historique (factures/remises)."""
        telephone_norm = ClientRepository.normaliser_telephone(client.telephone)
        if not telephone_norm:
            return
        autre = self._clients.chercher_par_telephone(telephone_norm)
        if autre is not None and autre.id != client.id:
            self.fusionner(client.id, autre.id)

    def fusionner(self, id_a_garder: int, id_a_supprimer: int) -> ResultatFusion:
        """Fusionne un client dans un autre : factures et remises du client
        supprimé sont transférées vers le client conservé."""
        if id_a_garder == id_a_supprimer:
            raise ErreurValidation("cli_fusion_soi_meme")
        cible = self._clients.obtenir(id_a_garder)
        source = self._clients.obtenir(id_a_supprimer)
        if cible is None or source is None:
            raise ErreurValidation("cli_fusion_introuvable")

        # Complète la fiche conservée avec les infos manquantes du doublon
        # (calculé avant suppression, mais écrit seulement APRÈS : le
        # téléphone du doublon est encore en base jusque-là, et l'index
        # unique partiel sur `clients.telephone` refuserait sinon de le
        # recopier sur la fiche conservée tant que les deux fiches coexistent).
        modifie = False
        if not cible.telephone and source.telephone:
            cible.telephone = source.telephone
            modifie = True
        if not cible.adresse and source.adresse:
            cible.adresse = source.adresse
            modifie = True

        nb_factures = self._factures.reattribuer_client(source.id, cible.id, cible.nom)

        self._remises.reattribuer_client(source.id, cible.id)
        self._clients.supprimer(source.id)

        if modifie:
            self._clients.modifier(cible)
        return ResultatFusion(client=cible, factures_transferees=nb_factures)
