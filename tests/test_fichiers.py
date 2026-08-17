"""Tests d'ouvrir_fichier : bonne commande système selon la plateforme."""
from __future__ import annotations

from app.utils.fichiers import ouvrir_fichier


def test_windows_utilise_startfile(monkeypatch):
    monkeypatch.setattr("sys.platform", "win32")
    appels = []
    monkeypatch.setattr("os.startfile", lambda chemin: appels.append(chemin),
                        raising=False)
    ouvrir_fichier("C:\\test.pdf")
    assert appels == ["C:\\test.pdf"]


def test_macos_utilise_open(monkeypatch):
    monkeypatch.setattr("sys.platform", "darwin")
    appels = []
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: appels.append(cmd) or type(
                            "R", (), {"returncode": 0})())
    ouvrir_fichier("/tmp/test.pdf")
    assert appels == [["open", "/tmp/test.pdf"]]


def test_linux_utilise_xdg_open(monkeypatch):
    monkeypatch.setattr("sys.platform", "linux")
    appels = []
    monkeypatch.setattr("subprocess.run",
                        lambda cmd, **kw: appels.append(cmd) or type(
                            "R", (), {"returncode": 0})())
    ouvrir_fichier("/tmp/test.pdf")
    assert appels == [["xdg-open", "/tmp/test.pdf"]]


def test_repli_navigateur_si_echec(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "darwin")

    def _echoue(cmd, **kw):
        raise FileNotFoundError("open introuvable")
    monkeypatch.setattr("subprocess.run", _echoue)
    appels = []
    monkeypatch.setattr("webbrowser.open", lambda url: appels.append(url))
    chemin = tmp_path / "test.pdf"
    chemin.write_text("x")
    ouvrir_fichier(chemin)
    assert len(appels) == 1
    assert appels[0].startswith("file:")
