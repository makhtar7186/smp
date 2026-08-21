"""Constantes, chemins et paramètres persistants de l'application."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

# Chemins ---------------------------------------------------------------------
# En exécutable PyInstaller (sys.frozen) : les données (base, exports, réglages)
# vivent à côté du .exe ; les ressources embarquées (logo) dans sys._MEIPASS.
if getattr(sys, "frozen", False):
    _EXECUTABLE: Path = Path(sys.executable).resolve()
    if _EXECUTABLE.parent.name == "MacOS" and _EXECUTABLE.parent.parent.name == "Contents":
        # Bundle .app macOS (SMP-Client.app/Contents/MacOS/SMP-Client) :
        # sys.executable pointe vers le binaire interne, profondément niché
        # dans le bundle — "à côté de l'exécutable" doit donc s'entendre à
        # côté du .app lui-même (son dossier parent), pas dans
        # Contents/MacOS/. Sans ce cas particulier, chaque .app (SMP-Client,
        # SMP-Serveur) avait son PROPRE data/settings.json isolé à
        # l'intérieur de son bundle, alors que sous Windows SMP.exe/
        # SMP-Client.exe et SMP-Serveur.exe partagent le même dossier data/
        # en étant simplement installés côte à côte — un changement de
        # config (ex. IP Tailscale) fait via l'app Client n'atteignait donc
        # jamais le processus SMP-Serveur réellement lancé, qui lisait son
        # propre fichier isolé, jamais modifié.
        RACINE_PROJET: Path = _EXECUTABLE.parents[3]
    else:
        RACINE_PROJET = _EXECUTABLE.parent
    _RESSOURCES: Path = Path(getattr(sys, "_MEIPASS", RACINE_PROJET))
    DOSSIER_DATA: Path = RACINE_PROJET / "data"
else:
    RACINE_PROJET = Path(__file__).resolve().parent.parent
    _RESSOURCES = RACINE_PROJET
    DOSSIER_DATA = RACINE_PROJET / "app" / "data"

DOSSIER_EXPORTS: Path = DOSSIER_DATA / "exports"
CHEMIN_DB: Path = DOSSIER_DATA / "promatelas.db"
CHEMIN_SETTINGS: Path = DOSSIER_DATA / "settings.json"
CHEMIN_LOGO: Path = _RESSOURCES / "logo.png"
# Cache local de la machine de facturation (offline-first) — mêmes
# tables/schéma que la base boss (`promatelas.db`), mais jamais la source de
# vérité. Voir CLAUDE.md, section « Machine de facturation ».
CHEMIN_CACHE_FACTURATION: Path = DOSSIER_DATA / "cache_facturation.db"


def _masquer(chemin: Path) -> None:
    """Cache ce fichier/dossier du Finder (macOS uniquement) — les données
    qu'il contient (base SQLite, jetons API, mot de passe PostgreSQL en
    clair — voir `definir_config_postgres`) n'ont aucune raison d'être
    visibles en parcourant le dossier d'installation de l'app. `chflags
    hidden` plutôt qu'un renommage en `.xxx` : le chemin déjà utilisé
    partout dans le code (`DOSSIER_DATA`, etc.) ne change pas. Reste
    listable via `ls -a`/Terminal.

    **Jamais appliqué sous Windows** : une première version masquait aussi
    via `FILE_ATTRIBUTE_HIDDEN`, mais réécrire un fichier déjà cache de
    cette façon échoue avec `PermissionError`/« Permission denied » côté
    Windows si l'attribut n'est pas explicitement redemandé (ce que l'API
    Python ne fait jamais) — corrigé une première fois en retirant
    l'attribut avant chaque écriture, mais le motif « changer les attributs
    puis réécrire » reste ensuite bloqué par endroits par un antivirus/
    Windows Defender (heuristique proche d'un comportement de rançongiciel),
    observé en usage réel sur un poste client. Retiré entièrement côté
    Windows plutôt que de complexifier davantage un contournement pour un
    gain purement cosmétique.

    Désactivable via la variable d'environnement `SMP_NE_PAS_MASQUER`
    (debug, préférence utilisateur). N'échoue jamais bruyamment (ex. volume
    réseau ne supportant pas cet attribut) : purement cosmétique, jamais une
    condition de fonctionnement de l'app."""
    if sys.platform != "darwin" or os.environ.get("SMP_NE_PAS_MASQUER"):
        return
    try:
        os.chflags(str(chemin), stat.UF_HIDDEN)
    except OSError:
        pass


