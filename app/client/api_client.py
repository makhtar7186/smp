"""Client HTTP de l'API distante. Historiquement lecture seule ; expose
désormais aussi l'écriture des versements et de la remise **annuelle** —
la remise **par facture** reste réservée à `role_principal` (l'app
principale écrit les factures, donc leur remise) et n'est volontairement
pas exposée ici. Voir CLAUDE.md, section « Paiements »."""
from __future__ import annotations

from datetime import date

import requests

from app.client.config_client import ConfigClient

_DELAI_CONNEXION = 4       # secondes — la machine principale est sur le LAN/Tailscale
_DELAI_LECTURE = 15        # laisse le temps de régénérer un PDF


class ErreurApiClient(Exception):
    """Erreur générique de communication avec l'API distante."""


class ErreurInjoignable(ErreurApiClient):
    """La machine principale n'a pas répondu (réseau/Tailscale/appli éteinte)."""


class ErreurAuthentification(ErreurApiClient):
    """Jeton API refusé (401)."""


class ErreurPermission(ErreurApiClient):
    """Action refusée pour le rôle de ce jeton (403) — ex. un jeton
    `role_principal` tentant d'enregistrer un versement."""


class ApiClient:
    """Enveloppe fine autour de `requests` pour dialoguer avec `app.api`."""

    def __init__(self, config: ConfigClient) -> None:
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
            raise ErreurApiClient(f"Erreur API ({reponse.status_code}) : {reponse.text}")
        return reponse

    def tester_connexion(self) -> bool:
        """Vrai si la machine principale répond (sans vérifier le jeton) —
        sert à distinguer « injoignable » de « jeton invalide »."""
        try:
            reponse = requests.get(f"{self._config.base_url}/health",
                                   timeout=(_DELAI_CONNEXION, _DELAI_CONNEXION))
            return reponse.ok
        except requests.exceptions.RequestException:
            return False

    # Historique / impression (lecture seule) -----------------------------------
    def lister_factures(self, date_debut: date | None = None,
                        date_fin: date | None = None) -> list[dict]:
        params = {}
        if date_debut:
            params["date_debut"] = date_debut.isoformat()
        if date_fin:
            params["date_fin"] = date_fin.isoformat()
        return self._requete("GET", "/factures", params=params).json()

    def obtenir_facture(self, facture_id: int) -> dict:
        return self._requete("GET", f"/factures/{facture_id}").json()

    def telecharger_pdf(self, facture_id: int) -> bytes:
        return self._requete("GET", f"/factures/{facture_id}/pdf").content

    def telecharger_bordereau(self, facture_id: int) -> bytes:
        return self._requete("GET", f"/factures/{facture_id}/bordereau").content

    # Paiements -------------------------------------------------------------------
    def lister_factures_paiements(self, recherche: str = "",
                                  client_id: int | None = None,
                                  date_debut: date | None = None,
                                  date_fin: date | None = None) -> list[dict]:
        params = {"recherche": recherche}
        if client_id:
            params["client_id"] = client_id
        if date_debut:
            params["date_debut"] = date_debut.isoformat()
        if date_fin:
            params["date_fin"] = date_fin.isoformat()
        return self._requete("GET", "/paiements/factures", params=params).json()

    def obtenir_facture_paiement(self, facture_id: int) -> dict:
        return self._requete("GET", f"/paiements/facture/{facture_id}").json()

    def creer_versement(self, facture_id: int, montant: int,
                        date_versement: date, remarque: str = "") -> dict:
        """Réservé au rôle `role_client` — lève ErreurPermission (403) sinon."""
        return self._requete(
            "POST", f"/paiements/facture/{facture_id}/versement",
            json={"montant": montant, "date_versement": date_versement.isoformat(),
                 "remarque": remarque},
        ).json()

    def importer_paiements_legacy(self, lignes: list[dict]) -> dict:
        """Import ponctuel d'un résumé de paiements historiques (une facture
        « coquille » + versement par ligne, voir CLAUDE.md) — réservé au
        rôle `role_client`, même permission que `creer_versement`. `lignes`
        déjà validées côté appelant (numéro/montant numériques) : chaque
        élément a la forme `{numero, date_facture (ISO), client_nom,
        montant, versement, commentaire}`. Retourne le rapport serveur
        `{importees, ignorees, avertissements}`."""
        return self._requete(
            "POST", "/paiements/import-legacy", json={"lignes": lignes},
        ).json()

    def appliquer_remise_annuelle(self, client_id: int, annee: int, ca_annuel: int,
                                  taux: float, note: str = "") -> dict:
        return self._requete(
            "POST", f"/clients/{client_id}/remise-annuelle",
            json={"annee": annee, "ca_annuel": ca_annuel, "taux": taux, "note": note},
        ).json()

    def totaux_paiements(self, **filtres) -> dict:
        return self._requete("GET", "/paiements/totaux", params=filtres).json()

    def synthese_client(self, client_id: int, annee: int | None = None,
                        date_debut: date | None = None, date_fin: date | None = None) -> dict:
        """`date_debut`/`date_fin` définissent une période précise (ex. un
        mois), prioritaire sur `annee` dès que l'une des deux est fournie."""
        params: dict = {}
        if date_debut is not None or date_fin is not None:
            if date_debut is not None:
                params["date_debut"] = date_debut.isoformat()
            if date_fin is not None:
                params["date_fin"] = date_fin.isoformat()
        elif annee is not None:
            params["annee"] = annee
        return self._requete(
            "GET", f"/paiements/client/{client_id}/synthese", params=params).json()

    def rechercher_clients(self, q: str) -> list[dict]:
        return self._requete("GET", "/clients/recherche", params={"q": q}).json()

    # Dashboard / Remises (onglets « Dashboard »/« Remises » du mode client,
    # pertinents quand ce poste héberge désormais la base — voir CLAUDE.md,
    # section « Machine de facturation ») -----------------------------------
    def stats_kpis(self, jour: date | None = None) -> dict:
        params = {"jour": jour.isoformat()} if jour else {}
        return self._requete("GET", "/stats/kpis", params=params).json()

    def stats_top_produits(self, debut: date, fin: date, par: str = "quantite",
                           limite: int = 10) -> list[dict]:
        return self._requete("GET", "/stats/top-produits", params={
            "debut": debut.isoformat(), "fin": fin.isoformat(), "par": par,
            "limite": limite,
        }).json()

    def stats_repartition_gamme(self, debut: date, fin: date) -> list[dict]:
        return self._requete("GET", "/stats/repartition-gamme", params={
            "debut": debut.isoformat(), "fin": fin.isoformat(),
        }).json()

    def stats_serie_ca(self, debut: date, fin: date,
                       granularite: str = "mois") -> list[dict]:
        return self._requete("GET", "/stats/serie-ca", params={
            "debut": debut.isoformat(), "fin": fin.isoformat(),
            "granularite": granularite,
        }).json()

    def remises_tableau(self, annee: int) -> list[dict]:
        return self._requete("GET", "/remises/tableau", params={"annee": annee}).json()
