"""Service des paiements (versements) et des remises partagées entre l'app
principale et l'app client (accès distant) — voir CLAUDE.md, section
« Paiements »."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from app.models import Client, Facture, Remise, Versement
from app.repositories.client_repository import ClientRepository
from app.repositories.facture_repository import FactureRepository
from app.repositories.remise_repository import RemiseRepository
from app.repositories.versement_repository import VersementRepository
from app.services.remise_service import RemiseService
from app.utils.recherche import correspond, decouper_termes
from app.utils.validation import ErreurValidation


def _total_net_liste(facture: Facture) -> int:
    """Total net (après remise) d'une facture issue de `FactureRepository.lister`
    (qui remplit `total_liste`/`nb_lignes` mais jamais `lignes` — la propriété
    `total_net`, basée sur la somme des lignes, y vaudrait toujours 0)."""
    remise_montant = round(facture.total_liste * facture.remise_taux / 100) \
        if facture.remise_taux else 0
    return facture.total_liste - remise_montant


@dataclass
class SoldeFacture:
    """Solde d'une facture : montant dû, versé, restant. `restant` peut être
    négatif (trop-perçu, autorisé librement — voir CLAUDE.md)."""

    facture_id: int
    total: int
    verse: int
    restant: int


@dataclass
class TotauxPaiements:
    """Totaux agrégés sur un ensemble de factures filtré (barre du bas des vues)."""

    total_facture: int = 0
    total_verse: int = 0
    total_restant: int = 0


@dataclass
class SyntheseClient:
    """Synthèse d'un client : total dépensé, versé, restant dû, remises reçues."""

    total_facture: int = 0
    total_verse: int = 0
    total_restant: int = 0
    total_remises: int = 0


