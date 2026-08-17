#!/usr/bin/env bash
# Construit le mode client (SMP-Client.app) depuis un Mac.
#
# PyInstaller ne fait pas de cross-compilation : un exécutable Windows ne
# peut être produit que sur Windows, un .app macOS que sur macOS. Ce script
# doit donc être lancé SUR LE MAC où vous voulez utiliser le client, avec une
# copie du projet (clone git, ou dossier copié depuis la machine Windows).
#
# Usage :
#   cd chemin/vers/pro-matela
#   chmod +x build_client_mac.sh   # une seule fois
#   ./build_client_mac.sh
#
# Résultat : dist/SMP-Client.app (bundle macOS standard, double-clic
# depuis le Finder). Aucun droit administrateur requis.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (à ajuster une fois pour toutes)
# ---------------------------------------------------------------------------
APP_NAME="SMP-Client"
BUNDLE_ID="com.smp.client"          # identifiant unique de l'app (reverse-DNS)
APP_VERSION="1.0.0"                 # version affichée dans "À propos" / Finder
ICON_ICNS="assets/icon.icns"        # optionnel : chemin vers une icône .icns

# ---------------------------------------------------------------------------
# Vérifications préalables
# ---------------------------------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Ce script est prévu pour macOS uniquement (détecté : $(uname -s))." >&2
  exit 1
fi

if ! command -v python3 &>/dev/null; then
  echo "python3 introuvable. Installez-le depuis https://www.python.org/downloads/macos/" >&2
  echo "(ou via Homebrew : brew install python)" >&2
  exit 1
fi

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RACINE"

if [[ ! -f "app/main_client.py" ]]; then
  echo "app/main_client.py introuvable depuis $RACINE." >&2
  echo "Lancez ce script depuis la racine du projet." >&2
  exit 1
fi

# Info : architecture native de ce Mac. PyInstaller ne compile PAS de build
# universel par défaut : le résultat ne tournera nativement que sur la même
# architecture que celle de ce Mac (Apple Silicon arm64 OU Intel x86_64).
ARCH="$(uname -m)"
echo "→ Build lancé sur architecture : $ARCH"
if [[ "$ARCH" == "arm64" ]]; then
  echo "  (le .app produit ne sera pas nativement compatible Mac Intel, sauf"
  echo "   Rosetta 2 côté utilisateur, ou build universal2 — voir commentaire"
  echo "   plus bas dans ce script)"
fi

# Nettoyage des builds précédents pour éviter des artefacts obsolètes
# (fichiers de données oubliés, ancienne version embarquée, etc.)
echo "→ Nettoyage build/ et dist/ précédents…"
rm -rf build dist "${APP_NAME}.spec"

# ---------------------------------------------------------------------------
# Environnement virtuel dédié au build
# ---------------------------------------------------------------------------
echo "→ Environnement virtuel dédié au build (venv_client_mac/)…"
python3 -m venv venv_client_mac
source venv_client_mac/bin/activate

echo "→ Installation des dépendances du mode client uniquement…"
# Volontairement PAS requirements.txt complet : le client n'a pas besoin de
# fastapi/uvicorn (serveur, aucune route HTTP n'est servie par ce poste).
# matplotlib est nécessaire depuis l'ajout de l'onglet Dashboard (graphiques
# partagés avec l'application principale, voir
# app/ui/components/graphiques_dashboard.py). reportlab est nécessaire depuis
# AccesDirectDonnees (app/client/acces_direct.py) : quand ce poste héberge sa
# propre base, les PDF sont régénérés en local plutôt que téléchargés.
pip install --quiet --upgrade pip
pip install --quiet requests matplotlib reportlab pyinstaller

# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------
echo "→ Compilation de ${APP_NAME}.app…"

PYINSTALLER_ARGS=(
  --noconfirm --clean --onefile --windowed
  --name "$APP_NAME"
  --osx-bundle-identifier "$BUNDLE_ID"
  # --add-data avec ":" (séparateur macOS/Linux, ";" sous Windows) : le logo
  # est nécessaire depuis AccesDirectDonnees (PDF régénéré en local avec logo
  # quand ce poste héberge sa propre base).
  --add-data "logo.png:."
)

# Icône .icns optionnelle : n'ajoute l'option que si le fichier existe, pour
# ne pas casser le build si vous n'en avez pas encore préparé une.
if [[ -f "$ICON_ICNS" ]]; then
  echo "  Icône trouvée : $ICON_ICNS"
  PYINSTALLER_ARGS+=(--icon "$ICON_ICNS")
else
  echo "  Aucune icône .icns trouvée ($ICON_ICNS) — l'app aura l'icône"
  echo "  générique PyInstaller. Générez-en une avec :"
  echo "    sips -s format icns votre_logo.png --out assets/icon.icns"
  echo "  (ou via iconutil à partir d'un dossier .iconset)"
fi

python -m PyInstaller "${PYINSTALLER_ARGS[@]}" app/main_client.py

# ---------------------------------------------------------------------------
# Version affichée dans le bundle (Info.plist)
# ---------------------------------------------------------------------------
# PyInstaller ne permet pas de fixer CFBundleShortVersionString via une
# option en ligne de commande : on patche le Info.plist généré directement.
INFO_PLIST="dist/${APP_NAME}.app/Contents/Info.plist"
if [[ -f "$INFO_PLIST" ]]; then
  /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $APP_VERSION" "$INFO_PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $APP_VERSION" "$INFO_PLIST"
  echo "→ Version $APP_VERSION inscrite dans Info.plist"
fi

deactivate

# ---------------------------------------------------------------------------
# Quarantaine
# ---------------------------------------------------------------------------
# macOS ajoute l'attribut com.apple.quarantine aux fichiers transférés via
# USB/réseau/téléchargement, ce qui déclenche l'avertissement Gatekeeper.
# On la retire ici pour VOTRE poste de build/test. Si vous transférez ensuite
# le .app à quelqu'un d'autre (clé USB, email, AirDrop…), l'attribut sera
# probablement réappliqué côté destinataire : il devra faire la même chose,
# ou vous distribuez plutôt via un .dmg signé/notarisé (compte développeur
# Apple à 99$/an) pour éviter complètement l'avertissement.
xattr -cr "dist/${APP_NAME}.app" 2>/dev/null || true

echo
echo "✅ Terminé : dist/${APP_NAME}.app"
echo "   Déplacez-le où vous voulez (ex. /Applications) et double-cliquez pour lancer."
echo "   Premier lancement chez un AUTRE utilisateur : clic droit → Ouvrir"
echo "   (macOS bloque par défaut les apps non signées d'un développeur non"
echo "   identifié — normal pour un build local). Ou en ligne de commande :"
echo "     xattr -d com.apple.quarantine /chemin/vers/${APP_NAME}.app"
echo
echo "   Pour un build universel Intel + Apple Silicon, il faut un Python"
echo "   'universal2' (python.org, pas Homebrew) et ajouter :"
echo "     --target-architecture universal2"
echo "   à la commande PyInstaller ci-dessus (nécessite que toutes vos"
echo "   dépendances aient aussi des wheels universal2, pas toujours le cas)."