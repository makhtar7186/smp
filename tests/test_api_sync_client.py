"""Tests du client HTTP de synchronisation (mapping des codes d'erreur) —
requêtes simulées via unittest.mock, sans dépendance réseau réelle."""
from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from app.sync.api_sync_client import (
    ApiSyncClient,
    ErreurAuthentification,
    ErreurInjoignable,
    ErreurMetierDistante,
    ErreurPermission,
)
from app.sync.config_sync import ConfigSync


def _config() -> ConfigSync:
    return ConfigSync(hote="127.0.0.1", port=8420, token="jeton", machine_id="m1")


class _FauxeReponse:
    def __init__(self, status_code: int, donnees: dict | None = None) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._donnees = donnees or {}
        self.text = str(donnees)

    def json(self) -> dict:
        return self._donnees


def test_injoignable_leve_erreur_dediee() -> None:
    client = ApiSyncClient(_config())
    with patch("requests.request", side_effect=requests.exceptions.ConnectionError()):
        with pytest.raises(ErreurInjoignable):
            client.reserver_numeros(5)


def test_401_leve_erreur_authentification() -> None:
    client = ApiSyncClient(_config())
    with patch("requests.request", return_value=_FauxeReponse(401)):
        with pytest.raises(ErreurAuthentification):
            client.reserver_numeros(5)


def test_403_leve_erreur_permission() -> None:
    client = ApiSyncClient(_config())
    with patch("requests.request", return_value=_FauxeReponse(403)):
        with pytest.raises(ErreurPermission):
            client.reserver_numeros(5)


def test_400_leve_erreur_metier_distante() -> None:
    client = ApiSyncClient(_config())
    with patch("requests.request",
               return_value=_FauxeReponse(400, {"detail": "fact_panier_vide"})):
        with pytest.raises(ErreurMetierDistante, match="fact_panier_vide"):
            client.envoyer_operation("creation_facture", "usine:260001", {})


def test_200_retourne_les_donnees() -> None:
    client = ApiSyncClient(_config())
    donnees = {"numeros": [1, 2, 3], "n_postes_actifs": 1, "rang": 0}
    with patch("requests.request", return_value=_FauxeReponse(200, donnees)):
        assert client.reserver_numeros(3) == donnees


def test_dernier_numero_connu_appelle_l_endpoint_leger() -> None:
    """Palier 1 (sondage continu) — voir CLAUDE.md, « Numérotation résiliente »."""
    client = ApiSyncClient(_config())
    with patch("requests.request",
               return_value=_FauxeReponse(200, {"dernier_numero": 261611})) as mock_requete:
        assert client.dernier_numero_connu() == 261611
    methode, url = mock_requete.call_args.args
    assert methode == "GET"
    assert url.endswith("/factures/dernier-numero")
