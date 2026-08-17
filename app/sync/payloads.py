"""Construction/parsing des payloads JSON de la file de synchronisation
montante. Toujours des clés naturelles (jamais un id local, non portable vers
la machine boss) — voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from datetime import date

from app.models import Client, LigneVente
from app.utils.formatting import date_vers_iso, iso_vers_date


def cle_correlation_facture(numero: int) -> str:
    """Un seul type de facture désormais — la clé de corrélation est portée
    uniquement par le numéro."""
    return f"facture:{numero}"


def construire_payload_facture(
    numero: int, date_facture: date, nom_client: str, destination: str,
    lignes: list[LigneVente], etabli_par: str, remise_taux: float,
    telephone: str = "", matricule: str = "",
) -> dict:
    """Mêmes arguments naturels que `FacturationService.enregistrer_facture`/
    `modifier_facture` — rejouable tel quel côté serveur, qui résout
    lui-même client/produit en autorité (jamais un id local envoyé). La TVA
    n'est jamais transportée : elle est toujours réappliquée par le serveur
    (`config.TVA_TAUX_DEFAUT`), jamais une valeur locale."""
    return {
        "numero": numero,
        "date_facture": date_vers_iso(date_facture),
        "nom_client": nom_client,
        "destination": destination,
        "telephone": telephone,
        "matricule": matricule,
        "etabli_par": etabli_par,
        "remise_taux": remise_taux,
        "lignes": [
            {
                "designation": ligne.designation,
                "quantite": ligne.quantite,
                "prix_unitaire": ligne.prix_unitaire,
                "remarque": ligne.remarque,
            }
            for ligne in lignes
        ],
    }


def parser_payload_facture(payload: dict) -> dict:
    """Reconstruit les arguments naturels (date convertie, lignes en
    `LigneVente`) à partir d'un payload enfilé — utilisé côté serveur par
    `SyncReceptionService`."""
    return {
        "numero": payload["numero"],
        "date_facture": iso_vers_date(payload["date_facture"]),
        "nom_client": payload["nom_client"],
        "destination": payload["destination"],
        "telephone": payload.get("telephone", ""),
        "matricule": payload.get("matricule", ""),
        "etabli_par": payload.get("etabli_par", ""),
        "remise_taux": payload.get("remise_taux", 0.0),
        "lignes": [
            LigneVente(
                designation=l["designation"], quantite=l["quantite"],
                prix_unitaire=l["prix_unitaire"], remarque=l.get("remarque", ""),
            )
            for l in payload["lignes"]
        ],
    }


def cle_correlation_client(nom: str, adresse: str) -> str:
    return f"creation_client:{nom.strip().upper()}|{adresse.strip().upper()}"


def construire_payload_client(nom: str, telephone: str, adresse: str) -> dict:
    """Création autonome d'un client depuis la page Clients de la machine de
    facturation (hors saisie d'une facture, où le client est déjà résolu par
    clé naturelle dans le payload de `creation_facture`/`modification_facture`)."""
    return {"nom": nom, "telephone": telephone, "adresse": adresse}


def cle_correlation_produit(nom: str, type_option: str, valeur_option: str) -> str:
    return f"creation_produit:{nom.strip().upper()}|{type_option.strip().upper()}|{valeur_option.strip().upper()}"


def construire_payload_produit(
    nom: str, type_option: str, valeur_option: str, prix: int,
) -> dict:
    """Création autonome d'un produit depuis la page Produits de la machine
    de facturation (hors saisie d'une facture, où l'auto-création de produit
    est intégralement gérée serveur par le rejeu de `creation_facture`)."""
    return {"nom": nom, "type_option": type_option, "valeur_option": valeur_option,
            "prix": prix}


def cle_correlation_produit_modification(nom: str, type_option: str, valeur_option: str) -> str:
    """Préfixe distinct de `cle_correlation_produit` (création) : une
    modification ne doit jamais fusionner, dans la file d'attente locale,
    avec une création encore non synchronisée du même produit — les deux
    doivent être rejouées dans l'ordre plutôt que collabsées en une seule."""
    return f"modification_produit:{nom.strip().upper()}|{type_option.strip().upper()}|{valeur_option.strip().upper()}"


def construire_payload_produit_modification(
    ancien_nom: str, ancien_type_option: str, ancien_valeur_option: str,
    nom: str, type_option: str, valeur_option: str, prix: int, actif: bool,
) -> dict:
    """Modification (nom/option/prix/actif) d'un produit existant depuis la
    page Produits de la machine de facturation. `ancien_*` porte l'identité
    AVANT modification — seule clé fiable pour retrouver le produit côté
    serveur (jamais un id local) ; les autres champs portent le nouvel état
    à appliquer."""
    return {
        "ancien_nom": ancien_nom, "ancien_type_option": ancien_type_option,
        "ancien_valeur_option": ancien_valeur_option,
        "nom": nom, "type_option": type_option, "valeur_option": valeur_option,
        "prix": prix, "actif": actif,
    }


def cle_correlation_client_modification(nom: str, adresse: str) -> str:
    """Même raisonnement que `cle_correlation_produit_modification` — préfixe
    distinct de `cle_correlation_client` (création)."""
    return f"modification_client:{nom.strip().upper()}|{adresse.strip().upper()}"


def construire_payload_client_modification(
    ancien_nom: str, ancien_adresse: str, nom: str, telephone: str, adresse: str,
) -> dict:
    """Modification (nom/téléphone/adresse) d'un client existant depuis la
    page Clients de la machine de facturation. `ancien_*` identifie la fiche
    à retrouver côté serveur (clé naturelle nom+adresse d'avant l'édition)."""
    return {
        "ancien_nom": ancien_nom, "ancien_adresse": ancien_adresse,
        "nom": nom, "telephone": telephone, "adresse": adresse,
    }


def cle_correlation_fusion(cible: Client, source: Client) -> str:
    return (f"fusion:{cible.nom}|{cible.adresse}>{source.nom}|{source.adresse}")


def construire_payload_fusion_client(cible: Client, source: Client) -> dict:
    """Clés naturelles (nom, adresse) des deux fiches, plus le `modifie_le`
    connu localement au moment de la décision de fusion — le serveur compare
    cette valeur à l'état actuel pour détecter un conflit (voir
    `SyncReceptionService._rejouer_fusion_client`)."""
    return {
        "cible_nom": cible.nom,
        "cible_adresse": cible.adresse,
        "cible_modifie_le_connu": cible.modifie_le,
        "source_nom": source.nom,
        "source_adresse": source.adresse,
        "source_modifie_le_connu": source.modifie_le,
    }
