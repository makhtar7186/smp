"""Client HTTP de l'API de stock (`app/api/routes_stock.py`, préfixe `/stock`,
rôle `role_stock`). Même idiome que `app.client.api_client.ApiClient` —
enveloppe fine autour de `requests`, exceptions typées pour que l'UI
(`app/stock/ui.py`) suive le même `try/except` que le reste de l'application."""
from __future__ import annotations

import requests

from app.stock.config_stock import ConfigStock

_DELAI_CONNEXION = 4       # secondes — le serveur est sur le LAN/Tailscale
_DELAI_LECTURE = 15


class ErreurApiStock(Exception):
    """Erreur générique de communication avec l'API de stock."""


class ErreurInjoignable(ErreurApiStock):
    """Le serveur n'a pas répondu (réseau/Tailscale/serveur éteint)."""


class ErreurAuthentification(ErreurApiStock):
    """Jeton API refusé (401)."""


class ErreurPermission(ErreurApiStock):
    """Action refusée pour le rôle de ce jeton (403)."""


class ApiStockClient:
    """Enveloppe fine autour de `requests` pour dialoguer avec `/stock`."""

    def __init__(self, config: ConfigStock) -> None:
        self._config = config

    def _en_tetes(self) -> dict:
        en_tetes = {"X-API-Key": self._config.token}
        if self._config.machine_id:
            en_tetes["X-Machine-Id"] = self._config.machine_id
        return en_tetes

    def _requete(self, methode: str, chemin: str, **kwargs) -> requests.Response:
        try:
            reponse = requests.request(
                methode, f"{self._config.base_url}{chemin}",
                headers=self._en_tetes(),
                timeout=(_DELAI_CONNEXION, _DELAI_LECTURE), **kwargs,
            )
        except requests.exceptions.RequestException as exc:
            raise ErreurInjoignable(str(exc)) from exc
        if reponse.status_code == 401:
            raise ErreurAuthentification("Jeton API invalide.")
        if reponse.status_code == 403:
            raise ErreurPermission("Action non autorisée pour ce poste.")
        if not reponse.ok:
            raise ErreurApiStock(f"Erreur API ({reponse.status_code}) : {reponse.text}")
        return reponse

    def tester_connexion(self) -> bool:
        """Vrai si le serveur répond (sans vérifier le jeton) — sert à
        distinguer « injoignable » de « jeton invalide »."""
        try:
            reponse = requests.get(f"{self._config.base_url}/health",
                                   timeout=(_DELAI_CONNEXION, _DELAI_CONNEXION))
            return reponse.ok
        except requests.exceptions.RequestException:
            return False

    # Produits / stock --------------------------------------------------------
    def lister_produits(self) -> list[dict]:
        """`GET /stock/produits` → [{id, nom, type_option, valeur_option,
        prix, actif, quantite_stock}, ...]."""
        return self._requete("GET", "/stock/produits").json()

    def creer_produit(
        self, nom: str, type_option: str = "", valeur_option: str = "", prix: int = 0,
    ) -> dict:
        """`POST /stock/produits` → article créé (stock initial à 0),
        {id, nom, type_option, valeur_option, prix, actif, quantite_stock}."""
        return self._requete(
            "POST", "/stock/produits",
            json={"nom": nom, "type_option": type_option,
                  "valeur_option": valeur_option, "prix": prix},
        ).json()

    def modifier_produit(
        self, produit_id: int, nom: str, type_option: str = "", valeur_option: str = "",
    ) -> dict:
        """`PUT /stock/produits/{id}` (jamais de prix) → article modifié."""
        return self._requete(
            "PUT", f"/stock/produits/{produit_id}",
            json={"nom": nom, "type_option": type_option, "valeur_option": valeur_option},
        ).json()

    def supprimer_produit(self, produit_id: int) -> None:
        """`DELETE /stock/produits/{id}` — refusé (400 → `ErreurApiStock`) si
        l'article est encore référencé par des ventes déjà enregistrées."""
        self._requete("DELETE", f"/stock/produits/{produit_id}")

    def entrer_stock(self, produit_id: int, quantite: int, note: str = "") -> dict:
        """`POST /stock/produits/{id}/entree` (quantite doit être > 0) →
        {id, produit_id, type_mouvement, quantite, reference, source,
        machine_id, cree_le}."""
        return self._requete(
            "POST", f"/stock/produits/{produit_id}/entree",
            json={"quantite": quantite, "note": note},
        ).json()

    def ajuster_stock(self, produit_id: int, delta: int, motif: str = "") -> dict:
        """`POST /stock/produits/{id}/ajustement` (delta signé, non nul) →
        même forme que `entrer_stock`."""
        return self._requete(
            "POST", f"/stock/produits/{produit_id}/ajustement",
            json={"delta": delta, "motif": motif},
        ).json()

    def historique(self, produit_id: int) -> list[dict]:
        """`GET /stock/produits/{id}/historique` → mouvements du produit,
        les plus récents en premier."""
        return self._requete("GET", f"/stock/produits/{produit_id}/historique").json()
