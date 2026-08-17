"""Tests des méthodes admin distant de ApiSyncClient (Archive) — requêtes
simulées via unittest.mock, même style que tests/test_api_sync_client.py."""
from __future__ import annotations

from datetime import date

from app.sync.api_sync_client import ApiSyncClient
from app.sync.config_sync import ConfigSync


def _config() -> ConfigSync:
    return ConfigSync(hote="127.0.0.1", port=8420, token="jeton", machine_id="m1")


class _FauxeReponse:
    def __init__(self, status_code: int, donnees=None) -> None:
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._donnees = donnees if donnees is not None else {}
        self.text = str(donnees)
        self.content = b"%PDF-1.4 faux contenu"

    def json(self):
        return self._donnees


def test_lister_factures_admin() -> None:
    from unittest.mock import patch
    client = ApiSyncClient(_config())
    with patch("requests.request", return_value=_FauxeReponse(200, [{"id": 1}])) as appel:
        assert client.lister_factures_admin(archivee=False) == [{"id": 1}]
        assert appel.call_args.kwargs["params"]["archivee"] is False


def test_facture_admin_detail_pdf_bordereau() -> None:
    """Sert la page « Historique complet » (historique_view_distant.py) —
    détail/PDF/bordereau d'une facture usine, inaccessibles via routes.py au
    rôle role_facturation."""
    from unittest.mock import patch
    client = ApiSyncClient(_config())
    with patch("requests.request", return_value=_FauxeReponse(200, {"id": 1, "numero": 260901})):
        assert client.obtenir_facture_admin(1) == {"id": 1, "numero": 260901}
    with patch("requests.request", return_value=_FauxeReponse(200)):
        assert client.telecharger_pdf_admin(1) == b"%PDF-1.4 faux contenu"
        assert client.telecharger_bordereau_admin(1) == b"%PDF-1.4 faux contenu"


def test_statut_archivage() -> None:
    """Sert ArchiveStatutSyncWorker (synchronisation descendante du statut
    d'archivage vers le cache local de la machine de facturation)."""
    from unittest.mock import patch
    client = ApiSyncClient(_config())
    with patch("requests.request",
              return_value=_FauxeReponse(200, {"numeros_archives": [1, 3]})) as appel:
        assert client.statut_archivage([1, 2, 3]) == [1, 3]
        assert appel.call_args.kwargs["json"] == {"numeros": [1, 2, 3]}


def test_archiver_desarchiver_ids() -> None:
    from unittest.mock import patch
    client = ApiSyncClient(_config())
    with patch("requests.request", return_value=_FauxeReponse(200, {"nb": 3})):
        assert client.archiver_ids([1, 2, 3]) == 3
        assert client.desarchiver_ids([1, 2, 3]) == 3


def test_archiver_desarchiver_periode() -> None:
    from unittest.mock import patch
    client = ApiSyncClient(_config())
    with patch("requests.request", return_value=_FauxeReponse(200, {"nb": 5})):
        assert client.archiver_periode(date(2026, 1, 1), date(2026, 12, 31)) == 5
        assert client.desarchiver_periode(date(2026, 1, 1), date(2026, 12, 31)) == 5
