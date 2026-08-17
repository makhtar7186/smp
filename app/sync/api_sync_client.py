"""Client HTTP vers les endpoints de synchronisation de la machine boss
(`app/api/routes_sync.py`) — réservation de numéros, envoi d'une opération de
la file montante, référentiels descendants. Même idiome que
`app.client.api_client.ApiClient` (délibérément un module séparé : rôle et
jeton différents, `role_facturation` plutôt que `role_client`)."""
from __future__ import annotations

from datetime import date

import requests

from app.sync.config_sync import ConfigSync

_DELAI_CONNEXION = 4
_DELAI_LECTURE = 20  # les référentiels peuvent être volumineux
_DELAI_JIT = 5        # palier 1 (numérotation résiliente) : ne jamais bloquer
                       # longtemps l'interface si le serveur est lent/injoignable
_DELAI_POLL = 4        # sondage continu (palier 1) : cadence 3-5s, doit rester
                       # court pour ne jamais faire s'accumuler les requêtes


class ErreurApiSync(Exception):
    """Erreur générique de communication avec l'API de synchronisation."""


class ErreurInjoignable(ErreurApiSync):
    """La machine boss n'a pas répondu (réseau/Tailscale/serveur éteint) —
    erreur transitoire : le worker de synchro doit réessayer plus tard."""


class ErreurAuthentification(ErreurApiSync):
    """Jeton `role_facturation` refusé (401)."""


class ErreurPermission(ErreurApiSync):
    """Action refusée pour ce rôle (403)."""


class ErreurMetierDistante(ErreurApiSync):
    """Le serveur a rejeté l'opération pour une raison métier (400) — pas de
    retry automatique, l'utilisateur doit être notifié."""


