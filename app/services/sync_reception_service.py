"""Réception (boss) des opérations rejouées depuis la file de synchronisation
d'une machine de facturation — `POST /sync/operation`. Chaque type
d'opération est rejoué via les services existants, qui ré-exécutent leur
propre résolution (client/produit) en autorité : aucun id local envoyé par la
machine de facturation n'est jamais utilisé tel quel. Voir CLAUDE.md, section
« Machine de facturation »."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

from app.models import HistoriqueFusion, Produit
from app.repositories.client_repository import ClientRepository
from app.repositories.historique_fusion_repository import HistoriqueFusionRepository
from app.repositories.produit_repository import ProduitRepository
from app.services.client_maintenance_service import ClientMaintenanceService
from app.services.facturation_service import FacturationService
from app.sync.payloads import parser_payload_facture
from app.utils.validation import ErreurMetier, ErreurValidation

_TYPES_CONNUS = (
    "creation_facture", "modification_facture", "suppression_facture",
    "creation_client", "creation_produit", "modification_produit",
    "modification_client", "fusion_client",
)


class SyncReceptionService:
    """Point d'entrée unique du rejeu — `rejouer()` route vers le bon
    gestionnaire privé selon `type_operation`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._facturation = FacturationService(conn)
        self._clients = ClientRepository(conn)
        self._produits = ProduitRepository(conn)
        self._maintenance = ClientMaintenanceService(conn)
        self._historique_fusions = HistoriqueFusionRepository(conn)

    def rejouer(self, type_operation: str, cle_correlation: str, payload: dict,
               machine_id: str = "", cree_le: str = "") -> dict:
        if type_operation not in _TYPES_CONNUS:
            raise ErreurValidation("sync_type_operation_inconnu")
        if type_operation == "creation_facture":
            return self._rejouer_creation_facture(payload)
        if type_operation == "modification_facture":
            return self._rejouer_modification_facture(payload)
        if type_operation == "suppression_facture":
            return self._rejouer_suppression_facture(payload)
        if type_operation == "creation_client":
            return self._rejouer_creation_client(payload)
        if type_operation == "creation_produit":
            return self._rejouer_creation_produit(payload)
        if type_operation == "modification_produit":
            return self._rejouer_modification_produit(payload)
        if type_operation == "modification_client":
            return self._rejouer_modification_client(payload)
        return self._rejouer_fusion_client(payload, machine_id, cree_le)

    # Factures ------------------------------------------------------------------
    def _rejouer_creation_facture(self, payload: dict) -> dict:
        """Rejoue les MÊMES arguments naturels que la machine de facturation
        a utilisés localement — la résolution client/produit est refaite ici,
        en autorité, par `FacturationService._preparer_facture`."""
        args = parser_payload_facture(payload)
        facture = self._facturation.enregistrer_facture(**args)
        return {"statut": "ok", "id_correlation_serveur": facture.id}

    def _rejouer_modification_facture(self, payload: dict) -> dict:
        """Le `numero` du payload est la seule clé de corrélation fiable
        entre l'id local (sans signification côté serveur) et la facture
        réellement enregistrée ici."""
        args = parser_payload_facture(payload)
        existante = self._facturation.chercher_facture_par_numero(args["numero"])
        if existante is None or existante.id is None:
            raise ErreurMetier("sync_modification_facture_introuvable")
        facture = self._facturation.modifier_facture(facture_id=existante.id, **args)
        return {"statut": "ok", "id_correlation_serveur": facture.id}

    def _rejouer_suppression_facture(self, payload: dict) -> dict:
        """Retrouve la facture par son numéro (seule clé de corrélation
        fiable, comme pour `modification_facture`) et la supprime — restitue
        le stock au passage (voir `FacturationService.supprimer_facture`).
        Si elle est déjà absente (créée puis supprimée sur la machine de
        facturation avant d'avoir jamais atteint le serveur), ne fait rien :
        le résultat souhaité — qu'elle n'existe pas — est déjà atteint."""
        facture = self._facturation.chercher_facture_par_numero(payload["numero"])
        if facture is None or facture.id is None:
            return {"statut": "ok", "id_correlation_serveur": None}
        self._facturation.supprimer_facture(facture.id)
        return {"statut": "ok", "id_correlation_serveur": facture.id}

    # Créations autonomes (pages Produits/Clients) -------------------------------
    def _rejouer_creation_client(self, payload: dict) -> dict:
        client = self._clients.obtenir_ou_creer(
            payload["nom"], telephone=payload.get("telephone", ""),
            adresse=payload.get("adresse", ""))
        return {"statut": "ok", "id_correlation_serveur": client.id}

    def _rejouer_creation_produit(self, payload: dict) -> dict:
        produit = self._produits.obtenir_ou_creer(
            payload["nom"], payload.get("type_option", ""),
            payload.get("valeur_option", ""), prix=payload.get("prix", 0))
        return {"statut": "ok", "id_correlation_serveur": produit.id}

    def _rejouer_modification_produit(self, payload: dict) -> dict:
        """Retrouve le produit par son identité D'AVANT la modification
        (`ancien_*`, clé naturelle) puis lui applique les nouvelles valeurs.
        Si introuvable (ex. jamais synchronisé jusqu'ici), le crée directement
        avec les valeurs demandées plutôt que d'échouer — même philosophie
        de résilience que `_rejouer_creation_produit`."""
        existant = self._produits.chercher(
            payload["ancien_nom"], payload.get("ancien_type_option", ""),
            payload.get("ancien_valeur_option", ""))
        if existant is None:
            produit = self._produits.creer(Produit(
                nom=payload["nom"], type_option=payload.get("type_option", ""),
                valeur_option=payload.get("valeur_option", ""),
                prix=payload.get("prix", 0), actif=payload.get("actif", True)))
            return {"statut": "ok", "id_correlation_serveur": produit.id}
        existant.nom = payload["nom"]
        existant.type_option = payload.get("type_option", "")
        existant.valeur_option = payload.get("valeur_option", "")
        existant.prix = payload.get("prix", existant.prix)
        existant.actif = payload.get("actif", existant.actif)
        self._produits.modifier(existant)
        return {"statut": "ok", "id_correlation_serveur": existant.id}

    def _rejouer_modification_client(self, payload: dict) -> dict:
        """Même principe que `_rejouer_modification_produit`, côté client —
        et fusionne d'abord un éventuel doublon déjà titulaire du nouveau
        téléphone (voir `ClientMaintenanceService.fusionner_doublon_telephone`),
        pour ne jamais heurter `idx_clients_telephone_unique`."""
        existant = self._clients.chercher_par_nom_et_adresse(
            payload["ancien_nom"], payload["ancien_adresse"])
        if existant is None:
            client = self._clients.obtenir_ou_creer(
                payload["nom"], telephone=payload.get("telephone", ""),
                adresse=payload.get("adresse", ""))
            return {"statut": "ok", "id_correlation_serveur": client.id}
        existant.nom = payload["nom"]
        existant.telephone = payload.get("telephone", "")
        existant.adresse = payload.get("adresse", "")
        self._maintenance.fusionner_doublon_telephone(existant)
        self._clients.modifier(existant)
        return {"statut": "ok", "id_correlation_serveur": existant.id}

    # Fusion de client ------------------------------------------------------------
    def _rejouer_fusion_client(self, payload: dict, machine_id: str,
                               cree_le: str) -> dict:
        """Résout les deux fiches par (nom, adresse) — jamais par id local.
        Un conflit (fiche modifiée côté serveur entre la décision locale et
        ce rejeu) n'empêche pas la fusion : elle est appliquée quand même,
        mais journalée en détail dans `historique_fusions_clients`."""
        cible = self._clients.chercher_par_nom_et_adresse(
            payload["cible_nom"], payload["cible_adresse"])
        source = self._clients.chercher_par_nom_et_adresse(
            payload["source_nom"], payload["source_adresse"])
        if cible is None or source is None:
            raise ErreurMetier("sync_fusion_client_introuvable")

        conflit = (
            cible.modifie_le != payload.get("cible_modifie_le_connu", "")
            or source.modifie_le != payload.get("source_modifie_le_connu", "")
        )
        etat_avant = {"cible": asdict(cible), "source": asdict(source)}
        resultat = self._maintenance.fusionner(cible.id, source.id)
        etat_apres = {"cible": asdict(resultat.client),
                      "factures_transferees": resultat.factures_transferees}

        self._historique_fusions.enregistrer(HistoriqueFusion(
            machine_origine=machine_id,
            demande_le=cree_le,
            client_a_garder_nom=payload["cible_nom"],
            client_a_garder_adresse=payload["cible_adresse"],
            client_a_supprimer_nom=payload["source_nom"],
            client_a_supprimer_adresse=payload["source_adresse"],
            client_a_garder_id_serveur=cible.id,
            client_a_supprimer_id_serveur=source.id,
            conflit_detecte=conflit,
            etat_avant_json=json.dumps(etat_avant, ensure_ascii=False),
            etat_apres_json=json.dumps(etat_apres, ensure_ascii=False),
            resultat="applique",
        ))
        return {"statut": "ok", "id_correlation_serveur": resultat.client.id}
