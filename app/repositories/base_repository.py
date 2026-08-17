"""Connexion SQLite (ou PostgreSQL pour la base boss, voir CLAUDE.md section
« Bascule PostgreSQL ») et création du schéma."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app import config
from app.repositories.db_backend import colonnes_existantes, connecter_postgres

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    adresse TEXT NOT NULL DEFAULT '',
    telephone TEXT NOT NULL DEFAULT '',
    modifie_le TEXT NOT NULL DEFAULT '',  -- ISO datetime, détecte un conflit de fusion différée
    -- Des clients homonymes sont autorisés s'ils ont une adresse différente
    UNIQUE (nom, adresse)
);
-- Le téléphone, quand renseigné, est en plus globalement unique (avec
-- l'adresse, c'est l'élément essentiel d'identification d'un client) — index
-- partiel : ne s'applique pas aux fiches sans téléphone connu (ex. saisies
-- rapides à la facturation).
CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_telephone_unique
    ON clients(telephone) WHERE telephone != '';

CREATE TABLE IF NOT EXISTS produits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nom TEXT NOT NULL,
    type_option TEXT NOT NULL DEFAULT '',    -- 'dimension' | 'litrage' | ''
    valeur_option TEXT NOT NULL DEFAULT '',  -- ex. "5L" ou "40x60"
    prix INTEGER NOT NULL DEFAULT 0,         -- FCFA
    actif INTEGER NOT NULL DEFAULT 1,
    quantite_stock INTEGER NOT NULL DEFAULT 0,  -- géré exclusivement par l'app Stock
    -- Id du produit côté boss, appris par une machine de facturation via la
    -- synchro descendante — 0 (jamais utilisé) sur la base boss elle-même.
    -- Clé de corrélation stable pour retrouver un produit renommé (voir
    -- CLAUDE.md, section « Machine de facturation »).
    id_serveur INTEGER NOT NULL DEFAULT 0,
    UNIQUE (nom, type_option, valeur_option)
);

CREATE TABLE IF NOT EXISTS factures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero INTEGER NOT NULL,
    date_facture TEXT NOT NULL,             -- ISO YYYY-MM-DD
    client_id INTEGER REFERENCES clients(id),
    client_nom TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL DEFAULT '',
    telephone TEXT NOT NULL DEFAULT '',   -- téléphone du client, dénormalisé (affichage/PDF)
    matricule TEXT NOT NULL DEFAULT '',   -- matricule du véhicule de livraison, saisi librement
    etabli_par TEXT NOT NULL DEFAULT '',
    archivee INTEGER NOT NULL DEFAULT 0,  -- masquée de l'historique des ventes (n'affecte pas les stats)
    remise_taux REAL NOT NULL DEFAULT 0,  -- % appliqué à CETTE facture (0 = aucune remise)
    remise_modifiee_par TEXT NOT NULL DEFAULT '',  -- traçabilité : rôle ayant fixé remise_taux
    remise_modifiee_le TEXT NOT NULL DEFAULT '',   -- ISO datetime de la dernière modification
    tva_taux REAL NOT NULL DEFAULT 0      -- % de TVA appliqué (toujours 18, non modifiable en UI)
);
CREATE INDEX IF NOT EXISTS idx_factures_numero ON factures(numero);
CREATE INDEX IF NOT EXISTS idx_factures_date ON factures(date_facture);

CREATE TABLE IF NOT EXISTS lignes_vente (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    facture_id INTEGER NOT NULL REFERENCES factures(id) ON DELETE CASCADE,
    produit_id INTEGER REFERENCES produits(id),
    designation TEXT NOT NULL,
    quantite INTEGER NOT NULL,
    prix_unitaire INTEGER NOT NULL,
    remarque TEXT NOT NULL DEFAULT '',
    ref_externe INTEGER UNIQUE              -- clé d'idempotence import (héritée, inutilisée)
);
CREATE INDEX IF NOT EXISTS idx_lignes_facture ON lignes_vente(facture_id);

-- Mouvements de stock (append-only, même esprit que `versements`) : chaque
-- ligne est un delta signé appliqué à `produits.quantite_stock` (positif =
-- entrée, négatif = sortie/ajustement correctif). La quantité en stock d'un
-- produit est la somme de ses mouvements, mais `produits.quantite_stock` est
-- maintenue en cache pour un affichage rapide (mise à jour atomique avec
-- l'insertion du mouvement — voir StockRepository/FacturationService).
CREATE TABLE IF NOT EXISTS mouvements_stock (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produit_id INTEGER NOT NULL REFERENCES produits(id) ON DELETE CASCADE,
    type_mouvement TEXT NOT NULL,           -- 'entree' | 'sortie' | 'ajustement'
    quantite INTEGER NOT NULL,              -- delta signé
    reference TEXT NOT NULL DEFAULT '',     -- n° de facture (sortie liée à une vente) ou note libre
    source TEXT NOT NULL DEFAULT 'manuel',  -- 'vente' | 'manuel'
    machine_id TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mouvements_stock_produit ON mouvements_stock(produit_id, id);

CREATE TABLE IF NOT EXISTS remises (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    annee INTEGER NOT NULL,
    ca_annuel INTEGER NOT NULL DEFAULT 0,
    taux REAL NOT NULL DEFAULT 0,
    montant INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    modifie_par TEXT NOT NULL DEFAULT '',  -- traçabilité : rôle ayant écrit/modifié
    modifie_le TEXT NOT NULL DEFAULT '',   -- ISO datetime de la dernière modification
    UNIQUE (client_id, annee)
);

-- Versements (paiements) reçus sur une facture. Append-only strict : jamais
-- d'UPDATE/DELETE — une correction s'effectue via un versement négatif
-- compensatoire (voir CLAUDE.md, section « Paiements »).
CREATE TABLE IF NOT EXISTS versements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    facture_id INTEGER NOT NULL REFERENCES factures(id) ON DELETE CASCADE,
    date_versement TEXT NOT NULL,            -- ISO YYYY-MM-DD
    montant INTEGER NOT NULL,                -- FCFA, peut être négatif (correction)
    machine_origine TEXT NOT NULL DEFAULT '',
    role_origine TEXT NOT NULL DEFAULT '',
    remarque TEXT NOT NULL DEFAULT '',       -- note libre (nature du versement)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))  -- horodatage serveur
);
CREATE INDEX IF NOT EXISTS idx_versements_facture ON versements(facture_id);

-- Brouillons de facture (proforma) : jamais de numéro tant qu'ils ne sont
-- pas validés (ProformaService.valider les convertit en facture usine, puis
-- les supprime — voir CLAUDE.md, section « Proforma »).
CREATE TABLE IF NOT EXISTS proformas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date_creation TEXT NOT NULL,             -- ISO YYYY-MM-DD
    client_nom TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL DEFAULT '',
    telephone TEXT NOT NULL DEFAULT '',      -- téléphone du client, dénormalisé (affichage/PDF)
    matricule TEXT NOT NULL DEFAULT '',      -- matricule du véhicule de livraison, saisi librement
    etabli_par TEXT NOT NULL DEFAULT '',
    remise_taux REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS lignes_proforma (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proforma_id INTEGER NOT NULL REFERENCES proformas(id) ON DELETE CASCADE,
    designation TEXT NOT NULL,
    quantite INTEGER NOT NULL,
    prix_unitaire INTEGER NOT NULL,
    remarque TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_lignes_proforma ON lignes_proforma(proforma_id);

-- Architecture offline-first (machine de facturation cliente / machine boss
-- serveur, voir CLAUDE.md section « Machine de facturation »). Les 4 tables
-- suivantes partagent le même schéma des deux côtés (base boss et cache
-- local de la machine de facturation) : chaque machine n'utilise que celles
-- qui la concernent, les autres restent vides et inoffensives.

-- BOSS uniquement : blocs de numéros (numérotation continue) déjà distribués
-- (consommés ou non) à une machine de facturation — empêche la facturation
-- directe du boss de réémettre un numéro déjà remis à un poste hors ligne.
-- `annee` reste stockée à titre indicatif/historique (colonne conservée
-- telle quelle), mais n'intervient plus dans le calcul du plancher.
CREATE TABLE IF NOT EXISTS reservations_numeros (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_facture TEXT NOT NULL DEFAULT 'usine',
    annee INTEGER NOT NULL,
    numero_min INTEGER NOT NULL,
    numero_max INTEGER NOT NULL,
    machine_id TEXT NOT NULL DEFAULT '',
    reserve_le TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_reservations_numeros_annee ON reservations_numeros(annee);

-- BOSS uniquement : journal append-only des fusions de clients rejouées
-- depuis une machine de facturation, y compris celles appliquées malgré un
-- conflit détecté (jamais purgé — voir ClientMaintenanceServiceHorsLigne).
CREATE TABLE IF NOT EXISTS historique_fusions_clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_origine TEXT NOT NULL DEFAULT '',
    demande_le TEXT NOT NULL DEFAULT '',
    traite_le TEXT NOT NULL DEFAULT (datetime('now')),
    client_a_garder_nom TEXT NOT NULL,
    client_a_garder_adresse TEXT NOT NULL DEFAULT '',
    client_a_supprimer_nom TEXT NOT NULL,
    client_a_supprimer_adresse TEXT NOT NULL DEFAULT '',
    client_a_garder_id_serveur INTEGER,
    client_a_supprimer_id_serveur INTEGER,
    conflit_detecte INTEGER NOT NULL DEFAULT 0,
    etat_avant_json TEXT NOT NULL DEFAULT '',
    etat_apres_json TEXT NOT NULL DEFAULT '',
    resultat TEXT NOT NULL DEFAULT 'applique'  -- 'applique' | 'echec'
);
CREATE INDEX IF NOT EXISTS idx_historique_fusions_traite_le ON historique_fusions_clients(traite_le);

-- CACHE (machine de facturation) uniquement : pool de numéros réservés
-- auprès du serveur, consommés localement un par un — jamais de numéro
-- généré ad hoc hors ligne.
CREATE TABLE IF NOT EXISTS numeros_reserves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_facture TEXT NOT NULL DEFAULT 'usine',
    numero INTEGER NOT NULL UNIQUE,
    statut TEXT NOT NULL DEFAULT 'disponible',  -- 'disponible' | 'utilise'
    reserve_le TEXT NOT NULL DEFAULT (datetime('now')),
    utilise_le TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_numeros_reserves_statut ON numeros_reserves(statut, numero);

-- BOSS uniquement : dernière activité connue de chaque machine de facturation
-- (heartbeat porté par le canal de synchro descendante déjà existant, voir
-- ReferentielSyncWorker — aucune requête dédiée) : sert à déterminer N (le
-- nombre de postes actuellement actifs) et le rang de chacun, pour le calcul
-- déterministe de repli hors ligne (palier 3 — voir CLAUDE.md, section
-- « Numérotation résiliente »).
-- `id` auto-incrémenté par convention avec toutes les autres tables de ce
-- schéma (pas seulement `machine_id`) : `ConnexionPostgres.execute()`
-- ajoute automatiquement `RETURNING id` à tout INSERT pour émuler
-- `lastrowid` (voir `app/repositories/db_backend.py`) — une table sans
-- colonne `id` ferait échouer cet ajout automatique sur PostgreSQL.
CREATE TABLE IF NOT EXISTS machines_actives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id TEXT NOT NULL UNIQUE,
    dernier_vu TEXT NOT NULL
);

-- CACHE (machine de facturation) uniquement : état local de l'algorithme de
-- numérotation résiliente — un seul enregistrement (id=1). `base_connu` est
-- le plus haut numéro de facture jamais vu dans l'historique complet (appris
-- en continu par NumeroPollerWorker, palier 1, et par chaque réservation
-- confirmée) ; `n_connu`/`rang_connu` sont les dernières valeurs communiquées
-- par le boss ; `prochain_k` avance à chaque bloc calculé localement sans
-- jamais être réutilisé ; `dernier_poll_reussi` (vide = jamais) horodate le
-- dernier contact serveur réussi (poll OU confirmation), pour détecter une
-- coupure soutenue (20-30 s, voir CLAUDE.md).
CREATE TABLE IF NOT EXISTS etat_numerotation (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    base_connu INTEGER NOT NULL DEFAULT 0,
    n_connu INTEGER NOT NULL DEFAULT 1,
    rang_connu INTEGER NOT NULL DEFAULT 0,
    prochain_k INTEGER NOT NULL DEFAULT 0,
    dernier_poll_reussi TEXT NOT NULL DEFAULT ''
);

-- CACHE (machine de facturation) uniquement : file d'attente unifiée de
-- synchronisation montante, traitée dans l'ordre chronologique strict par
-- SyncWorker (voir app/sync/worker.py).
CREATE TABLE IF NOT EXISTS queue_synchronisation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type_operation TEXT NOT NULL,           -- creation_facture | modification_facture |
                                             -- creation_client | creation_produit | fusion_client
    cle_correlation TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL,
    statut TEXT NOT NULL DEFAULT 'en_attente',  -- en_attente | en_cours | synchronise | erreur
    tentatives INTEGER NOT NULL DEFAULT 0,
    derniere_erreur TEXT NOT NULL DEFAULT '',
    cree_le TEXT NOT NULL DEFAULT (datetime('now')),
    traite_le TEXT NOT NULL DEFAULT '',
    machine_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_queue_sync_statut ON queue_synchronisation(statut, id);
CREATE INDEX IF NOT EXISTS idx_queue_sync_correlation ON queue_synchronisation(cle_correlation, statut);
"""