class ApiSyncClient:
    """Enveloppe fine autour de `requests` pour dialoguer avec
    `app/api/routes_sync.py`."""

    def __init__(self, config: ConfigSync) -> None:
        self._config = config

    def _en_tetes(self) -> dict:
        en_tetes = {"X-API-Key": self._config.token}
        if self._config.machine_id:
            en_tetes["X-Machine-Id"] = self._config.machine_id
        return en_tetes

    def _requete(self, methode: str, chemin: str, *,
                delai_lecture: int = _DELAI_LECTURE, **kwargs) -> requests.Response:
        try:
            reponse = requests.request(
                methode, f"{self._config.base_url}{chemin}",
                headers=self._en_tetes(),
                timeout=(_DELAI_CONNEXION, delai_lecture), **kwargs,
            )
        except requests.exceptions.RequestException as exc:
            raise ErreurInjoignable(str(exc)) from exc
        if reponse.status_code == 401:
            raise ErreurAuthentification("Jeton API invalide.")
        if reponse.status_code == 403:
            raise ErreurPermission("Action non autorisée pour ce rôle.")
        if reponse.status_code == 400:
            raise ErreurMetierDistante(reponse.json().get("detail", reponse.text))
        if not reponse.ok:
            raise ErreurApiSync(f"Erreur API ({reponse.status_code}) : {reponse.text}")
        return reponse

    def tester_connexion(self) -> bool:
        """Vrai si la machine boss répond (sans vérifier le jeton)."""
        try:
            reponse = requests.get(f"{self._config.base_url}/health",
                                   timeout=(_DELAI_CONNEXION, _DELAI_CONNEXION))
            return reponse.ok
        except requests.exceptions.RequestException:
            return False

    def reserver_numeros(self, quantite: int, delai_court: bool = False) -> dict:
        """Retourne `{numeros, n_postes_actifs, rang}` (voir CLAUDE.md,
        section « Numérotation résiliente »). `delai_court=True` (palier 1,
        JIT depuis l'interface) réduit le délai de lecture pour ne jamais
        bloquer longtemps si le serveur est lent ou injoignable — le palier 2
        (pool de secours, alimenté en tâche de fond) garde le délai normal."""
        corps = {"quantite": quantite, "machine_id": self._config.machine_id}
        delai = _DELAI_JIT if delai_court else _DELAI_LECTURE
        return self._requete(
            "POST", "/factures/reserver-numeros", json=corps, delai_lecture=delai,
        ).json()

    def dernier_numero_connu(self) -> int:
        """Lecture seule, sans verrou — sondage continu (palier 1, toutes les
        3-5s, voir `NumeroPollerWorker`). Délai de lecture court : un
        ralentissement isolé ne doit jamais faire attendre le worker."""
        return self._requete(
            "GET", "/factures/dernier-numero", delai_lecture=_DELAI_POLL,
        ).json()["dernier_numero"]

    def envoyer_operation(self, type_operation: str, cle_correlation: str,
                          payload: dict, cree_le: str = "") -> dict:
        corps = {"type_operation": type_operation, "cle_correlation": cle_correlation,
                "payload": payload, "cree_le": cree_le}
        return self._requete("POST", "/sync/operation", json=corps).json()

    def referentiel_produits(self) -> list[dict]:
        return self._requete("GET", "/referentiels/produits").json()

    def referentiel_clients(self) -> list[dict]:
        return self._requete("GET", "/referentiels/clients").json()

    # Admin distant (Archive) — pages réseau uniquement de la machine de
    # facturation en mode étendu, jamais exposées au mode client léger
    # (`app.client.api_client.ApiClient`) : voir CLAUDE.md, section « Machine
    # de facturation ». -------------------------------------------------------
    def lister_factures_admin(
        self, archivee: bool | None = None,
        date_debut: date | None = None, date_fin: date | None = None,
        client_id: int | None = None,
    ) -> list[dict]:
        params: dict = {}
        if archivee is not None:
            params["archivee"] = archivee
        if date_debut:
            params["date_debut"] = date_debut.isoformat()
        if date_fin:
            params["date_fin"] = date_fin.isoformat()
        if client_id:
            params["client_id"] = client_id
        return self._requete("GET", "/admin/factures", params=params).json()

    def obtenir_facture_admin(self, facture_id: int) -> dict:
        return self._requete("GET", f"/admin/factures/{facture_id}").json()

    def telecharger_pdf_admin(self, facture_id: int) -> bytes:
        return self._requete("GET", f"/admin/factures/{facture_id}/pdf").content

    def telecharger_bordereau_admin(self, facture_id: int) -> bytes:
        return self._requete("GET", f"/admin/factures/{facture_id}/bordereau").content

    def archiver_ids(self, ids: list[int]) -> int:
        return self._requete(
            "POST", "/admin/factures/archiver-ids", json={"ids": ids}).json()["nb"]

    def desarchiver_ids(self, ids: list[int]) -> int:
        return self._requete(
            "POST", "/admin/factures/desarchiver-ids", json={"ids": ids}).json()["nb"]

    def archiver_periode(self, date_debut: date, date_fin: date,
                         client_id: int | None = None) -> int:
        corps = {"date_debut": date_debut.isoformat(), "date_fin": date_fin.isoformat(),
                "client_id": client_id}
        return self._requete("POST", "/admin/factures/archiver-periode", json=corps).json()["nb"]

    def desarchiver_periode(self, date_debut: date, date_fin: date,
                            client_id: int | None = None) -> int:
        corps = {"date_debut": date_debut.isoformat(), "date_fin": date_fin.isoformat(),
                "client_id": client_id}
        return self._requete(
            "POST", "/admin/factures/desarchiver-periode", json=corps).json()["nb"]

    def statut_archivage(self, numeros: list[int]) -> list[int]:
        """Parmi ces numéros usine, ceux actuellement archivés sur le boss —
        alimente `ArchiveStatutSyncWorker` (synchronisation descendante du
        statut d'archivage vers le cache local)."""
        return self._requete(
            "POST", "/admin/factures/statut-archivage",
            json={"numeros": numeros}).json()["numeros_archives"]

