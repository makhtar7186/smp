"""Tests des nouvelles méthodes Dashboard/Remises de ApiClient — requêtes
simulées via unittest.mock (même style que tests/test_api_sync_client.py),
sans dépendance réseau réelle."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from app.client.api_client import ApiClient
from app.client.config_client import ConfigClient


def _config() -> ConfigClient:
    return ConfigClient(hote="127.0.0.1", port=8420, token="jeton", machine_id="m1")


class _FauxeReponse:
    def __init__(self, donnees) -> None:
        self.status_code = 200
        self.ok = True
        self._donnees = donnees

    def json(self):
        return self._donnees


def test_stats_kpis() -> None:
    client = ApiClient(_config())
    donnees = {"ca_jour": {"valeur": 1, "precedent": 0, "variation_pct": None}}
    with patch("requests.request", return_value=_FauxeReponse(donnees)) as appel:
        assert client.stats_kpis(date(2026, 3, 1)) == donnees
        assert appel.call_args.kwargs["params"] == {"jour": "2026-03-01"}


def test_stats_top_produits() -> None:
    client = ApiClient(_config())
    with patch("requests.request", return_value=_FauxeReponse([{"libelle": "X", "valeur": 1}])):
        resultat = client.stats_top_produits(date(2026, 1, 1), date(2026, 12, 31))
        assert resultat == [{"libelle": "X", "valeur": 1}]


def test_stats_repartition_gamme() -> None:
    client = ApiClient(_config())
    with patch("requests.request", return_value=_FauxeReponse([{"gamme": "G", "ca": 1}])):
        assert client.stats_repartition_gamme(date(2026, 1, 1), date(2026, 12, 31)) == [
            {"gamme": "G", "ca": 1}]


def test_stats_serie_ca() -> None:
    client = ApiClient(_config())
    with patch("requests.request", return_value=_FauxeReponse([{"periode": "2026-01", "ca": 1}])):
        assert client.stats_serie_ca(date(2026, 1, 1), date(2026, 12, 31)) == [
            {"periode": "2026-01", "ca": 1}]


def test_remises_tableau() -> None:
    client = ApiClient(_config())
    with patch("requests.request", return_value=_FauxeReponse([{"client_id": 1}])) as appel:
        assert client.remises_tableau(2026) == [{"client_id": 1}]
        assert appel.call_args.kwargs["params"] == {"annee": 2026}