def _nettoyer_masquage_windows_residuel(chemin: Path) -> None:
    """Retire l'attribut `FILE_ATTRIBUTE_HIDDEN` s'il est encore présent sur
    ce fichier/dossier — résidu laissé par une version antérieure qui
    masquait aussi sous Windows (voir `_masquer`), jamais reposé ensuite.

    Appelée une seule fois, au démarrage (`preparer_dossiers()`), jamais
    couplée à une écriture ultérieure comme l'était `_demasquer()` : le
    blocage observé en usage réel (`PermissionError`, vraisemblablement un
    antivirus/Windows Defender) semblait lié au motif « changer l'attribut
    puis réécrire immédiatement » — séparer les deux dans le temps réduit le
    risque de redéclencher la même heuristique. N'échoue jamais bruyamment :
    auto-corrige silencieusement les installations déjà affectées, sans
    action manuelle requise côté utilisateur."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        attributs = kernel32.GetFileAttributesW(str(chemin))
        if attributs != 0xFFFFFFFF and attributs & 0x2:  # FILE_ATTRIBUTE_HIDDEN
            kernel32.SetFileAttributesW(str(chemin), attributs & ~0x2)
    except OSError:
        pass


def _ecrire_settings(settings: dict) -> None:
    """Point d'écriture unique de `settings.json` — nettoyage résiduel
    d'abord (voir `_nettoyer_masquage_windows_residuel`) : `preparer_dossiers()`
    ne suffit pas seul, toutes les fonctions de sauvegarde n'y passent pas
    forcément avant d'écrire."""
    _nettoyer_masquage_windows_residuel(CHEMIN_SETTINGS)
    CHEMIN_SETTINGS.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _masquer(CHEMIN_SETTINGS)


def _assurer_dossier_data() -> None:
    """Crée `DOSSIER_DATA` au besoin et le cache (voir `_masquer`) — point
    d'entrée unique appelé par toute fonction qui y écrit, pour ne jamais
    laisser un `data/` visible selon que ce soit ce dossier-ci ou tel autre
    réglage qui l'a créé en premier sur une machine donnée."""
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    _masquer(DOSSIER_DATA)

# Métier ----------------------------------------------------------------------
DEVISE: str = "FCFA"
FORMAT_DATE_AFFICHAGE: str = "%d/%m/%Y"   # JJ/MM/AAAA
FORMAT_DATE_ISO: str = "%Y-%m-%d"

ENTREPRISE = {
    "nom": "SOCIÉTÉ DES MATIÈRES PLASTIQUES SUARL",
    "adresse": "DIAMNIADIO, PRÈS DE L'HÔPITAL DES ENFANTS, AVANT LA SORTIE À PÉAGE",
    "telephones": "33 897 72 94 / 77 487 07 09",
    "ninea": "006569034 2A2",
    "rc": "SN-DKR-2017-B-26690",
}

LANGUE_DEFAUT: str = "fr"
LANGUES_DISPONIBLES: tuple[str, ...] = ("fr", "en", "zh")

TVA_TAUX_DEFAUT: float = 18.0  # % TVA, obligatoire et fixe sur toutes les factures

# API distante (lecture seule) -------------------------------------------------
# Par défaut, écoute uniquement en local (127.0.0.1) — l'API n'est PAS exposée
# tant que l'hôte n'a pas été explicitement réglé sur l'IP Tailscale de la
# machine (ex. 100.x.y.z, visible via `tailscale ip -4`), pour ne jamais
# exposer l'API sur une interface réseau publique/locale par erreur. Réglage
# via `api_host` dans settings.json ou la variable PROMATELAS_API_HOST.
API_HOST_DEFAUT: str = "127.0.0.1"
API_PORT_DEFAUT: int = 8420


def lire_api_host() -> str:
    """IP d'écoute du serveur API (idéalement l'IP Tailscale de la machine)."""
    return os.environ.get("PROMATELAS_API_HOST") or _lire_settings().get(
        "api_host", API_HOST_DEFAUT)


