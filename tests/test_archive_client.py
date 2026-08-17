"""Tests de l'archivage local du mode client (app.client.archive_client) —
indépendant de l'archivage de l'application principale, voir CLAUDE.md,
section « Archivage »."""
from __future__ import annotations

from app.client import archive_client


def test_vide_par_defaut(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    assert archive_client.charger() == set()


def test_archiver_puis_charger(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.archiver(42)
    archive_client.archiver(7)
    assert archive_client.charger() == {42, 7}


def test_desarchiver(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.archiver(42)
    archive_client.desarchiver(42)
    assert archive_client.charger() == set()


def test_desarchiver_id_absent_ne_leve_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.desarchiver(999)
    assert archive_client.charger() == set()


def test_fichier_corrompu_traite_comme_vide(tmp_path, monkeypatch):
    chemin = tmp_path / "archive.json"
    chemin.write_text("{ceci n'est pas du json", encoding="utf-8")
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", chemin)
    assert archive_client.charger() == set()


def test_archiver_plusieurs(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.archiver_plusieurs([1, 2, 3])
    assert archive_client.charger() == {1, 2, 3}


def test_archiver_plusieurs_cumule_avec_existant(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.archiver(1)
    archive_client.archiver_plusieurs([2, 3])
    assert archive_client.charger() == {1, 2, 3}


def test_desarchiver_plusieurs(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.archiver_plusieurs([1, 2, 3])
    archive_client.desarchiver_plusieurs([1, 2])
    assert archive_client.charger() == {3}


def test_desarchiver_plusieurs_ids_absents_ne_leve_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT", tmp_path / "archive.json")
    archive_client.desarchiver_plusieurs([100, 200])
    assert archive_client.charger() == set()
