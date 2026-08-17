"""Tests de la bascule de mode machine (config.py) et du dispatch
app/main.py — voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_mode_par_defaut_principale(tmp_path, monkeypatch) -> None:
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    assert config.lire_mode_machine() == "principale"


def test_definir_puis_relire(tmp_path, monkeypatch) -> None:
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    config.definir_mode_machine("facturation_distante")
    assert config.lire_mode_machine() == "facturation_distante"
    config.definir_mode_machine("principale")
    assert config.lire_mode_machine() == "principale"


def test_valeur_invalide_leve(tmp_path, monkeypatch) -> None:
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    with pytest.raises(ValueError):
        config.definir_mode_machine("autre_chose")


def test_valeur_corrompue_dans_settings_retombe_sur_principale(tmp_path, monkeypatch) -> None:
    from app import config
    chemin = tmp_path / "settings.json"
    chemin.write_text('{"mode_machine": "n_importe_quoi"}', encoding="utf-8")
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", chemin)
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    assert config.lire_mode_machine() == "principale"


def test_main_dispatch_mode_principale(monkeypatch) -> None:
    from app import config, main as main_module
    monkeypatch.setattr(config, "lire_mode_machine", lambda: "principale")
    with patch("app.ui.app.lancer") as lancer_principale:
        main_module.main()
        lancer_principale.assert_called_once()


def test_main_dispatch_mode_facturation_distante(monkeypatch) -> None:
    from app import config, main as main_module
    monkeypatch.setattr(config, "lire_mode_machine", lambda: "facturation_distante")
    with patch("app.ui.app_facturation_etendue.lancer") as lancer_etendue:
        main_module.main()
        lancer_etendue.assert_called_once()
