# Déploiement du serveur API en service Windows (NSSM)

Ce document couvre l'installation de `SMP-Serveur.exe` comme service
Windows natif via [NSSM](https://nssm.cc) (Non-Sucking Service Manager), en
alternative au démarrage automatique déjà géré par `ApiManagementService`
(dossier de démarrage utilisateur — voir CLAUDE.md, section « Accès
distant »).

## Pourquoi NSSM plutôt que le dossier de démarrage existant ?

Le mécanisme déjà en place (`ApiManagementService.activer_demarrage_auto`,
page « API distante ») dépose un `.bat` dans le dossier de démarrage de
l'utilisateur — simple, sans élévation, mais avec deux limites :

- il ne démarre qu'**après l'ouverture d'une session utilisateur** (pas au
  boot de la machine, ex. si personne ne se connecte après un redémarrage) ;
- il n'a pas de politique de redémarrage automatique si le process crashe.

Un service Windows NSSM démarre **avant toute connexion utilisateur** (mode
`Automatic`, pas `Automatic (Delayed Start)`, pour minimiser le délai) et
peut être configuré pour se relancer seul en cas de crash. Pertinent pour une
machine dédiée à héberger l'API en continu (ex. un boîtier sans écran, ou une
machine où personne ne se connecte systématiquement).

Les deux mécanismes sont mutuellement exclusifs pour éviter deux process
écoutant sur le même port : si vous adoptez le service NSSM, désactivez le
démarrage automatique existant (page « API distante », décochez la case, ou
appelez `ApiManagementService.desactiver_demarrage_auto()`).

## Prérequis

1. **NSSM** : téléchargez `nssm.exe` depuis <https://nssm.cc/download>
   (binaire tiers, non fourni dans ce dépôt). Prenez la version 64-bit
   correspondant à Windows. Placez `nssm.exe` où vous voulez (ex.
   `C:\outils\nssm\nssm.exe`) — les scripts ci-dessous acceptent son chemin
   en paramètre, ou le cherchent dans le `PATH`.
2. **`SMP-Serveur.exe`** généré (voir CLAUDE.md, section
   « Commandes ») :
   ```powershell
   python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SMP-Serveur" --icon "app/icone.ico" --add-data "logo.png;." app/main_server.py
   ```
3. PowerShell lancé **en tant qu'administrateur** (création d'un service
   Windows).

## Chemins utilisés (référence)

| Élément | Chemin par défaut | Notes |
|---|---|---|
| Exécutable du service | `dist\SMP-Serveur.exe` (dépôt) ou l'emplacement de déploiement final, ex. `C:\SMP\SMP-Serveur.exe` | C'est l'exécutable PyInstaller déjà buildé — **pas** un script Python + venv (le service exécute directement le binaire, comme `ApiManagementService` le fait déjà pour le lancement manuel). |
| Répertoire de travail | Le même dossier que l'exécutable | `config.py` crée `data\` **à côté de l'exe** (`sys.frozen` → `Path(sys.executable).resolve().parent`) — le service doit tourner avec ce dossier comme `AppDirectory` pour retrouver/créer `data\promatelas.db`, `data\settings.json`. |
| Log applicatif (uvicorn) | `data\api_serveur.log` | Déjà écrit par le process lui-même (voir `ApiManagementService.demarrer`, redirection stdin/stdout/stderr) — inchangé, que le process soit lancé par NSSM ou manuellement. |
| Logs NSSM (wrapper) | `data\nssm_stdout.log` / `data\nssm_stderr.log` | Capturent ce qui échapperait au log applicatif (ex. crash avant même l'ouverture du log uvicorn). Rotation activée (1 Mo). |
| **Alternative** : lancement depuis les sources (sans build) | `venv\Scripts\python.exe -m app.api.server`, `AppDirectory` = racine du dépôt | Utile en dev/débogage uniquement — voir CLAUDE.md : `SMP-Serveur.exe` reste le mode de déploiement recommandé (pas de dépendance à un venv sur la machine cible). Pour l'utiliser avec NSSM : `CheminExe` = chemin complet vers `python.exe` du venv, et ajoutez les arguments `-m app.api.server` via `nssm set ProMatelasAPI AppParameters "-m app.api.server"`. |

## Installation

```powershell
cd scripts\nssm
.\installer_service_api.ps1 -CheminExe "C:\SMP\SMP-Serveur.exe" -CheminNssm "C:\outils\nssm\nssm.exe" -DemarrerImmediatement
```

Sans `-DemarrerImmediatement`, le service est installé et configuré mais
reste arrêté (démarrage manuel via `Start-Service ProMatelasAPI`, ou au
prochain redémarrage de la machine).

Le script configure :
- démarrage `Automatic` (pas Delayed) ;
- redémarrage automatique sur tout code de sortie non nul, avec un délai de
  5 secondes (`AppRestartDelay`) pour éviter une boucle de crash immédiate ;
- rotation des logs NSSM au-delà de 1 Mo.

## Vérification

```powershell
Get-Service ProMatelasAPI | Format-List Name, Status, StartType
Invoke-WebRequest http://127.0.0.1:<port>/health   # port configuré (settings.json / PROMATELAS_API_PORT)
```

`/health` ne nécessite pas d'authentification (voir CLAUDE.md, section
« Accès distant ») — un `200 OK` confirme que le service tourne et répond.
Consultez `services.msc` pour une vue graphique, ou `data\api_serveur.log` /
`data\nssm_stdout.log` en cas de doute sur le démarrage.

## Désinstallation

```powershell
cd scripts\nssm
.\desinstaller_service_api.ps1 -CheminNssm "C:\outils\nssm\nssm.exe"
```

N'affecte que le service Windows — l'exécutable et le dossier `data\` (base,
réglages, logs) sont conservés intacts.

## Redémarrage / reconfiguration

Relancer `installer_service_api.ps1` sur un service déjà existant le
reconfigure en place (arrêt, mise à jour des paramètres NSSM) sans le
recréer — pratique après un changement de chemin ou une mise à jour de
l'exécutable (remplacez le `.exe` puis relancez le script, ou simplement
`Restart-Service ProMatelasAPI` si seul le binaire a changé).