def _schema_postgresql() -> str:
    """Dérive le schéma PostgreSQL du schéma SQLite canonique (`_SCHEMA`) par
    substitution ciblée — une seule source de vérité, jamais deux schémas
    maintenus séparément qui pourraient diverger silencieusement :
    - `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY`
    - `DEFAULT (datetime('now'))` → supprimé : le code Python fournit
      désormais toujours cet horodatage explicitement (voir
      `app.utils.formatting.horodatage_sql`), pour un format identique
      quel que soit le moteur — voir CLAUDE.md, section « Bascule
      PostgreSQL »."""
    schema = re.sub(r"INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY", _SCHEMA)
    schema = re.sub(r"\s*DEFAULT \(datetime\('now'\)\)", "", schema)
    return schema


def _corriger_machines_actives_postgres(conn) -> None:
    """Corrige, sur une base PostgreSQL déjà provisionnée, la forme boguée
    de `machines_actives` d'avant l'ajout de sa colonne `id` (bug : tout
    `INSERT` s'y voyait ajouter automatiquement `RETURNING id` par
    `ConnexionPostgres.execute`, qui échouait faute de cette colonne — la
    synchro descendante entière était alors cassée, chaque appel de
    `GET /referentiels/produits`/`clients` levant une erreur serveur). Cette
    table n'étant qu'un heartbeat entièrement reconstitué en quelques
    secondes, la recréer ne perd rien d'utile — bien plus sûr qu'un ALTER
    TABLE pour ajouter une clé primaire après coup."""
    colonnes = colonnes_existantes(conn, "machines_actives")
    if colonnes and "id" not in colonnes:
        conn.execute("DROP TABLE machines_actives")
        conn.commit()


