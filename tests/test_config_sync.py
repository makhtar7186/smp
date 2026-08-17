"""Tests de la configuration persistante de la machine de facturation
(sync_config.json) — même idiome que app.client.config_client, tolérant au
fichier absent/corrompu."""
from __future__ import annotations

from pathlib import Path

from app.sync import config_sync


def test_charger_sans_fichier_retourne_defauts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(config_sync, "CHEMIN_CONFIG_SYNC", tmp_path / "absent.json")
    config = config_sync.charger()
    assert config.hote == ""
    assert config.port == 8420
    assert config.complete is False


def test_charger_fichier_corrompu_retourne_defauts(tmp_path: Path, monkeypatch) -> None:
    chemin = tmp_path / "sync_config.json"
    chemin.write_text("{ceci n'est pas du json", encoding="utf-8")
    monkeypatch.setattr(config_sync, "CHEMIN_CONFIG_SYNC", chemin)
    config = config_sync.charger()
    assert config.hote == ""


def test_sauvegarder_puis_charger_aller_retour(tmp_path: Path, monkeypatch) -> None:
    chemin = tmp_path / "sync_config.json"
    monkeypatch.setattr(config_sync, "CHEMIN_CONFIG_SYNC", chemin)
    original = config_sync.ConfigSync(
        hote="100.65.90.44", port=8420, token="jeton-facturation",
        machine_id="comptoir-1", intervalle_sync_secondes=60,
        intervalle_referentiels_secondes=180,
    )
    config_sync.sauvegarder(original)
    relu = config_sync.charger()
    assert relu == original
    assert relu.complete is True
