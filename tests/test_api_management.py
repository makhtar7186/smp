"""Tests du service de gestion du serveur API : configuration, jeton,
démarrage automatique (dossier de démarrage Windows). Le démarrage/arrêt du
processus réel n'est pas testé ici (dépend de l'OS) — voir vérification
manuelle documentée dans CLAUDE.md."""
from __future__ import annotations

from app.services.api_management_service import ApiManagementService


def test_config_par_defaut(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    service = ApiManagementService()
    config_lue = service.config()
    assert config_lue["host"] == "127.0.0.1"
    assert config_lue["port"] == 8420
    assert config_lue["token_client"] == ""
    assert config_lue["token_principal"] == ""
    assert config_lue["token_facturation"] == ""
    assert config_lue["token_stock"] == ""


def test_enregistrer_config_persiste(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    service = ApiManagementService()
    service.enregistrer_config("100.65.90.44", 9000, "jeton-client", "jeton-principal",
                               "jeton-facturation", "jeton-stock")
    config_lue = service.config()
    assert config_lue == {"host": "100.65.90.44", "port": 9000,
                          "token_client": "jeton-client",
                          "token_principal": "jeton-principal",
                          "token_facturation": "jeton-facturation",
                          "token_stock": "jeton-stock"}


def test_generer_jeton_est_unique_et_non_vide():
    service = ApiManagementService()
    a, b = service.generer_jeton(), service.generer_jeton()
    assert a and b and a != b


def test_en_ligne_faux_sur_port_libre(tmp_path, monkeypatch):
    from app import config
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    service = ApiManagementService()
    service.enregistrer_config("127.0.0.1", 8421, "x", "y")  # port inutilisé
    assert service.en_ligne() is False


class TestPersistanceApiActif:
    """`demarrer()`/`arreter()` doivent persister l'intention de garder le
    serveur actif aux prochains lancements (`config.api_active()`) — sans
    quoi `Application._demarrer_api_si_active`/
    `ApplicationClient._demarrer_serveur_si_actif` ne relancent jamais le
    serveur automatiquement, même après l'avoir démarré une fois."""

    def test_inactif_par_defaut(self, tmp_path, monkeypatch):
        from app import config
        monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
        monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
        assert config.api_active() is False

    def test_demarrer_persiste_actif(self, tmp_path, monkeypatch):
        from app import config
        monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
        monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
        service = ApiManagementService()
        monkeypatch.setattr(service, "en_ligne", lambda: True)  # déjà en ligne : pas de subprocess réel
        service.demarrer()
        assert config.api_active() is True

    def test_arreter_persiste_inactif(self, tmp_path, monkeypatch):
        from app import config
        monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
        monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
        config.definir_api_active(True)
        service = ApiManagementService()
        monkeypatch.setattr(service, "_pid_a_l_ecoute", lambda port: 4242)

        class _ResultatFactice:
            returncode = 0
            stderr = ""

        monkeypatch.setattr(
            "app.services.api_management_service.subprocess.run",
            lambda *a, **k: _ResultatFactice())
        service.arreter()
        assert config.api_active() is False


class TestDemarrageAuto:
    def test_inactif_par_defaut(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        service = ApiManagementService()
        assert service.demarrage_auto_actif() is False

    def test_activer_puis_desactiver(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        service = ApiManagementService()
        service.activer_demarrage_auto(True)
        assert service.demarrage_auto_actif() is True
        chemin = service._chemin_fichier_demarrage()
        assert chemin.exists()
        assert "app.api.server" in chemin.read_text(encoding="utf-8")

        service.activer_demarrage_auto(False)
        assert service.demarrage_auto_actif() is False
        assert not chemin.exists()