class PaiementService:
    """Logique métier des paiements : enregistrement des versements, calcul de
    solde, agrégats, et écriture partagée des remises (par facture et
    annuelle) — seul point d'accès pour l'API `routes_paiements.py` et les
    vues UI « Paiements »/« Vue client »."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._versements = VersementRepository(conn)
        self._factures = FactureRepository(conn)
        self._remises = RemiseRepository(conn)
        self._clients = ClientRepository(conn)
        self._remise_service = RemiseService(conn)

    # Versements ---------------------------------------------------------------
    def enregistrer_versement(
        self, facture_id: int, montant: int, date_versement: date,
        machine_origine: str = "", role_origine: str = "local", remarque: str = "",
    ) -> Versement:
        """Enregistre un versement (append-only). Le montant peut être négatif
        (correction d'un versement précédent) mais jamais nul. Aucune borne
        n'est imposée sur le solde résultant : un trop-perçu est autorisé
        librement (règle confirmée — voir CLAUDE.md). `remarque` est une note
        libre optionnelle expliquant la nature du versement (ex. « acompte »,
        « règlement final », « correction erreur de saisie »)."""
        if self._factures.obtenir(facture_id) is None:
            raise ErreurValidation("paie_facture_introuvable")
        if montant == 0:
            raise ErreurValidation("paie_montant_nul")
        versement = Versement(
            facture_id=facture_id,
            date_versement=date_versement,
            montant=montant,
            machine_origine=machine_origine,
            role_origine=role_origine,
            remarque=remarque.strip(),
        )
        return self._versements.enregistrer(versement)

    def obtenir_facture(self, facture_id: int) -> Facture | None:
        """Facture complète (en-tête + lignes) — utilisé par l'API pour
        vérifier le type ('usine') avant d'exposer solde/historique."""
        return self._factures.obtenir(facture_id)

    def calculer_solde_facture(self, facture_id: int) -> SoldeFacture:
        """Solde d'une facture : `total` = total net (après remise), `verse` =
        somme des versements, `restant` = total - verse (peut être négatif)."""
        facture = self._factures.obtenir(facture_id)
        if facture is None:
            raise ErreurValidation("paie_facture_introuvable")
        verse = self._versements.somme_par_facture(facture_id)
        return SoldeFacture(
            facture_id=facture_id, total=facture.total_net, verse=verse,
            restant=facture.total_net - verse,
        )

    def historique_versements(self, facture_id: int) -> list[Versement]:
        """Versements d'une facture, du plus ancien au plus récent."""
        return self._versements.lister_par_facture(facture_id)

    def lister_avec_solde(
        self, recherche: str = "", client_id: int | None = None,
        date_debut: date | None = None, date_fin: date | None = None,
        inclure_archivees: bool = False,
    ) -> list[tuple[Facture, SoldeFacture]]:
        """Factures avec leur solde, filtrables par nom de client, destination,
        numéro de facture ou téléphone du client (dénormalisé sur `Facture`,
        voir CLAUDE.md section « Téléphone et matricule » — recherche en
        mémoire, sur un jeu déjà filtré par période/client côté SQL) —
        utilisé par la vue Paiements (app principale et app cliente) et
        `GET /paiements/factures`. Supporte la recherche multi-termes
        (plusieurs clients à la fois, ex. « ALPHA, BETA » — voir
        `app.utils.recherche.decouper_termes`).

        `inclure_archivees` : par défaut, respecte l'archivage de
        l'application principale (comme le reste de ses vues). L'API
        distante (`routes_paiements.py`) passe `True` — chaque application
        gère son propre système d'archivage (voir CLAUDE.md), l'archivage
        principal ne doit pas masquer de factures au poste distant."""
        factures = self._factures.lister(
            date_debut, date_fin, client_id,
            inclure_archivees=inclure_archivees)
        termes = decouper_termes(recherche)
        if termes:
            factures = [
                f for f in factures
                if correspond(f.client_nom, termes) or correspond(f.destination, termes)
                or correspond(str(f.numero), termes) or correspond(f.telephone, termes)
            ]
        sommes = self._versements.sommes_par_factures([f.id for f in factures if f.id])
        resultat = []
        for facture in factures:
            verse = sommes.get(facture.id, 0)
            total = _total_net_liste(facture)
            solde = SoldeFacture(
                facture_id=facture.id, total=total, verse=verse,
                restant=total - verse,
            )
            resultat.append((facture, solde))
        return resultat

    def totaux_globaux(
        self, date_debut: date | None = None, date_fin: date | None = None,
        client_id: int | None = None, inclure_archivees: bool = False,
    ) -> TotauxPaiements:
        """Totaux agrégés (total facturé net, total versé, total restant) sur
        les factures correspondant aux filtres — mêmes filtres que l'historique
        des ventes. `inclure_archivees` : voir `lister_avec_solde`."""
        factures = self._factures.lister(
            date_debut, date_fin, client_id,
            inclure_archivees=inclure_archivees)
        sommes = self._versements.sommes_par_factures([f.id for f in factures if f.id])
        totaux = TotauxPaiements()
        for facture in factures:
            verse = sommes.get(facture.id, 0)
            total = _total_net_liste(facture)
            totaux.total_facture += total
            totaux.total_verse += verse
            totaux.total_restant += total - verse
        return totaux

    # Synthèse client ------------------------------------------------------------
    def total_depense_par_client(
        self, client_id: int, annee: int | None = None,
        date_debut: date | None = None, date_fin: date | None = None,
    ) -> SyntheseClient:
        """Synthèse pour la vue « Vue client » : total dépensé, total versé,
        total restant, total des remises (par facture + annuelle).

        Le filtre est soit une année entière (`annee`), soit une période
        précise (`date_debut`/`date_fin`, prioritaire dès que l'une des deux
        est fournie — permet de bien définir une période, ex. un mois ou une
        plage à cheval sur deux années) ; sans aucun filtre, porte sur tout
        l'historique du client."""
        periode_precise = date_debut is not None or date_fin is not None
        if periode_precise:
            factures = self._factures.lister(
                date_debut=date_debut, date_fin=date_fin, client_id=client_id,
                inclure_archivees=True)
        else:
            factures = self._factures.lister(
                client_id=client_id, inclure_archivees=True)
            if annee is not None:
                factures = [f for f in factures if f.date_facture.year == annee]

        synthese = SyntheseClient()
        for facture in factures:
            verse = self._versements.somme_par_facture(facture.id) if facture.id else 0
            total = _total_net_liste(facture)
            remise_montant = facture.total_liste - total
            synthese.total_facture += total
            synthese.total_verse += verse
            synthese.total_restant += total - verse
            synthese.total_remises += remise_montant

        if periode_precise:
            # Remise(s) annuelle(s) des années couvertes par la période précise
            for annee_couverte in {f.date_facture.year for f in factures}:
                remise = self._remises.lister_annee(annee_couverte).get(client_id)
                if remise:
                    synthese.total_remises += remise.montant
        elif annee is not None:
            remise_annee = self._remises.lister_annee(annee).get(client_id)
            if remise_annee:
                synthese.total_remises += remise_annee.montant
        else:
            synthese.total_remises += self._remises.somme_client(client_id)
        return synthese

    # Remises partagées (écriture ouverte aux deux rôles) -------------------------
    def appliquer_remise_facture(
        self, facture_id: int, remise_taux: float, modifie_par: str,
    ) -> None:
        """Applique/modifie la remise ponctuelle d'une facture, avec traçabilité
        de qui l'a écrite (role_principal, role_client, ou 'local')."""
        if self._factures.obtenir(facture_id) is None:
            raise ErreurValidation("paie_facture_introuvable")
        if not 0 <= remise_taux <= 100:
            raise ErreurValidation("fact_remise_invalide")
        self._factures.enregistrer_remise_facture(facture_id, remise_taux, modifie_par)

    def appliquer_remise_annuelle(
        self, client_id: int, annee: int, ca_annuel: int, taux: float,
        note: str, modifie_par: str,
    ) -> Remise:
        """Applique/modifie la remise annuelle d'un client, avec traçabilité."""
        return self._remise_service.enregistrer(
            client_id, annee, ca_annuel, taux, note, modifie_par=modifie_par)

    # Recherche client (lecture seule) --------------------------------------------
    def rechercher_clients(self, q: str) -> list[Client]:
        """Recherche client par nom/localité — seul point d'accès pour l'API
        et l'UI (jamais dupliqué)."""
        return self._clients.rechercher(q)
