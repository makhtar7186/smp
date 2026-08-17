"""Gestion du serveur API distant : configuration, démarrage/arrêt d'un
processus **autonome** (indépendant du cycle de vie de l'application
principale — il continue de tourner si celle-ci est fermée), et démarrage
automatique à l'ouverture de session. Voir CLAUDE.md, section « Accès
distant ».

Ce service est utilisé par l'app Facturation (page « API distante ») ET par
l'app Client (onglet « Serveur », pertinent quand ce poste héberge sa propre
base — voir CLAUDE.md, « Client multiplateforme ») : il doit donc fonctionner
aussi bien sur Windows que sur macOS (`_EST_WINDOWS`), avec un mécanisme
différent par OS pour chaque opération système (détachement de processus,
recherche du PID à l'écoute, démarrage automatique).

Le démarrage automatique s'appuie, sous Windows, sur le **dossier de
démarrage** (`shell:startup`, propre à l'utilisateur) plutôt que sur le
Planificateur de tâches (`schtasks`) : ce dernier exige des droits que
beaucoup de comptes d'entreprise n'ont pas (`Accès refusé` observé même pour
une tâche « à l'ouverture de session » sur un compte de domaine standard),
alors que déposer un script dans le dossier de démarrage est une opération
100 % par utilisateur, sans élévation. Sous macOS, l'équivalent utilisateur
sans élévation est un **agent launchd** (`~/Library/LaunchAgents/*.plist`).
"""
from __future__ import annotations

import os
import secrets
import signal
import subprocess
import sys
from pathlib import Path

import requests

from app import config

_EST_WINDOWS = sys.platform.startswith("win")
_NOM_FICHIER_DEMARRAGE = "SMP-API.bat"
_LABEL_LAUNCHD = "com.smp.serveur"
_NOM_FICHIER_DEMARRAGE_MAC = f"{_LABEL_LAUNCHD}.plist"
_DELAI_PING = 1.5  # secondes — vérification locale, doit être quasi instantanée
# DETACHED_PROCESS/CREATE_NEW_PROCESS_GROUP : constantes de subprocess
# propres à Windows (AttributeError sur toute autre plateforme) — le nouveau
# processus n'hérite d'aucune console (donc aucune fenêtre ne clignote), et
# est isolé du groupe de la GUI pour qu'il survive à sa fermeture. Sur
# macOS/Linux, `start_new_session=True` (passé directement à Popen, voir
# `demarrer()`) obtient le même effet de détachement.
_DRAPEAUX_DETACHES = (
    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    if _EST_WINDOWS else 0
)


def _contenu_plist_lancement(programme: list[str], repertoire_travail: str | None) -> str:
    """Agent launchd minimal (`RunAtLoad`) équivalent au `.bat` du dossier de
    démarrage Windows : relance `programme` à chaque ouverture de session."""
    args_xml = "".join(f"    <string>{a}</string>\n" for a in programme)
    travail_xml = (
        f"  <key>WorkingDirectory</key>\n  <string>{repertoire_travail}</string>\n"
        if repertoire_travail else ""
    )
    journal = str(config.DOSSIER_DATA / "api_serveur.log")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key>\n  <string>{_LABEL_LAUNCHD}</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        f'{args_xml}'
        '  </array>\n'
        f'{travail_xml}'
        '  <key>RunAtLoad</key>\n  <true/>\n'
        f'  <key>StandardOutPath</key>\n  <string>{journal}</string>\n'
        f'  <key>StandardErrorPath</key>\n  <string>{journal}</string>\n'
        '</dict>\n'
        '</plist>\n'
    )


class ErreurGestionApi(Exception):
    """Échec d'une opération de gestion du serveur (démarrage, arrêt,
    démarrage automatique) — message déjà en clair, affiché tel quel par l'UI."""


