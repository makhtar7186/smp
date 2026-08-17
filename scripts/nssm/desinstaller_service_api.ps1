<#
.SYNOPSIS
    Arrete et desinstalle le service Windows ProMatelasAPI (NSSM).

.DESCRIPTION
    Voir docs/DEPLOIEMENT_SERVICE_WINDOWS.md. N'affecte que le service
    Windows lui-meme - ne supprime ni l'executable ni le dossier data\
    (base SQLite, settings.json, logs).

.PARAMETER CheminNssm
    Chemin vers nssm.exe. Par defaut : recherche dans le PATH.

.PARAMETER NomService
    Nom du service Windows. Par defaut : ProMatelasAPI.

.EXAMPLE
    .\desinstaller_service_api.ps1 -CheminNssm "C:\nssm\nssm.exe"
#>
[CmdletBinding()]
param(
    [string]$CheminNssm = "nssm.exe",
    [string]$NomService = "ProMatelasAPI"
)

$ErrorActionPreference = "Stop"

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)) {
    Write-Error "Ce script doit etre execute dans un PowerShell lance en tant qu'administrateur."
    exit 1
}

$service = Get-Service -Name $NomService -ErrorAction SilentlyContinue
if (-not $service) {
    Write-Host "Le service '$NomService' n'existe pas - rien a faire."
    exit 0
}

$nssmResolu = Get-Command $CheminNssm -ErrorAction SilentlyContinue
if (-not $nssmResolu) {
    Write-Error "nssm.exe introuvable ('$CheminNssm'). Passez son chemin via -CheminNssm."
    exit 1
}
$CheminNssm = $nssmResolu.Source

if ($service.Status -eq "Running") {
    Write-Host "Arret du service '$NomService'..."
    & $CheminNssm stop $NomService | Out-Null
}

Write-Host "Suppression du service '$NomService'..."
& $CheminNssm remove $NomService confirm

Write-Host "Service '$NomService' desinstalle (l'executable et data\ sont conserves)."