def creer_connexion(chemin_db: Path | str | None = None):
    """Ouvre une connexion à la base de données et garantit la présence du
    schéma.

    Sans argument (`chemin_db=None`, la base par défaut de l'application) :
    sensible à `config.lire_moteur_bdd()` — SQLite (défaut, comportement
    historique inchangé) ou PostgreSQL (base boss uniquement, voir CLAUDE.md,
    section « Bascule PostgreSQL »). Un `chemin_db` explicite (fichier ou
    `:memory:` — machine de facturation, tests) reste TOUJOURS SQLite, quel
    que soit le moteur configuré : les caches locaux offline-first ne
    basculent jamais vers un moteur qui exigerait un serveur réseau
    joignable."""
    if chemin_db is None and config.lire_moteur_bdd() == "postgresql":
        pg = config.lire_config_postgres()
        conn = connecter_postgres(pg["hote"], pg["port"], pg["base"],
                                  pg["utilisateur"], pg["mot_de_passe"])
        _corriger_machines_actives_postgres(conn)
        conn.executescript(_schema_postgresql())
        # Une base PostgreSQL est en principe toujours créée fraîche avec le
        # schéma COMPLET actuel — mais l'expérience a montré (`machines_actives`,
        # puis `produits.id_serveur`) qu'une base déjà provisionnée peut se
        # retrouver avec un schéma antérieur à l'ajout d'une colonne : `_migrer()`
        # tourne donc aussi ici (portable, voir sa docstring).
        _migrer(conn)
        return conn

    if chemin_db is None:
        config.preparer_dossiers()
        chemin_db = config.CHEMIN_DB
    conn = sqlite3.connect(str(chemin_db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Sans ceci, le délai d'attente par défaut de SQLite face à un verrou pris
    # par une autre connexion est de 0 ms : la moindre écriture concurrente
    # (plusieurs threads workers + le thread UI, chacun avec sa propre
    # connexion vers le même fichier cache) lève immédiatement "database is
    # locked" plutôt que d'attendre. Cette erreur n'étant pas une ErreurApiSync,
    # elle n'est interceptée par aucun worker et tuait silencieusement son
    # thread daemon (voir CLAUDE.md, section « Machine de facturation ») —
    # 5 s laisse largement le temps à une écriture concurrente de se terminer.
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(chemin_db) != ":memory:":
        # WAL : permet les lectures concurrentes pendant une écriture (plusieurs
        # machines clientes peuvent enregistrer des versements simultanément).
        conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_SCHEMA)
    _migrer(conn)
    return conn


def _migrer(conn) -> None:
    """Ajoute les colonnes manquantes aux bases créées par une version antérieure
    de ce schéma (SOCIÉTÉ DES MATIÈRES PLASTIQUES). Les anciennes bases au
    format SMP (gamme/dimensions/épaisseur, clients.localite,
    factures.type_facture, etc.) ne sont pas prises en charge par une
    migration incrémentale : ce schéma correspond à un nouveau tenant, sans
    donnée héritée à faire évoluer par ALTER TABLE.

    Appelée pour les deux moteurs (SQLite et PostgreSQL, voir
    `creer_connexion`) : `colonnes_existantes` est déjà portable, et
    l'expérience de `machines_actives` (voir CLAUDE.md) a montré qu'une base
    PostgreSQL déjà provisionnée peut, elle aussi, se retrouver avec un
    schéma antérieur à l'ajout d'une colonne."""
    colonnes_versements = colonnes_existantes(conn, "versements")
    if "remarque" not in colonnes_versements:
        conn.execute("ALTER TABLE versements ADD COLUMN remarque TEXT NOT NULL"
                     " DEFAULT ''")

    colonnes_remises = colonnes_existantes(conn, "remises")
    if "modifie_par" not in colonnes_remises:
        conn.execute("ALTER TABLE remises ADD COLUMN modifie_par TEXT NOT NULL"
                     " DEFAULT ''")
    if "modifie_le" not in colonnes_remises:
        conn.execute("ALTER TABLE remises ADD COLUMN modifie_le TEXT NOT NULL"
                     " DEFAULT ''")

    colonnes_produits = colonnes_existantes(conn, "produits")
    if "id_serveur" not in colonnes_produits:
        conn.execute("ALTER TABLE produits ADD COLUMN id_serveur INTEGER NOT NULL"
                     " DEFAULT 0")

    colonnes_etat_numerotation = colonnes_existantes(conn, "etat_numerotation")
    if colonnes_etat_numerotation and "dernier_poll_reussi" not in colonnes_etat_numerotation:
        conn.execute("ALTER TABLE etat_numerotation ADD COLUMN dernier_poll_reussi"
                     " TEXT NOT NULL DEFAULT ''")

    colonnes_factures = colonnes_existantes(conn, "factures")
    if "telephone" not in colonnes_factures:
        conn.execute("ALTER TABLE factures ADD COLUMN telephone TEXT NOT NULL"
                     " DEFAULT ''")
    if "matricule" not in colonnes_factures:
        conn.execute("ALTER TABLE factures ADD COLUMN matricule TEXT NOT NULL"
                     " DEFAULT ''")

    colonnes_proformas = colonnes_existantes(conn, "proformas")
    if colonnes_proformas and "telephone" not in colonnes_proformas:
        conn.execute("ALTER TABLE proformas ADD COLUMN telephone TEXT NOT NULL"
                     " DEFAULT ''")
    if colonnes_proformas and "matricule" not in colonnes_proformas:
        conn.execute("ALTER TABLE proformas ADD COLUMN matricule TEXT NOT NULL"
                     " DEFAULT ''")

    conn.commit()
    _ajouter_contrainte_unique_factures_numero(conn)
    _purger_numeros_reserves_invalides(conn)


def _purger_numeros_reserves_invalides(conn) -> None:
    """Purge défensive de `numeros_reserves` (cache de la machine de
    facturation) : un bug corrigé de `NumeroResilientService._calculer_bloc_local`
    (formule sans `+1`, voir CLAUDE.md, « Numérotation résiliente ») a pu, sur
    une machine jamais encore synchronisée avant le correctif, insérer un
    numéro **0** (ou tout numéro ≤ 0, invalide) comme `disponible` — resté
    piégé dans le pool local depuis (jamais consommé, puisque `_lire_entete`
    refuse toute saisie ≤ 0), et reproposé indéfiniment par
    `prochain_disponible()` malgré le correctif du calcul lui-même : corriger
    le CODE ne suffit pas à effacer une DONNÉE déjà écrite avant lui. Appelée
    séparément de l'`executescript` du schéma canonique : la table peut ne
    pas exister sur une base qui n'a jamais servi de cache de facturation."""
    try:
        conn.execute(
            "DELETE FROM numeros_reserves WHERE statut = 'disponible' AND numero <= 0")
        conn.commit()
    except Exception:
        conn.rollback()


def _ajouter_contrainte_unique_factures_numero(conn) -> None:
    """Garde-fou final contre tout doublon résiduel de numéro de facture
    (voir CLAUDE.md, section « Numérotation résiliente ») — un index unique
    plutôt qu'une contrainte UNIQUE sur la colonne, pour pouvoir l'ajouter
    après coup sans réécrire la table. Ignore silencieusement si des
    doublons existent déjà (bases historiques antérieures à la suppression
    de la notion de facture « revendeur », qui autorisait explicitement deux
    factures à partager un numéro) : mieux vaut ne pas imposer cette
    contrainte que de faire planter l'app au démarrage — à corriger
    manuellement le cas échéant. Appelée séparément de l'`executescript` du
    schéma canonique, jamais depuis celui-ci : une seule instruction en
    erreur y ferait échouer la création de TOUTES les tables suivantes."""
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_factures_numero_unique"
            " ON factures(numero)")
        conn.commit()
    except Exception:
        conn.rollback()


class BaseRepository:
    """Classe mère des repositories : partage la connexion (`sqlite3.Connection`,
    ou `ConnexionPostgres` pour la base boss sur PostgreSQL — même interface
    `.execute()`/`.commit()`/`.rollback()`, voir `app.repositories.db_backend`)."""

    def __init__(self, conn) -> None:
        self.conn = conn
