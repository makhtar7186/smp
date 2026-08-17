"""Smoke test : ApplicationClient (mode client) se construit avec son
nouvel onglet « Serveur », qui pilote SMP-Serveur.exe directement
depuis ce poste — pertinent quand ce poste héberge la base (voir CLAUDE.md,
section « Machine de facturation »). N'appelle jamais `mainloop()` ni ne
démarre de serveur réel (le `after(150, ...)` de démarrage du client ne se
déclenche pas sans boucle d'événements active)."""
from __future__ import annotations

from pathlib import Path

import pytest

from app import config
from app.client import archive_client, config_client, queue_hors_ligne
from app.client.ui import ApplicationClient


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


def test_onglet_serveur_construit_et_s_actualise(app_client) -> None:
    app = app_client
    assert app.onglet_serveur is not None
    assert app.api_management is not None
    statut = app.api_management.config()
    assert statut["host"] == "127.0.0.1"
    assert statut["token_facturation"] == ""


def test_generer_et_enregistrer_les_trois_jetons(app_client) -> None:
    app = app_client
    onglet = app.onglet_serveur
    onglet._generer_jeton_client()
    onglet._generer_jeton_principal()
    onglet._generer_jeton_facturation()
    assert onglet.var_jeton_client.get()
    assert onglet.var_jeton_principal.get()
    assert onglet.var_jeton_facturation.get()

    onglet.var_hote.set("100.64.1.2")
    onglet.var_port.set("8420")
    onglet._enregistrer_config()

    config_relue = app.api_management.config()
    assert config_relue["host"] == "100.64.1.2"
    assert config_relue["token_facturation"] == onglet.var_jeton_facturation.get()


def test_actualiser_general_rafraichit_aussi_l_onglet_serveur(app_client) -> None:
    app = app_client
    app.onglet_serveur.var_hote.set("")  # simule un état différent du fichier
    app.actualiser()
    assert app.onglet_serveur.var_hote.get() == "127.0.0.1"


def test_config_auto_locale_absente_sans_jeton_client(app_client) -> None:
    """Aucun serveur local configuré (aucun jeton `role_client`) : pas de
    connexion automatique possible, l'onglet Connexion manuel reste requis."""
    assert app_client._config_auto_locale() is None


def test_config_auto_locale_derivee_du_jeton_client_local(app_client) -> None:
    """Dès que l'onglet Serveur a un jeton `role_client` enregistré, la
    connexion se déduit automatiquement (127.0.0.1, même port/jeton) —
    plus besoin de ressaisir la même chose via « Connexion »."""
    app = app_client
    onglet = app.onglet_serveur
    onglet._generer_jeton_client()
    onglet.var_hote.set("100.64.1.2")  # l'hôte réseau ne doit pas influencer l'auto-connexion locale
    onglet.var_port.set("9500")
    onglet._enregistrer_config()

    auto = app._config_auto_locale()
    assert auto is not None
    assert auto.hote == "127.0.0.1"
    assert auto.port == 9500
    assert auto.token == onglet.var_jeton_client.get()


def test_rafraichir_connexion_auto_met_a_jour_api_et_actualise(app_client) -> None:
    app = app_client
    assert app.api is None
    onglet = app.onglet_serveur
    onglet._generer_jeton_client()
    onglet.var_port.set("8420")
    onglet._enregistrer_config()  # appelle déjà rafraichir_connexion_auto()

    assert app.api is not None
    assert app.config.hote == "127.0.0.1"
    assert app.config.token == onglet.var_jeton_client.get()


def test_rafraichir_connexion_auto_no_op_sans_jeton_client(app_client) -> None:
    """Si aucun jeton `role_client` n'est configuré, l'appel ne doit rien
    changer (ni lever, ni fabriquer une config invalide)."""
    app = app_client
    app.rafraichir_connexion_auto()
    assert app.api is None


