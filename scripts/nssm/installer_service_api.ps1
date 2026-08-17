<#
.SYNOPSIS
    Installe SMP-Serveur.exe comme service Windows natif via NSSM.

.DESCRIPTION
    Voir docs/DEPLOIEMENT_SERVICE_WINDOWS.md pour le contexte complet
    (pourquoi NSSM plutot que le dossier de demarrage deja gere par
    ApiManagementService, chemins exacts, verification, desinstallation).

    Necessite d'avoir deja telecharge nssm.exe (https://nssm.cc/download,
    non fourni ici - binaire tiers) et genere SMP-Serveur.exe
    (voir CLAUDE.md, section "Commandes").

    Ce script ne fait qu'installer/configurer le service ; il ne le demarre
    qu'a la toute fin, apres confirmation explicite (-DemarrerImmediatement).

.PARAMETER CheminExe
    Chemin vers SMP-Serveur.exe. Par defaut : dist\SMP-Serveur.exe
    a la racine du depot. Sur la machine boss reelle, ce sera plutot le
    dossier de deploiement final (ex. C:\SMP\SMP-Serveur.exe).

.PARAMETER CheminNssm
    Chemin vers nssm.exe. Par defaut : recherche dans le PATH.

.PARAMETER NomService
    Nom du service Windows. Par defaut : ProMatelasAPI (voir CLAUDE.md).

.PARAMETER DemarrerImmediatement
    Si present, demarre le service tout de suite apres l'installation.
    Sinon, le service est installe mais reste arrete (demarrage manuel via
    Start-Service ProMatelasAPI, ou au prochain redemarrage de la machine).

.EXAMPLE
    .\installer_service_api.ps1 -CheminExe "C:\SMP\SMP-Serveur.exe" -CheminNssm "C:\nssm\nssm.exe" -DemarrerImmediatement
#>
[CmdletBinding()]
param(
    [string]$CheminExe = (Join-Path $PSScriptRoot "..\..\dist\SMP-Serveur.exe"),
    [string]$CheminNssm = "nssm.exe",
    [string]$NomService = "ProMatelasAPI",
    [switch]$DemarrerImmediatement
)

$ErrorActionPreference = "Stop"

# --- Verifications prealables ------------------------------------------------
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Write-Error "Ce script doit etre execute dans un PowerShell lance en tant qu'administrateur (creation d'un service Windows)."
    exit 1
}

$CheminExe = (Resolve-Path -ErrorAction SilentlyContinue $CheminExe)
if (-not $CheminExe -or -not (Test-Path $CheminExe)) {
    Write-Error "Executable introuvable. Verifiez -CheminExe (generez d'abord SMP-Serveur.exe - voir CLAUDE.md, section Commandes)."
    exit 1
}

$nssmResolu = Get-Command $CheminNssm -ErrorAction SilentlyContinue
if (-not $nssmResolu) {
    Write-Error "nssm.exe introuvable ('$CheminNssm'). Telechargez-le depuis https://nssm.cc/download et passez son chemin via -CheminNssm."
    exit 1
}
$CheminNssm = $nssmResolu.Source

$DossierTravail = Split-Path $CheminExe -Parent
$DossierLogs = Join-Path $DossierTravail "data"
New-Item -ItemType Directory -Force -Path $DossierLogs | Out-Null

Write-Host "Executable   : $CheminExe"
Write-Host "Repertoire   : $DossierTravail"
Write-Host "Logs NSSM    : $DossierLogs"
Write-Host "Service      : $NomService"
Write-Host ""

# --- Installation / reconfiguration ------------------------------------------
$serviceExistant = Get-Service -Name $NomService -ErrorAction SilentlyContinue
if ($serviceExistant) {
    Write-Host "Le service '$NomService' existe deja - reconfiguration en place."
    if ($serviceExistant.Status -eq "Running") {
        & $CheminNssm stop $NomService | Out-Null
    }
} else {
    & $CheminNssm install $NomService $CheminExe
}

& $CheminNssm set $NomService AppDirectory $DossierTravail
& $CheminNssm set $NomService DisplayName "SMP API"
& $CheminNssm set $NomService Description "Serveur API distant SMP (FastAPI/uvicorn) - acces factures/paiements pour les postes distants. Voir CLAUDE.md."

# Demarrage "Automatic" (pas "Automatic (Delayed Start)") : minimise le delai
# avant que l'API soit joignable au demarrage de la machine.
& $CheminNssm set $NomService Start SERVICE_AUTO_START

# Redemarrage automatique en cas de crash (tout code de sortie non nul) -
# NSSM attend AppRestartDelay avant de relancer, pour eviter une boucle
# de crash immediate si le binaire est casse.
& $CheminNssm set $NomService AppExit Default Restart
& $CheminNssm set $NomService AppRestartDelay 5000
& $CheminNssm set $NomService AppThrottle 1500

# stdout/stderr du process wrappe par NSSM (distinct de data\api_serveur.log,
# deja ecrit par le process lui-meme - voir ApiManagementService dans
# CLAUDE.md) : utile si le process plante avant meme d'ouvrir son propre log.
& $CheminNssm set $NomService AppStdout (Join-Path $DossierLogs "nssm_stdout.log")
& $CheminNssm set $NomService AppStderr (Join-Path $DossierLogs "nssm_stderr.log")
& $CheminNssm set $NomService AppRotateFiles 1
& $CheminNssm set $NomService AppRotateBytes 1048576

Write-Host ""
Write-Host "Service '$NomService' installe/configure avec succes."

if ($DemarrerImmediatement) {
    Write-Host "Demarrage du service..."
    & $CheminNssm start $NomService
    Start-Sleep -Seconds 2
    Get-Service -Name $NomService | Format-List Name, Status, StartType
    Write-Host "Verifiez ensuite : Invoke-WebRequest http://127.0.0.1:<port>/health"
} else {
    Write-Host "Le service n'a PAS ete demarre (utilisez -DemarrerImmediatement, ou 'Start-Service $NomService')."
}
