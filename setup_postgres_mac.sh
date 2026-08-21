#!/usr/bin/env bash
# Provisionne une base PostgreSQL locale sur macOS pour la « bascule
# PostgreSQL » de SMP Gestion (app Facturation/Client, onglet Serveur —
# voir CLAUDE.md, section « Bascule PostgreSQL »).
#
# Installe PostgreSQL via Homebrew s'il est absent (avec confirmation avant
# tout téléchargement/installation), démarre le service, puis crée le rôle
# et la base attendus par l'app. L'app crée elle-même les TABLES à la
# première connexion (`base_repository.creer_connexion` exécute le schéma
# canonique) : ce script ne s'occupe que de faire exister le serveur, le
# rôle et la base — jamais du schéma métier.
#
# Usage :
#   cd chemin/vers/pro-matela
#   chmod +x setup_postgres_mac.sh   # une seule fois
#   ./setup_postgres_mac.sh
#
# Personnalisable via variables d'environnement (valeurs par défaut =
# celles attendues par app/client/config_postgres.py) :
#   DB_NAME=promatelas DB_USER=promatelas DB_PASSWORD=... DB_HOST=localhost \
#   DB_PORT=5432 PG_VERSION=16 ./setup_postgres_mac.sh
#
# Idempotent : peut être relancé sans risque (rôle/base déjà existants =
# simplement signalés, jamais recréés en écrasant les données).

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration (à ajuster une fois pour toutes, ou via variables d'env)
# ---------------------------------------------------------------------------
DB_NAME="${DB_NAME:-promatelas}"
DB_USER="${DB_USER:-promatelas}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
PG_VERSION="${PG_VERSION:-16}"   # formule Homebrew "postgresql@$PG_VERSION"

# ---------------------------------------------------------------------------
# Vérifications préalables
# ---------------------------------------------------------------------------
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Ce script est prévu pour macOS uniquement (détecté : $(uname -s))." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# Homebrew : requis pour installer/piloter PostgreSQL. Jamais installé sans
# confirmation explicite (télécharge et exécute un script d'installation
# système, peut demander le mot de passe de session).
# ---------------------------------------------------------------------------
if ! command -v brew &>/dev/null; then
  echo "Homebrew (gestionnaire de paquets macOS) est introuvable — nécessaire"
  echo "pour installer PostgreSQL automatiquement."
  read -rp "L'installer maintenant (télécharge depuis brew.sh) ? [o/N] " reponse
  if [[ "$reponse" =~ ^[oOyY] ]]; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -x /opt/homebrew/bin/brew ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"     # Mac Apple Silicon
    elif [[ -x /usr/local/bin/brew ]]; then
      eval "$(/usr/local/bin/brew shellenv)"        # Mac Intel
    fi
  else
    echo "Installez PostgreSQL manuellement (Homebrew, ou l'app signée" >&2
    echo "https://postgresapp.com) puis relancez ce script." >&2
    exit 1
  fi
fi

# ---------------------------------------------------------------------------
# PostgreSQL : installation via Homebrew si absent (téléchargement du
# paquet), sinon réutilisation de l'installation déjà présente.
# ---------------------------------------------------------------------------
FORMULE=""
for candidate in "postgresql@${PG_VERSION}" postgresql; do
  if brew list --formula 2>/dev/null | grep -qx "$candidate"; then
    FORMULE="$candidate"
    break
  fi
done

if [[ -z "$FORMULE" ]]; then
  echo "PostgreSQL n'est pas installé sur cette machine."
  read -rp "Le télécharger et l'installer maintenant via Homebrew ? [o/N] " reponse
  if [[ ! "$reponse" =~ ^[oOyY] ]]; then
    echo "Installez PostgreSQL manuellement puis relancez ce script." >&2
    exit 1
  fi
  echo "→ Téléchargement/installation de postgresql@${PG_VERSION}…"
  if brew install "postgresql@${PG_VERSION}"; then
    FORMULE="postgresql@${PG_VERSION}"
  else
    echo "  Formule postgresql@${PG_VERSION} indisponible — repli sur la"
    echo "  dernière version Homebrew (postgresql)…"
    brew install postgresql
    FORMULE="postgresql"
  fi
fi

# Formules versionnées ("postgresql@16") : Homebrew ne les ajoute pas au
# PATH par défaut (keg-only, pour ne pas entrer en conflit avec une autre
# version) — nécessaire pour que psql/pg_isready appelés plus bas résolvent
# vers cette installation.
export PATH="$(brew --prefix "$FORMULE")/bin:$PATH"

# ---------------------------------------------------------------------------
# Démarrage du service (idempotent : ne fait rien s'il tourne déjà), lancé
# en tâche de fond et relancé automatiquement à la connexion — cohérent
# avec un serveur censé tourner en continu.
# ---------------------------------------------------------------------------
echo "→ Démarrage du service PostgreSQL (${FORMULE})…"
brew services start "$FORMULE" >/dev/null

echo -n "→ Attente que le serveur réponde"
PRET=0
for _ in $(seq 1 30); do
  if pg_isready -h "$DB_HOST" -p "$DB_PORT" &>/dev/null; then
    PRET=1
    break
  fi
  echo -n "."
  sleep 1
done
echo
if [[ "$PRET" -ne 1 ]]; then
  echo "PostgreSQL ne répond toujours pas sur ${DB_HOST}:${DB_PORT} après 30s." >&2
  echo "Vérifiez 'brew services list' et les journaux ($(brew --prefix)/var/log/)." >&2
  exit 1
fi
echo "  Serveur prêt."

# ---------------------------------------------------------------------------
# Rôle applicatif + base — jamais le rôle superutilisateur créé par défaut
# par Homebrew (celui-ci porte le nom de l'utilisateur macOS courant,
# utilisé ci-dessous uniquement pour exécuter les commandes d'administration).
# ---------------------------------------------------------------------------
SUPERUSER="$(whoami)"

if [[ -z "${DB_PASSWORD:-}" ]]; then
  DB_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=\n' | cut -c1-24)"
fi

if psql -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres -tAc \
    "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1; then
  echo "→ Rôle \"${DB_USER}\" déjà existant — mise à jour du mot de passe."
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres -c \
    "ALTER ROLE \"${DB_USER}\" WITH LOGIN PASSWORD '${DB_PASSWORD}';" >/dev/null
else
  echo "→ Création du rôle \"${DB_USER}\"…"
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres -c \
    "CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASSWORD}';" >/dev/null
fi

if psql -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  echo "→ Base \"${DB_NAME}\" déjà existante — laissée telle quelle."
else
  echo "→ Création de la base \"${DB_NAME}\" (propriétaire : ${DB_USER})…"
  psql -h "$DB_HOST" -p "$DB_PORT" -U "$SUPERUSER" -d postgres -c \
    "CREATE DATABASE \"${DB_NAME}\" OWNER \"${DB_USER}\";" >/dev/null
fi

echo
echo "✅ PostgreSQL prêt."
echo "   Renseignez ces informations dans l'app (onglet Serveur → PostgreSQL) :"
echo "     Hôte         : ${DB_HOST}"
echo "     Port         : ${DB_PORT}"
echo "     Base         : ${DB_NAME}"
echo "     Utilisateur  : ${DB_USER}"
echo "     Mot de passe : ${DB_PASSWORD}"
echo
echo "   Les tables sont créées automatiquement par l'app à la première"
echo "   connexion (aucune action SQL supplémentaire nécessaire ici)."
echo
echo "   Note sécurité : l'installation Homebrew par défaut autorise les"
echo "   connexions locales (127.0.0.1) sans vérifier le mot de passe"
echo "   (authentification \"trust\" dans pg_hba.conf) — acceptable pour un"
echo "   usage strictement local à cette machine (voir CLAUDE.md : l'accès"
echo "   distant passe toujours par l'API, jamais par une connexion"
echo "   PostgreSQL directe). Pour durcir ça, localisez pg_hba.conf avec :"
echo "     psql -h ${DB_HOST} -p ${DB_PORT} -U ${SUPERUSER} -d postgres -tAc \"SHOW hba_file\""
echo "   remplacez-y \"trust\" par \"scram-sha-256\", puis :"
echo "     brew services restart ${FORMULE}"