def test_demarrage_serveur_auto_si_jeton_client_local_deja_configure(
    tmp_path: Path, monkeypatch,
) -> None:
    """Un poste déjà configuré pour héberger sa propre base (jeton
    `role_client` présent) doit toujours tenter de démarrer le serveur au
    lancement — même si `api_actif` n'a jamais été positionné (ex. poste
    configuré avant l'ajout de cette persistance, ou `api_actif` resté à
    `False` pour toute autre raison). Sans ce second déclencheur, un
    versement échouerait indéfiniment avec « serveur injoignable » sans que
    l'utilisateur comprenne pourquoi."""
    from app.client import archive_client, config_client, queue_hors_ligne
    from app.client.ui import ApplicationClient
    from app.services.api_management_service import ApiManagementService

    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "CHEMIN_DB", tmp_path / "promatelas.db")
    monkeypatch.setattr(config_client, "CHEMIN_CONFIG_CLIENT", tmp_path / "client_config.json")
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT",
                        tmp_path / "factures_archivees_client.json")
    monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "versements_en_attente.json")

    # Jeton role_client déjà configuré (onglet Serveur d'une session précédente),
    # mais api_actif jamais positionné (False par défaut).
    config.sauver_api_config(token_client="jeton-client-existant")
    assert config.api_active() is False

    appels = []
    monkeypatch.setattr(ApiManagementService, "demarrer", lambda self: appels.append(1))

    application = ApplicationClient()
    application.withdraw()
    try:
        assert appels == [1]
    finally:
        application.destroy()


def test_demarrage_priorise_la_connexion_manuelle_sur_l_auto_connexion_locale(
    tmp_path: Path, monkeypatch,
) -> None:
    """Une connexion manuelle déjà enregistrée (bouton « Connexion », ex. IP
    Tailscale d'une machine boss distante) est un choix explicite et doit
    toujours l'emporter sur l'auto-connexion locale — même si un jeton
    `role_client` existe aussi sur ce poste (ex. onglet Serveur testé une
    fois sans intention de s'en servir). Sans cette priorité, un poste
    observateur distant se reconnectait malgré tout à 127.0.0.1 à chaque
    lancement, ignorant la config Tailscale pourtant enregistrée."""
    from app.client import archive_client, config_client, queue_hors_ligne
    from app.client.config_client import ConfigClient, sauvegarder
    from app.client.ui import ApplicationClient
    from app.services.api_management_service import ApiManagementService

    monkeypatch.setattr(config, "DOSSIER_DATA", tmp_path)
    monkeypatch.setattr(config, "CHEMIN_SETTINGS", tmp_path / "settings.json")
    monkeypatch.setattr(config, "CHEMIN_DB", tmp_path / "promatelas.db")
    monkeypatch.setattr(config_client, "CHEMIN_CONFIG_CLIENT", tmp_path / "client_config.json")
    monkeypatch.setattr(archive_client, "CHEMIN_ARCHIVE_CLIENT",
                        tmp_path / "factures_archivees_client.json")
    monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "versements_en_attente.json")
    # Le jeton role_client local (ci-dessous) ferait sinon tenter un vrai
    # démarrage de serveur (subprocess réel) à la construction de l'app.
    monkeypatch.setattr(ApiManagementService, "demarrer", lambda self: None)

    # Connexion manuelle déjà enregistrée (IP Tailscale de la machine boss).
    sauvegarder(ConfigClient(hote="100.64.1.2", port=8420, token="jeton-tailscale",
                            machine_id="poste-comptoir"))
    # Un jeton role_client existe aussi localement (ex. onglet Serveur testé
    # une fois par le passé) — ne doit pourtant pas prendre le dessus.
    config.sauver_api_config(token_client="jeton-client-local")

    application = ApplicationClient()
    application.withdraw()
    try:
        application._demarrage()
        assert application.config.hote == "100.64.1.2"
        assert application.config.token == "jeton-tailscale"
        assert type(application.api).__name__ == "ApiClient"
    finally:
        application.destroy()
