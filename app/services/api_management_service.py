"""Gestion du serveur API distant : configuration, démarrage/arrêt d'un
processus **autonome** (indépendant du cycle de vie de l'application
principale — il continue de tourner si celle-ci est fermée), et démarrage
automatique à l'ouverture de session Windows. Voir CLAUDE.md, section
« Accès distant ».

Le démarrage automatique s'appuie sur le **dossier de démarrage Windows**
(`shell:startup`, propre à l'utilisateur) plutôt que sur le Planificateur de
tâches (`schtasks`) : ce dernier exige des droits que beaucoup de comptes
d'entreprise n'ont pas (`Accès refusé` observé même pour une tâche « à
l'ouverture de session » sur un compte de domaine standard), alors que
déposer un script dans le dossier de démarrage est une opération 100 % par
utilisateur, sans élévation.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import requests

from app import config

_NOM_FICHIER_DEMARRAGE = "SMP-API.bat"
_DELAI_PING = 1.5  # secondes — vérification locale, doit être quasi instantanée
# DETACHED_PROCESS : le nouveau processus n'hérite d'aucune console (donc
# aucune fenêtre ne clignote), et CREATE_NEW_PROCESS_GROUP l'isole du groupe
# de la GUI pour qu'il survive à sa fermeture.
_DRAPEAUX_DETACHES = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP


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
        """`SMP-Serveur.exe`, attendu à côté de l'exécutable principal
        une fois packagé. `None` si absent ou si on tourne depuis les sources
        (auquel cas on relance `sys.executable -m app.api.server`)."""
        if not getattr(sys, "frozen", False):
            return None
        candidat = Path(sys.executable).resolve().parent / "SMP-Serveur.exe"
        return candidat if candidat.exists() else None

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
        # DETACHED_PROCESS prive l'enfant de toute console : sans redirection
        # explicite de stdin/stdout/stderr, il plante dès sa première écriture
        # (les journaux uvicorn) faute de handles valides à hériter — d'où la
        # redirection vers un fichier de log plutôt que vers rien.
        if exe is None and getattr(sys, "frozen", False):
            raise ErreurGestionApi(
                "SMP-Serveur.exe introuvable à côté de l'exécutable "
                "principal. Générez-le (voir README) ou copiez-le dans le "
                "même dossier."
            )
        config.preparer_dossiers()
        with open(config.DOSSIER_DATA / "api_serveur.log", "a", encoding="utf-8") as journal:
            if exe is not None:
                subprocess.Popen([str(exe)], creationflags=_DRAPEAUX_DETACHES,
                                 stdin=subprocess.DEVNULL, stdout=journal,
                                 stderr=journal, close_fds=True)
            else:
                racine = Path(__file__).resolve().parent.parent.parent
                subprocess.Popen(
                    [sys.executable, "-m", "app.api.server"], cwd=str(racine),
                    creationflags=_DRAPEAUX_DETACHES,
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
        resultat = subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                  capture_output=True, text=True,
                                  errors="replace")
        if resultat.returncode != 0:
            raise ErreurGestionApi(resultat.stderr.strip() or "Échec de l'arrêt.")
        config.definir_api_active(False)

    @staticmethod
    def _pid_a_l_ecoute(port: int) -> int | None:
        resultat = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                  errors="replace")
        for ligne in resultat.stdout.splitlines():
            colonnes = ligne.split()
            if (len(colonnes) >= 5 and colonnes[0] == "TCP"
                    and colonnes[3] == "LISTENING"
                    and colonnes[1].rsplit(":", 1)[-1] == str(port)):
                return int(colonnes[-1])
        return None

    # Démarrage automatique (dossier de démarrage Windows) ---------------------
    @staticmethod
    def _dossier_demarrage() -> Path:
        return (Path(os.environ["APPDATA"]) / "Microsoft" / "Windows"
                / "Start Menu" / "Programs" / "Startup")

    def _chemin_fichier_demarrage(self) -> Path:
        return self._dossier_demarrage() / _NOM_FICHIER_DEMARRAGE

    def demarrage_auto_actif(self) -> bool:
        return self._chemin_fichier_demarrage().exists()

    def activer_demarrage_auto(self, actif: bool) -> None:
        chemin = self._chemin_fichier_demarrage()
        if not actif:
            chemin.unlink(missing_ok=True)
            return
        exe = self._chemin_executable_serveur()
        if exe is not None:
            contenu = f'@echo off\r\nstart "" "{exe}"\r\n'
        elif getattr(sys, "frozen", False):
            raise ErreurGestionApi(
                "SMP-Serveur.exe introuvable : générez-le avant "
                "d'activer le démarrage automatique.")
        else:
            racine = Path(__file__).resolve().parent.parent.parent
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            interpreteur = pythonw if pythonw.exists() else Path(sys.executable)
            contenu = (f'@echo off\r\ncd /d "{racine}"\r\n'
                      f'start "" "{interpreteur}" -m app.api.server\r\n')
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(contenu, encoding="utf-8")
        except OSError as exc:
            raise ErreurGestionApi(f"Impossible d'écrire dans le dossier de "
                                   f"démarrage Windows : {exc}") from exc
