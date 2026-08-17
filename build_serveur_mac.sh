#!/usr/bin/env bash
# Construit le serveur API autonome (SMP-Serveur.app) depuis un Mac.
#
# PyInstaller ne fait pas de cross-compilation : un exécutable Windows ne
# peut être produit que sur Windows, un .app macOS que sur macOS. Ce script
# doit donc être lancé SUR LE MAC où vous voulez héberger le serveur, avec
# une copie du projet (clone git, ou dossier copié depuis la machine
# Windows).
#
# Usage :
#   cd chemin/vers/pro-matela
#   chmod +x build_serveur_mac.sh   # une seule fois
#   ./build_serveur_mac.sh
#
# Résultat : dist/SMP-Serveur.app (bundle macOS standard, double-clic
# depuis le Finder — ou lancement en tâche de fond, voir plus bas).
# Aucun droit administrateur requis.

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (à ajuster une fois pour toutes)
# ---------------------------------------------------------------------------
APP_NAME="SMP-Serveur"
BUNDLE_ID="com.smp.serveur"         # identifiant unique de l'app (reverse-DNS)
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

if [[ ! -f "app/main_server.py" ]]; then
  echo "app/main_server.py introuvable depuis $RACINE." >&2
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
echo "→ Environnement virtuel dédié au build (venv_serveur_mac/)…"
python3 -m venv venv_serveur_mac
source venv_serveur_mac/bin/activate

echo "→ Installation des dépendances du serveur uniquement…"
# Volontairement PAS requirements.txt complet : le serveur n'a pas besoin de
# matplotlib/tkcalendar/openpyxl (aucune fenêtre Tkinter, aucun export Excel
# côté serveur — ces fonctionnalités vivent dans l'app Facturation/Client).
# reportlab est nécessaire : les endpoints /factures/{id}/pdf et bordereau
# (app/api/routes.py) régénèrent le PDF via app/services/pdf_service.py.
# psycopg2-binary est nécessaire pour la bascule PostgreSQL (base boss sur
# Postgres plutôt que SQLite) — import toujours paresseux dans le code, donc
# à installer explicitement avant le build pour que PyInstaller l'embarque
# (voir CLAUDE.md, section Commandes).
pip install --quiet --upgrade pip
pip install --quiet fastapi uvicorn pydantic python-multipart requests httpx reportlab psycopg2-binary pyinstaller

# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------
echo "→ Compilation de ${APP_NAME}.app…"

PYINSTALLER_ARGS=(
  --noconfirm --clean --onefile --windowed
  --name "$APP_NAME"
  --osx-bundle-identifier "$BUNDLE_ID"
  --hidden-import psycopg2
  # --add-data avec ":" (séparateur macOS/Linux, ";" sous Windows) : le logo
  # est nécessaire pour la génération des PDF (facture/bordereau) servis par
  # ce processus (app/services/pdf_service.py).
  --add-data "logo.png:."
)

# Icône .icns : générée automatiquement depuis logo.png si elle n'existe pas
# encore (sips/iconutil, outils macOS natifs). logo.png n'étant pas carré,
# sips le recadre — si le résultat ne vous convient pas visuellement,
# remplacez assets/icon.icns par une version travaillée manuellement puis
# relancez ce script (il ne régénère jamais un .icns déjà présent).
if [[ ! -f "$ICON_ICNS" ]] && [[ -f "logo.png" ]] && command -v sips &>/dev/null && command -v iconutil &>/dev/null; then
  echo "  Génération de $ICON_ICNS depuis logo.png…"
  mkdir -p "$(dirname "$ICON_ICNS")"
  ICONSET="$(dirname "$ICON_ICNS")/icon.iconset"
  rm -rf "$ICONSET"
  mkdir -p "$ICONSET"
  for taille in 16 32 128 256 512; do
    sips -z "$taille" "$taille" logo.png --out "$ICONSET/icon_${taille}x${taille}.png" &>/dev/null
    double=$((taille * 2))
    sips -z "$double" "$double" logo.png --out "$ICONSET/icon_${taille}x${taille}@2x.png" &>/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$ICON_ICNS"
  rm -rf "$ICONSET"
fi

# N'ajoute l'option --icon que si le fichier existe, pour ne pas casser le
# build si la génération ci-dessus n'a pas pu avoir lieu (logo.png absent,
# sips/iconutil indisponibles).
if [[ -f "$ICON_ICNS" ]]; then
  echo "  Icône trouvée : $ICON_ICNS"
  PYINSTALLER_ARGS+=(--icon "$ICON_ICNS")
else
  echo "  Aucune icône .icns trouvée ($ICON_ICNS) — l'app aura l'icône"
  echo "  générique PyInstaller."
fi

python -m PyInstaller "${PYINSTALLER_ARGS[@]}" app/main_server.py

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
echo "   Ce processus n'a AUCUNE fenêtre visible une fois lancé (--windowed,"
echo "   sans interface) : double-clic depuis le Finder le démarre en tâche"
echo "   de fond — vérifiez qu'il tourne via l'endpoint /health, ou les"
echo "   journaux dist/SMP-Serveur.app/../data/api_serveur.log (stdout/stderr"
echo "   redirigés en l'absence de console, voir app/main_server.py)."
echo "   Premier lancement chez un AUTRE utilisateur : clic droit → Ouvrir"
echo "   (macOS bloque par défaut les apps non signées d'un développeur non"
echo "   identifié — normal pour un build local). Ou en ligne de commande :"
echo "     xattr -d com.apple.quarantine /chemin/vers/${APP_NAME}.app"
echo
echo "   Pour lancer ce serveur automatiquement à la connexion (macOS),"
echo "   ajoutez-le dans Réglages Système → Général → Ouverture → Ouvrir à"
echo "   la connexion, plutôt que le dossier de démarrage Windows utilisé"
echo "   par ApiManagementService côté PC (voir CLAUDE.md)."
echo
echo "   Pour un build universel Intel + Apple Silicon, il faut un Python"
echo "   'universal2' (python.org, pas Homebrew) et ajouter :"
echo "     --target-architecture universal2"
echo "   à la commande PyInstaller ci-dessus (nécessite que toutes vos"
echo "   dépendances aient aussi des wheels universal2, pas toujours le cas)."
