"""Synchro descendante périodique des référentiels (produits, clients) depuis
la machine boss vers le cache local de la machine de facturation. Jamais
destructif (aucun DELETE) et ne doit jamais écraser une fiche créée localement
en attente de synchro montante — voir CLAUDE.md, section « Machine de
facturation »."""
from __future__ import annotations

import threading
from pathlib import Path

from app.models import Produit
from app.repositories.base_repository import creer_connexion
from app.repositories.client_repository import ClientRepository
from app.repositories.produit_repository import ProduitRepository
from app.sync.api_sync_client import ApiSyncClient, ErreurApiSync

_INTERVALLE_DEFAUT = 300  # secondes


class ReferentielSyncWorker:
    """Thread daemon indépendant du `SyncWorker` (file montante) : celui-ci
    ne fait que lire depuis l'API, jamais écrire dessus."""

    def __init__(self, chemin_cache_db: Path, api: ApiSyncClient,
                 intervalle_secondes: int = _INTERVALLE_DEFAUT) -> None:
        self._chemin_cache_db = chemin_cache_db
        self._api = api
        self._intervalle_secondes = intervalle_secondes
        self._reveil = threading.Event()
        self._arret = threading.Event()
        self._thread: threading.Thread | None = None

    def demarrer(self) -> None:
        if self._thread is not None:
            return
        self._arret.clear()
        self._thread = threading.Thread(target=self._boucle, daemon=True,
                                        name="promatelas-referentiel-worker")
        self._thread.start()

    def arreter(self) -> None:
        self._arret.set()
        self._reveil.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def declencher_immediat(self) -> None:
        self._reveil.set()

    def _boucle(self) -> None:
        conn = creer_connexion(self._chemin_cache_db)
        try:
            while not self._arret.is_set():
                try:
                    self.synchroniser(conn)
                except Exception:
                    # Filet de sécurité : une erreur imprévue (ex. verrou
                    # SQLite concurrent non couvert par `busy_timeout`, champ
                    # inattendu) ne doit JAMAIS tuer ce thread daemon — sans
                    # console (`--windowed`), une exception non rattrapée ici
                    # serait invisible et arrêterait silencieusement toute
                    # synchro descendante jusqu'au redémarrage de l'app.
                    pass
                self._reveil.wait(self._intervalle_secondes)
                self._reveil.clear()
        finally:
            conn.close()

    def synchroniser(self, conn) -> None:
        """Exposé en public (plutôt que privé) pour être appelable directement
        dans les tests, sans dépendre du thread/minuteur."""
        try:
            self._synchroniser_produits(conn)
            self._synchroniser_clients(conn)
        except ErreurApiSync:
            pass  # hors ligne ou erreur transitoire : nouvelle tentative au prochain passage

    def _synchroniser_produits(self, conn) -> None:
        """Retrouve d'abord chaque produit par `id_serveur` (clé stable,
        insensible à un renommage fait depuis l'app Stock) ; à défaut
        (produit jamais encore lié — ex. juste après la mise à jour vers
        cette version), replie sur la clé naturelle (nom, type_option,
        valeur_option), qui fonctionne tant que le produit n'a jamais été
        renommé depuis la dernière synchro. Dans les deux cas, `id_serveur`
        est adopté/confirmé sur la ligne locale : dès ce cycle, un
        renommage ultérieur sera retrouvé correctement (voir CLAUDE.md,
        section « Machine de facturation »). Sans cela, un produit renommé
        redevenait introuvable par son ancien nom et se dupliquait au lieu
        d'être mis à jour."""
        produits = ProduitRepository(conn)
        for item in self._api.referentiel_produits():
            quantite_stock = item.get("quantite_stock", 0)
            id_serveur = item.get("id_serveur", 0)
            existant = produits.chercher_par_id_serveur(id_serveur)
            if existant is None:
                existant = produits.chercher(
                    item["nom"], item["type_option"], item["valeur_option"])
            if existant is not None:
                existant.nom = item["nom"]
                existant.type_option = item["type_option"]
                existant.valeur_option = item["valeur_option"]
                existant.prix = item["prix"]
                existant.actif = item["actif"]
                existant.id_serveur = id_serveur
                produits.modifier(existant)
                # `modifier` ne touche jamais quantite_stock (édition manuelle
                # du catalogue) — instantané du stock boss appliqué à part,
                # seule voie par laquelle cette machine hors ligne apprend les
                # entrées/ajustements faits ailleurs (app Stock).
                produits.definir_quantite_stock(existant.id, quantite_stock)
            else:
                produits.creer(Produit(
                    nom=item["nom"], type_option=item["type_option"],
                    valeur_option=item["valeur_option"], prix=item["prix"],
                    actif=item["actif"], quantite_stock=quantite_stock,
                    id_serveur=id_serveur,
                ))

    def _synchroniser_clients(self, conn) -> None:
        """Sans parent_id à résoudre, un simple upsert par clé naturelle
        (nom, adresse) suffit — plus de résolution en deux passes."""
        clients = ClientRepository(conn)
        for item in self._api.referentiel_clients():
            clients.upsert_depuis_referentiel(
                item["nom"], item["adresse"], item["telephone"], item["modifie_le"])