class ApiManagementService:
    """Pilote le serveur `app/api` sans jamais toucher SQLite directement
    (pas de repository ici : ce service orchestre des processus système)."""

    # Configuration ---------------------------------------------------------
    def config(self) -> dict:
        return {
            "host": config.lire_api_host(),
            "port": config.lire_api_port(),
            "token_client": config.lire_api_token("role_client"),
            "token_principal": config.lire_api_token("role_principal"),
            "token_facturation": config.lire_api_token("role_facturation"),
            "token_stock": config.lire_api_token("role_stock"),
        }

    def enregistrer_config(self, host: str, port: int, token_client: str,
                           token_principal: str, token_facturation: str = "",
                           token_stock: str = "") -> None:
        config.sauver_api_config(host=host, port=port, token_client=token_client,
                                 token_principal=token_principal,
                                 token_facturation=token_facturation,
                                 token_stock=token_stock)

    @staticmethod
    def generer_jeton() -> str:
        return secrets.token_urlsafe(32)

    # Statut ------------------------------------------------------------------
    def en_ligne(self) -> bool:
        """Vrai si un serveur répond sur l'hôte/port configurés (peu importe
        qui l'a démarré : GUI, tâche planifiée, ou lancement manuel)."""
        host, port = config.lire_api_host(), config.lire_api_port()
        try:
            return requests.get(f"http://{host}:{port}/health",
                                timeout=_DELAI_PING).ok
        except requests.exceptions.RequestException:
            return False

    # Démarrage / arrêt du processus -------------------------------------------
    def _chemin_executable_serveur(self) -> Path | None:
        """`SMP-Serveur.exe`/`SMP-Serveur.app`, attendu à côté de
        l'exécutable principal une fois packagé. `None` si absent ou si on
        tourne depuis les sources (auquel cas on relance
        `sys.executable -m app.api.server`)."""
        if not getattr(sys, "frozen", False):
            return None
        if _EST_WINDOWS:
            candidat = Path(sys.executable).resolve().parent / "SMP-Serveur.exe"
            return candidat if candidat.exists() else None
        # macOS : sys.executable pointe soit vers le binaire "à plat"
        # (dist/SMP-Client, lancé en ligne de commande) soit vers celui
        # empaqueté dans le bundle (dist/SMP-Client.app/Contents/MacOS/
        # SMP-Client, lancé depuis le Finder) — on remonte les répertoires
        # parents à la recherche de SMP-Serveur sous ces deux formes
        # possibles, plutôt que de supposer une profondeur fixe, jusqu'au
        # dossier "dist" (nom utilisé par build_client_mac.sh/
        # build_serveur_mac.sh) pour ne pas remonter indéfiniment.
        depart = Path(sys.executable).resolve().parent
        for ancetre in (depart, *depart.parents):
            bundle = ancetre / "SMP-Serveur.app" / "Contents" / "MacOS" / "SMP-Serveur"
            if bundle.exists():
                return bundle
            a_plat = ancetre / "SMP-Serveur"
            if a_plat.exists():
                return a_plat
            if ancetre.name == "dist":
                break
        return None

    def demarrer(self) -> None:
        """Lance le serveur dans un processus détaché : il survit à la
        fermeture de l'application principale. Persiste `api_actif=True`
        (`config.definir_api_active`) pour que cette application redémarre
        automatiquement le serveur à son prochain lancement s'il n'est plus
        en ligne (ex. machine redémarrée sans le voir aussi relancer)."""
        config.definir_api_active(True)
        if self.en_ligne():
            return
        exe = self._chemin_executable_serveur()
        nom_attendu = "SMP-Serveur.exe" if _EST_WINDOWS else "SMP-Serveur.app"
        # Détachement : prive l'enfant de toute console (Windows) ou d'une
        # session contrôlante (macOS/Linux) — sans redirection explicite de
        # stdin/stdout/stderr, il plante dès sa première écriture (les
        # journaux uvicorn) faute de handles valides à hériter — d'où la
        # redirection vers un fichier de log plutôt que vers rien.
        if exe is None and getattr(sys, "frozen", False):
            raise ErreurGestionApi(
                f"{nom_attendu} introuvable à côté de l'exécutable "
                "principal. Générez-le (voir README) ou copiez-le dans le "
                "même dossier."
            )
        kwargs_detache = (
            {"creationflags": _DRAPEAUX_DETACHES} if _EST_WINDOWS
            else {"start_new_session": True}
        )
        config.preparer_dossiers()
        with open(config.DOSSIER_DATA / "api_serveur.log", "a", encoding="utf-8") as journal:
            if exe is not None:
                subprocess.Popen([str(exe)], **kwargs_detache,
                                 stdin=subprocess.DEVNULL, stdout=journal,
                                 stderr=journal, close_fds=True)
            else:
                racine = Path(__file__).resolve().parent.parent.parent
                subprocess.Popen(
                    [sys.executable, "-m", "app.api.server"], cwd=str(racine),
                    **kwargs_detache,
                    stdin=subprocess.DEVNULL, stdout=journal, stderr=journal,
                    close_fds=True,
                )

    def arreter(self) -> None:
        """Arrête le processus à l'écoute sur le port configuré, quel qu'il
        soit (GUI, tâche planifiée, lancement manuel). Persiste
        `api_actif=False` : un arrêt explicite ne doit pas être contredit par
        un redémarrage automatique au prochain lancement de l'application."""
        pid = self._pid_a_l_ecoute(config.lire_api_port())
        if pid is None:
            raise ErreurGestionApi("Aucun serveur trouvé sur ce port.")
        if _EST_WINDOWS:
            resultat = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                      capture_output=True, text=True,
                                      errors="replace")
            if resultat.returncode != 0:
                raise ErreurGestionApi(resultat.stderr.strip() or "Échec de l'arrêt.")
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError as exc:
                raise ErreurGestionApi(str(exc)) from exc
        config.definir_api_active(False)

    @staticmethod
    def _pid_a_l_ecoute(port: int) -> int | None:
        if _EST_WINDOWS:
            resultat = subprocess.run(["netstat", "-ano"], capture_output=True,
                                      text=True, errors="replace")
            for ligne in resultat.stdout.splitlines():
                colonnes = ligne.split()
                if (len(colonnes) >= 5 and colonnes[0] == "TCP"
                        and colonnes[3] == "LISTENING"
                        and colonnes[1].rsplit(":", 1)[-1] == str(port)):
                    return int(colonnes[-1])
            return None
        # macOS/Linux : lsof est présent nativement sur macOS (pas toujours
        # sur un Linux minimal, mais ce service n'est utilisé que par les
        # apps Windows/macOS du projet — voir CLAUDE.md).
        resultat = subprocess.run(["lsof", "-ti", f"tcp:{port}"],
                                  capture_output=True, text=True, errors="replace")
        pids = resultat.stdout.split()
        return int(pids[0]) if pids else None

    # Démarrage automatique (dossier de démarrage Windows / agent launchd macOS)
    @staticmethod
    def _dossier_demarrage() -> Path:
        if _EST_WINDOWS:
            return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows"
                    / "Start Menu" / "Programs" / "Startup")
        return Path.home() / "Library" / "LaunchAgents"

    def _chemin_fichier_demarrage(self) -> Path:
        nom = _NOM_FICHIER_DEMARRAGE if _EST_WINDOWS else _NOM_FICHIER_DEMARRAGE_MAC
        return self._dossier_demarrage() / nom

    def demarrage_auto_actif(self) -> bool:
        return self._chemin_fichier_demarrage().exists()

    def activer_demarrage_auto(self, actif: bool) -> None:
        chemin = self._chemin_fichier_demarrage()
        if not actif:
            if not _EST_WINDOWS:
                # Désenregistre l'agent avant de le supprimer, sinon launchd
                # continue de le relancer au prochain login malgré la
                # suppression du fichier.
                subprocess.run(["launchctl", "unload", str(chemin)],
                               capture_output=True)
            chemin.unlink(missing_ok=True)
            return
        exe = self._chemin_executable_serveur()
        nom_attendu = "SMP-Serveur.exe" if _EST_WINDOWS else "SMP-Serveur.app"
        if exe is None and getattr(sys, "frozen", False):
            raise ErreurGestionApi(
                f"{nom_attendu} introuvable : générez-le avant "
                "d'activer le démarrage automatique.")
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            if _EST_WINDOWS:
                if exe is not None:
                    contenu = f'@echo off\r\nstart "" "{exe}"\r\n'
                else:
                    racine = Path(__file__).resolve().parent.parent.parent
                    pythonw = Path(sys.executable).with_name("pythonw.exe")
                    interpreteur = pythonw if pythonw.exists() else Path(sys.executable)
                    contenu = (f'@echo off\r\ncd /d "{racine}"\r\n'
                              f'start "" "{interpreteur}" -m app.api.server\r\n')
                chemin.write_text(contenu, encoding="utf-8")
            else:
                if exe is not None:
                    programme, repertoire_travail = [str(exe)], None
                else:
                    racine = Path(__file__).resolve().parent.parent.parent
                    programme = [sys.executable, "-m", "app.api.server"]
                    repertoire_travail = str(racine)
                chemin.write_text(
                    _contenu_plist_lancement(programme, repertoire_travail),
                    encoding="utf-8",
                )
                subprocess.run(["launchctl", "load", str(chemin)], capture_output=True)
        except OSError as exc:
            raise ErreurGestionApi(f"Impossible d'écrire le lanceur "
                                   f"automatique : {exc}") from exc