def lire_api_port() -> int:
    """Port d'écoute du serveur API."""
    valeur = os.environ.get("PROMATELAS_API_PORT") or _lire_settings().get(
        "api_port", API_PORT_DEFAUT)
    return int(valeur)


ROLES_API: tuple[str, ...] = ("role_client", "role_principal", "role_facturation", "role_stock")
_CLE_ENV_TOKEN = {
    "role_client": "PROMATELAS_API_TOKEN_CLIENT",
    "role_principal": "PROMATELAS_API_TOKEN_PRINCIPAL",
    "role_facturation": "PROMATELAS_API_TOKEN_FACTURATION",
    "role_stock": "PROMATELAS_API_TOKEN_STOCK",
}
_CLE_SETTINGS_TOKEN = {
    "role_client": "api_token_client",
    "role_principal": "api_token_principal",
    "role_facturation": "api_token_facturation",
    "role_stock": "api_token_stock",
}


def lire_api_token(role: str = "role_client") -> str:
    """Jeton statique attendu dans l'en-tête `X-API-Key` pour le rôle donné.

    Priorité : variable d'environnement (`PROMATELAS_API_TOKEN_CLIENT` /
    `PROMATELAS_API_TOKEN_PRINCIPAL`) > settings.json. Vide par défaut (l'API
    refuse alors toute requête pour ce rôle tant qu'un jeton n'a pas été
    configuré) — voir le README pour la procédure de génération.

    Rétrocompatibilité : une base configurée avant l'introduction des rôles
    (un seul `api_token`) est automatiquement migrée vers `api_token_client`
    au premier appel, pour que les postes distants déjà connectés (en lecture
    seule jusque-là) continuent de fonctionner sans reconfiguration.
    """
    _migrer_jeton_unique_vers_role_client()
    cle_env = _CLE_ENV_TOKEN[role]
    cle_settings = _CLE_SETTINGS_TOKEN[role]
    return os.environ.get(cle_env) or _lire_settings().get(cle_settings, "")


def _migrer_jeton_unique_vers_role_client() -> None:
    """Recopie l'ancien `api_token` (V1, un seul jeton) vers `api_token_client`
    s'il existe et qu'aucun jeton de rôle n'a encore été configuré."""
    settings = _lire_settings()
    ancien = settings.get("api_token")
    if ancien and not settings.get("api_token_client"):
        sauver_api_config(token_client=ancien)


def sauver_api_config(host: str | None = None, port: int | None = None,
                      token_client: str | None = None,
                      token_principal: str | None = None,
                      token_facturation: str | None = None,
                      token_stock: str | None = None) -> None:
    """Persiste la configuration du serveur API (hôte, port, jetons par rôle)."""
    _assurer_dossier_data()
    settings = _lire_settings()
    if host is not None:
        settings["api_host"] = host
    if port is not None:
        settings["api_port"] = port
    if token_client is not None:
        settings["api_token_client"] = token_client
    if token_principal is not None:
        settings["api_token_principal"] = token_principal
    if token_facturation is not None:
        settings["api_token_facturation"] = token_facturation
    if token_stock is not None:
        settings["api_token_stock"] = token_stock
    _ecrire_settings(settings)


def api_active() -> bool:
    """Vrai si l'application principale doit démarrer le serveur API en tâche
    de fond à son lancement (réglage `api_actif` de settings.json, faux par
    défaut) — positionné automatiquement par `ApiManagementService.demarrer()`/
    `arreter()` (voir `definir_api_active`), pas par une case à cocher dédiée :
    démarrer le serveur une fois signale l'intention de le garder actif aux
    lancements suivants de cette application."""
    return bool(_lire_settings().get("api_actif", False))


def definir_api_active(actif: bool) -> None:
    """Persiste l'intention de démarrer automatiquement le serveur au
    prochain lancement de cette application — voir `api_active`."""
    _assurer_dossier_data()
    settings = _lire_settings()
    settings["api_actif"] = actif
    _ecrire_settings(settings)


