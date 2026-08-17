# SMP Gestion

Application desktop (Python / Tkinter) de facturation, suivi des ventes et gestion de stock pour la **SOCIÉTÉ DES MATIÈRES PLASTIQUES SUARL** (Diamniadio, Sénégal).

Le système se compose de **3 applications** qui communiquent via un serveur central (SQLite + FastAPI) :

- **App Facturation** (`SMP.exe`) : facturation, produits, clients, historique, archive, remises, dashboards. L'application complète du gérant.
- **App Client / Serveur** (`SMP-Client.exe`) : consultation à distance, paiements, vue client, dashboard, remises — et peut elle-même héberger le serveur.
- **App Stock** (`SMP-Stock.exe`) : rôle unique — visibilité du catalogue et de la quantité en stock de chaque article, saisie des entrées et ajustements.

(Un 4ᵉ exécutable, `SMP-Serveur.exe`, héberge le serveur API seul, sans interface.)

## Fonctionnalités

- **Facturation** : panier de lignes produits, totaux automatiques (FCFA), **TVA à 18 % obligatoire sur toute facture** (fixe, non modifiable), numéro auto-incrémenté mais modifiable, export **PDF** avec logo. Enregistrer/imprimer ne vide pas le panier — seul le bouton « Nouvelle facture » vide le panier et passe au numéro suivant.
- **Brouillons (proforma)** : un panier peut être enregistré comme brouillon, **sans numéro de facture**, pour reprise ultérieure — page « Proforma » dédiée pour le modifier, le **valider** (il devient alors une vraie facture numérotée) ou le supprimer.
- **Bordereau de livraison PDF** à la demande (mêmes lignes, sans prix).
- **Historique des ventes** : filtrable par période et client, détail des lignes, réimpression, export Excel.
- Chaque document généré (PDF ou Excel) **s'ouvre automatiquement** dans l'application par défaut ; une copie reste dans `app/data/exports/`.
- **Référentiels** :
  - **Produits** : catalogue à plat — chaque article est identifié par un **nom**, une **option** (dimension ou litrage) et sa **valeur** (ex. « BIDON » / litrage / « 5L »), chaque combinaison ayant son propre prix. La création d'un nouvel article se fait exclusivement depuis l'**app Stock** ; l'app Facturation refuse d'ajouter au panier une désignation qui ne correspond à aucun produit du catalogue.
  - **Clients** : nom, adresse, téléphone — le téléphone et l'adresse sont les éléments essentiels d'identification (un même téléphone n'appartient jamais qu'à un seul client). Seuls le nom et l'adresse figurent sur une facture. Pas de notion de sous-client/revendeur ; seule la fusion de fiches doublons est proposée.
