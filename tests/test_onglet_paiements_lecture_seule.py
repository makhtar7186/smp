"""Tests de OngletPaiements(autoriser_versement=...) — non-régression du
mode client léger (défaut True, bouton toujours présent) et du mode lecture
seule utilisé par ApplicationFacturationEtendue (voir CLAUDE.md, section
« Machine de facturation »)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.client import archive_client, config_client, queue_hors_ligne
from app.client.ui import ApplicationClient, OngletPaiements
from app.i18n.translations import t


@pytest.fixture()
def app_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "CHEMIN_DB", tmp_path / "promatelas.db")
    monkeypatch.setattr(config_client, "CHEMIN_CONFIG_CLIENT", tmp_path / "client_config.json")
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT",
                        tmp_path / "factures_archivees_client.json")
    monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "versements_en_attente.json")
    application = ApplicationClient()
    application.withdraw()
    yield application
    application.destroy()


def _textes_boutons(widget) -> list[str]:
    textes = []
    for enfant in widget.winfo_children():
        if enfant.winfo_class() == "TButton":
            textes.append(str(enfant.cget("text")))
        textes.extend(_textes_boutons(enfant))
    return textes


def test_defaut_autorise_versement_bouton_present(app_client) -> None:
    onglet = app_client.onglet_paiements
    assert onglet._autoriser_versement is True
    textes = _textes_boutons(onglet)
    assert t("paie_ajouter_versement") in textes
    # Le label hors-ligne existe et est packé (mode écriture normal).
    assert onglet._label_hors_ligne.winfo_manager() == "pack"


def test_lecture_seule_masque_bouton_versement_et_indicateur(app_client) -> None:
    onglet = OngletPaiements(app_client, app_client, autoriser_versement=False)
    assert onglet._autoriser_versement is False
    assert t("paie_ajouter_versement") not in _textes_boutons(onglet)
    assert t("paie_renvoyer_attente") not in _textes_boutons(onglet)
    # Le label hors-ligne existe (widget construit) mais n'est jamais packé.
    assert onglet._label_hors_ligne.winfo_manager() == ""


def test_lecture_seule_maj_indicateur_est_no_op(app_client) -> None:
    onglet = OngletPaiements(app_client, app_client, autoriser_versement=False)
    onglet._maj_indicateur_hors_ligne()  # ne doit pas lever, ni toucher le label
    assert onglet._label_hors_ligne.cget("text") == ""