def _lire_settings() -> dict:
    """Lit le fichier de paramètres persistants (créé au besoin)."""
    if CHEMIN_SETTINGS.exists():
        try:
            return json.loads(CHEMIN_SETTINGS.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


MODES_MACHINE: tuple[str, ...] = ("principale", "facturation_distante")
_MODE_MACHINE_DEFAUT = "principale"


def lire_mode_machine() -> str:
    """Rôle de cette installation de `SMP.exe` : « principale »
    (comportement historique, base locale — défaut, aucune installation
    existante n'est affectée par cette clé absente) ou « facturation_distante »
    (voir CLAUDE.md, section « Machine de facturation »)."""
    mode = _lire_settings().get("mode_machine", _MODE_MACHINE_DEFAUT)
    return mode if mode in MODES_MACHINE else _MODE_MACHINE_DEFAUT


def definir_mode_machine(mode: str) -> None:
    """Persiste le mode choisi — un redémarrage manuel de l'application est
    nécessaire pour qu'il prenne effet (voir `app/main.py`)."""
    if mode not in MODES_MACHINE:
        raise ValueError(f"mode_machine invalide : {mode!r}")
    _assurer_dossier_data()
    settings = _lire_settings()
    settings["mode_machine"] = mode
    _ecrire_settings(settings)


MOTEURS_BDD: tuple[str, ...] = ("sqlite", "postgresql")
_MOTEUR_BDD_DEFAUT = "sqlite"


def lire_moteur_bdd() -> str:
    """Moteur de la base « boss » (app principale + serveur API) : « sqlite »
    (défaut, comportement historique inchangé) ou « postgresql » (voir
    CLAUDE.md, section « Bascule PostgreSQL »). Les caches locaux des
    machines de facturation restent TOUJOURS SQLite quelle que soit cette
    valeur — non concernés (`creer_connexion(chemin_db=...)` n'est sensible
    à ce réglage que lorsqu'elle est appelée SANS argument)."""
    moteur = os.environ.get("PROMATELAS_MOTEUR_BDD") or _lire_settings().get(
        "moteur_bdd", _MOTEUR_BDD_DEFAUT)
    return moteur if moteur in MOTEURS_BDD else _MOTEUR_BDD_DEFAUT


def definir_moteur_bdd(moteur: str) -> None:
    """Persiste le moteur choisi — un redémarrage manuel de l'application/du
    serveur API est nécessaire pour qu'il prenne effet (`creer_connexion()`
    n'est appelée qu'une fois, au démarrage)."""
    if moteur not in MOTEURS_BDD:
        raise ValueError(f"moteur_bdd invalide : {moteur!r}")
    _assurer_dossier_data()
    settings = _lire_settings()
    settings["moteur_bdd"] = moteur
    _ecrire_settings(settings)


def lire_config_postgres() -> dict:
    """Coordonnées de connexion PostgreSQL de la base boss — utilisées
    uniquement si `lire_moteur_bdd() == 'postgresql'`."""
    settings = _lire_settings()
    return {
        "hote": settings.get("pg_hote", "localhost"),
        "port": int(settings.get("pg_port", 5432)),
        "base": settings.get("pg_base", "promatelas"),
        "utilisateur": settings.get("pg_utilisateur", "promatelas"),
        "mot_de_passe": settings.get("pg_mot_de_passe", ""),
    }


def definir_config_postgres(hote: str, port: int, base: str, utilisateur: str,
                            mot_de_passe: str) -> None:
    """Persiste les coordonnées de connexion PostgreSQL de la base boss."""
    _assurer_dossier_data()
    settings = _lire_settings()
    settings.update({
        "pg_hote": hote, "pg_port": port, "pg_base": base,
        "pg_utilisateur": utilisateur, "pg_mot_de_passe": mot_de_passe,
    })
    _ecrire_settings(settings)


def lire_langue() -> str:
    """Retourne la langue sauvegardée, ou la langue par défaut."""
    langue = _lire_settings().get("langue", LANGUE_DEFAUT)
    return langue if langue in LANGUES_DISPONIBLES else LANGUE_DEFAUT


def sauver_langue(langue: str) -> None:
    """Persiste la langue choisie par l'utilisateur."""
    _assurer_dossier_data()
    settings = _lire_settings()
    settings["langue"] = langue
    _ecrire_settings(settings)


def preparer_dossiers() -> None:
    """Crée les dossiers de données et d'exports au premier lancement."""
    _assurer_dossier_data()
    DOSSIER_EXPORTS.mkdir(parents=True, exist_ok=True)
    _nettoyer_masquage_windows_residuel(DOSSIER_DATA)
    _nettoyer_masquage_windows_residuel(CHEMIN_SETTINGS)