- **Gestion de stock** : quantité en stock de chaque article, décrémentée automatiquement à chaque facture (dans la même transaction, y compris hors ligne), gérée (entrées, ajustements, historique) depuis l'**app Stock** dédiée — jamais depuis l'app Facturation.
- **Remises annuelles** : CA annuel par client + calcul de la remise de fin d'année (taux %). Une **remise par facture**, distincte, peut aussi être appliquée à une vente précise.
- **Dashboards** : KPI (CA jour/mois/année, factures, panier moyen, comparaison période précédente), top 10 produits, évolution du CA (jour/semaine/mois), répartition par article.
- **Interface trilingue** : français / anglais / 中文 (app Facturation), français / 中文 (app Client et app Stock).
- **Accès distant** : d'autres postes (reliés via Tailscale) peuvent consulter et imprimer l'historique des factures ; le mode client peut en plus **enregistrer des paiements (versements)**, appliquer des remises, et consulter le **Dashboard**/les **Remises annuelles** à distance — voir [Accès distant](#accès-distant) plus bas.
- **Paiements (versements)** : suivi du solde de chaque facture (total/versé/restant), saisi depuis le poste client, consultable en lecture seule depuis l'app Facturation (page « Paiements » + « Vue client »).
- **Machine de facturation (offline-first)** : un poste dédié à la facturation peut fonctionner **hors ligne** (créer une facture, l'imprimer, la modifier, gérer produits/clients) grâce à un cache SQLite local et une file de synchronisation ; la base de données et le serveur API vivent alors sur la machine du boss (allumée en continu) — voir [Machine de facturation](#machine-de-facturation-mode-offline-first) plus bas.

## Installation

Prérequis : **Python ≥ 3.10** (Windows ; Tkinter et SQLite inclus dans Python).

```powershell
python -m pip install -r requirements.txt
```

## Lancement

Depuis la racine du projet :

```powershell
python -m app.main
```

Au premier lancement, la base `app/data/promatelas.db` est créée automatiquement.

Les PDF sont exportés dans `app/data/exports/`.

## Exécutable Windows

Un exécutable autonome (aucune installation de Python requise sur le poste) peut être généré :

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SMP" --icon "app/icone.ico" --add-data "logo.png;." app/main.py
```

Le fichier `dist\SMP.exe` est autonome : copiez-le où vous voulez (Bureau, clé USB, autre PC Windows). Au premier lancement il crée un dossier `data\` **à côté de lui** (base `promatelas.db`, exports PDF/Excel dans `data\exports\`).

⚠️ La base de données vit à côté du .exe : pour sauvegarder, copiez le dossier `data\` ; pour déplacer l'application, déplacez le .exe **avec** son dossier `data\`.

## Accès distant

D'autres postes (reliés à la machine principale via **Tailscale**, un VPN privé) peuvent consulter et imprimer l'historique des factures, enregistrer des **paiements** (versements), appliquer des **remises**, et — depuis un poste dédié — gérer le **stock**. Tout reste local — aucun serveur externe, aucune migration de base de données. Les permissions sont **par ressource**, via quatre jetons distincts.

| Ressource | `role_client` | `role_principal` | `role_facturation` | `role_stock` |
|---|---|---|---|---|
| Factures (lecture, PDF, bordereau) | ✅ | ✅ | ❌ | ❌ |
| Recherche clients (nom/adresse/téléphone) | ✅ (lecture) | ✅ (lecture) | ❌ | ❌ |
| Versements — écriture | ✅ | ❌ (403) | ❌ | ❌ |
| Versements — lecture/solde/historique | ✅ | ✅ | ❌ | ❌ |
| Remise par facture — écriture | ❌ (403) | ✅ | ❌ | ❌ |
| Remise annuelle — écriture | ✅ | ✅ | ❌ | ❌ |
| Totaux/synthèse paiements | ✅ | ✅ | ❌ | ❌ |
| Réservation de numéros / rejeu d'opérations / référentiels / historique complet / archive | ❌ | ❌ | ✅ | ❌ |
| Catalogue + stock (lecture), entrées/ajustements (écriture) | ❌ | ❌ | ❌ | ✅ |

Le rôle « facturation » (voir [Machine de facturation](#machine-de-facturation-mode-offline-first)) et le rôle « stock » (voir [App Stock](#app-stock)) sont chacun indépendants des deux autres — accès strictement limité à leur propre périmètre.

Le mode client utilise le jeton « rôle client » (lecture + écriture des versements et de la remise **annuelle**). La remise **par facture** reste réservée à l'application Facturation. Le rôle « principal » sert pour une consultation en lecture seule des paiements depuis un autre poste, sans jamais pouvoir enregistrer de versement.

L'interface du mode client est disponible en **français et 中文** — la langue choisie est propre à ce poste (`client_config.json`), indépendante de celle de l'app Facturation.

**Onglet « Serveur » du mode client** : `SMP-Client.exe` peut aussi **piloter lui-même `SMP-Serveur.exe`** (configuration hôte/port, génération des 4 jetons, démarrage/arrêt, démarrage automatique) via son onglet « Serveur ». Pratique si le poste qui héberge la base est déjà celui où vous utilisez le client pour les paiements : vous n'avez alors besoin que de `SMP-Client.exe` + `SMP-Serveur.exe` (dans le même dossier), sans jamais installer `SMP.exe`. Dans ce cas, **aucune connexion manuelle n'est nécessaire** : dès qu'un jeton « rôle client » est enregistré dans l'onglet Serveur, le client se connecte automatiquement à lui-même (`127.0.0.1`).

**Chaque application gère son propre archivage des factures.** Archiver une facture depuis la page « Archive » de l'app Facturation ne la masque **pas** au poste distant — celui-ci dispose de son propre archivage, purement local, qui ne masque rien côté app Facturation non plus.

### 1. Installer Tailscale sur les deux postes

1. Créez un compte sur [tailscale.com](https://tailscale.com) (gratuit pour un usage personnel/petite équipe).
2. Installez Tailscale sur la machine principale **et** sur chaque poste distant, connectez-vous avec le même compte.
3. Sur la machine principale, notez son IP Tailscale : `tailscale ip -4` (ressemble à `100.x.y.z`). C'est cette adresse que les postes distants utiliseront.

### 2. Configurer et démarrer le serveur (machine principale)

Tout se fait depuis la page **« API distante »** de l'application (icône 🌐 dans la barre latérale) :

1. **Configuration** : renseignez l'adresse IP Tailscale de la machine (ex. `100.x.y.z`), le port (`8420` par défaut), puis cliquez sur **« Générer un nouveau jeton »** pour chacun des 4 rôles dont vous avez besoin (client, principal, facturation, stock), puis **Enregistrer**.
   ⚠️ Utilisez toujours l'**IP Tailscale**, jamais `0.0.0.0` — par défaut (`127.0.0.1`), l'API n'est accessible que depuis la machine elle-même.
2. **Serveur** : cliquez sur **« Démarrer le serveur »**. Le statut passe à « ● En ligne ».
3. **Le serveur tourne dans un processus séparé de l'application** — il **continue de fonctionner même après avoir fermé la fenêtre principale**.
4. **Démarrage automatique avec Windows** (optionnel) : cochez « Démarrer automatiquement avec Windows ».
5. Pour changer un jeton plus tard : générez-en un nouveau sur cette page, enregistrez, puis reconfigurez chaque poste concerné.

Alternative en ligne de commande (équivalent au bouton « Démarrer », mais bloquant/au premier plan) : `python -m app.api.server`.

### 3. Configurer et lancer le mode client (postes distants)

```powershell
python -m app.main_client
```

Au premier lancement, une fenêtre demande l'adresse IP Tailscale de la machine principale, le port (`8420` par défaut) et le jeton API (« rôle client ») — sauvegardés dans `client_config.json`, modifiable ensuite via le bouton « ⚙ Connexion ».

### App Stock

```powershell
python -m app.main_stock
```

Rôle strictement limité au suivi de stock : visualiser la quantité en stock de chaque article du catalogue (les lignes en négatif sont signalées en rouge), enregistrer une **entrée** (approvisionnement) ou un **ajustement** correctif (ex. après un inventaire physique), consulter l'historique des mouvements d'un article. Ne permet ni facturation, ni gestion du catalogue (nom/prix), ni paiements — ces fonctionnalités restent exclusivement dans l'app Facturation.

Au premier lancement, une fenêtre demande l'adresse IP Tailscale de la machine principale, le port et le jeton API du **rôle stock**, sauvegardés dans `stock_config.json`.

Enregistrer une facture dans l'app Facturation (en ligne ou hors ligne depuis une machine de facturation) décrémente automatiquement le stock des produits vendus — l'app Stock n'a donc besoin de gérer que les **entrées** de marchandise et les corrections d'inventaire, jamais les sorties liées à une vente.

### Exécutables autonomes

Générés séparément de `SMP.exe` :

- **`SMP-Serveur.exe`** — le serveur seul, sans fenêtre. Doit être copié dans le même dossier que `SMP.exe` (ou `SMP-Client.exe` si c'est lui qui héberge la base).
- **`SMP-Client.exe`** — le mode client, embarque matplotlib (Dashboard) et reportlab (régénération du PDF en local quand ce poste héberge sa propre base).
- **`SMP-Stock.exe`** — l'app Stock, la plus légère (uniquement `requests`, aucune génération de PDF ni de graphique).

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SMP-Serveur" --icon "app/icone.ico" --add-data "logo.png;." app/main_server.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SMP-Client" --icon "app/icone.ico" --add-data "logo.png;." --hidden-import psycopg2 app/main_client.py
python -m PyInstaller --noconfirm --clean --onefile --windowed --name "SMP-Stock" --icon "app/icone.ico" app/main_stock.py
```

`dist\SMP-Serveur.exe` va à côté de `dist\SMP.exe` (machine principale) ; `dist\SMP-Client.exe` et `dist\SMP-Stock.exe` se copient tels quels sur chaque poste distant Windows concerné.

#### Client sur macOS

Le mode client tourne aussi sur Mac (Tkinter + `requests` sont multiplateformes). PyInstaller ne fait pas de cross-compilation : il faut lancer le build **depuis le Mac** où le client sera utilisé.

```bash
./build_client_mac.sh
```

Ce script crée un environnement virtuel dédié et génère **`dist/SMP-Client.app`**. Premier lancement : clic droit → Ouvrir (macOS bloque par défaut les applications non signées).

## Machine de facturation (mode offline-first)

Rôles inversés par rapport à l'accès distant classique : la machine du **boss** (allumée en continu) héberge désormais la base SQLite + le serveur API — elle reste l'unique source de vérité. La machine qui **facture** (souvent éteinte/intermittente) est cliente en écriture, mais reste **pleinement fonctionnelle hors ligne** grâce à un cache SQLite local et une file de synchronisation. Voir `CLAUDE.md`, section « Machine de facturation (offline-first) », pour le détail de l'architecture.

### Sur la machine boss

- **Si le boss utilise déjà `SMP-Client.exe`** : configurez tout depuis son onglet **« Serveur »** (hôte/port, génération des 4 jetons, démarrage). Copiez simplement `SMP-Serveur.exe` dans le même dossier.
- **Sinon** : installez `SMP.exe` normalement, et configurez tout depuis sa page **« API distante »**.

### Sur chaque machine de facturation

**`SMP.exe`** en mode « facturation à distance » : page **« Paramètres machine »** → choisir « Facturation à distance » → Enregistrer → redémarrer l'exécutable. Ce mode ajoute, **en direct par le réseau uniquement** : Historique complet, Archive, Paiements (lecture seule), Vue client. Un bouton « Repasser en machine principale » dans la barre latérale permet de revenir en arrière (redémarrage requis).

Au premier lancement, une fenêtre demande l'adresse IP Tailscale de la machine boss, le port, le jeton du rôle **facturation** et un identifiant pour ce poste — sauvegardés dans `sync_config.json`.

**Facturation**, **Proforma**, **Historique** (local), **Produits** et **Clients** fonctionnent hors ligne grâce au cache local + à la file de synchronisation. Une facture enregistrée hors ligne décrémente aussi le stock localement, appliqué côté boss dès la resynchronisation.

Un bandeau en bas de la barre latérale indique l'état de la synchronisation (🟢 en ligne / 🔴 hors ligne, nombre d'opérations en attente/en erreur).

### Numérotation des factures hors ligne

La numérotation ne bloque **jamais** la création d'une facture, même en coupure réseau prolongée :

- À l'ouverture d'un panier neuf, un numéro est suggéré **instantanément** (sans réseau) ; un sondage de fond met à jour cette suggestion toutes les 3-5 s tant que le boss est joignable.
- Au clic « Enregistrer », une confirmation silencieuse et rapide (délai court) verrouille le numéro auprès du boss ; en cas d'échec ou de lenteur, le numéro suggéré est simplement conservé — jamais de blocage.
- Si la coupure se prolonge (20-30 s sans réponse du sondage de fond), la machine bascule automatiquement sur un pool de numéros de secours, puis sur un calcul déterministe local garanti sans collision avec les autres postes — reprise automatique du mode nominal dès que le réseau revient.
- Les factures déjà créées hors ligne restent consultables et réimprimables localement quel que soit l'état du réseau.

Voir `CLAUDE.md`, section « Numérotation résiliente », pour le détail des trois paliers.

## Tests

```powershell
python -m pytest tests/ -v
```

## Structure du projet

```
app/
├── main.py             # Point d'entrée (app Facturation, machine boss)
├── main_client.py      # Point d'entrée (app Client/Serveur)
├── main_stock.py       # Point d'entrée (app Stock)
├── main_server.py      # Point d'entrée (serveur API autonome)
├── main_facturation.py # Point d'entrée dev/debug de ApplicationFacturation seule
├── config.py           # Constantes (FCFA, chemins, entreprise, config API)
├── i18n/               # Traductions fr/en/zh
├── models/              # Entités métier (dataclasses pures)
├── repositories/        # Accès SQLite (seul endroit avec du SQL)
├── services/            # Logique métier (facturation, stock, stats, PDF, remises, API, sync)
├── ui/                  # Tkinter : app Facturation (app.py + app_facturation.py)
├── api/                 # Serveur FastAPI — accès distant + synchronisation offline-first
├── client/              # App Client/Serveur
├── stock/               # App Stock (nouvelle)
├── sync/                # Machine de facturation : cache local, file de synchro, workers
└── data/                # Base SQLite + exports PDF (créés au lancement)
tests/                 # Tests pytest (services, repositories, API)
docs/ANALYSE_EXCEL.md  # Analyse historique du système Excel de l'entreprise d'origine
CLAUDE.md              # Référence d'architecture et conventions
```

Les règles d'architecture (couches, conventions, commandes) sont détaillées dans [CLAUDE.md](CLAUDE.md).
