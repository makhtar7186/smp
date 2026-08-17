"""Accès direct à la base pour `ApplicationClient` quand ce poste héberge
lui-même le serveur (onglet Serveur, voir CLAUDE.md section « Accès distant »
et `ApplicationClient._config_auto_locale`). Implémente exactement la même
interface que `app.client.api_client.ApiClient` pour les **lectures**
(Historique, Paiements en lecture, recherche client, Dashboard, Remises) —
les onglets existants n'ont donc besoin d'aucune modification, qu'ils
reçoivent un `ApiClient` (HTTP, poste vraiment distant) ou un
`AccesDirectDonnees` (ce module).

Les **écritures** (versement, remise annuelle) continuent volontairement de
passer par le serveur HTTP local (`ApiClient` interne) : `creer_versement`
passe par la file FIFO du serveur (`app/api/write_queue.py`), seule protection
contre une corruption si un poste réellement distant écrit au même instant —
la contourner en écrivant directement en SQLite depuis ce process
réintroduirait exactement le risque de concurrence que cette file élimine.

Toute erreur inattendue (ex. base verrouillée) est convertie en
`ErreurApiClient` plutôt que de remonter telle quelle, pour que les `except`
déjà en place dans `app/client/ui.py` continuent de fonctionner sans
modification, qu'on soit en accès direct ou en HTTP."""
from __future__ import annotations

import functools
from datetime import date

from app.client.api_client import ApiClient, ErreurApiClient
from app.client.config_client import ConfigClient
from app.services.facturation_service import FacturationService
from app.services.paiement_service import PaiementService
from app.services.pdf_service import PdfService
from app.services.remise_service import RemiseService
from app.services.stats_service import StatsService


def _capturer_erreurs(methode):
    """Convertit toute exception inattendue (sqlite3.Error notamment) en
    `ErreurApiClient`, pour un comportement identique à un appel HTTP en échec
    du point de vue des `except` de `app/client/ui.py`."""
    @functools.wraps(methode)
    def enveloppe(self, *args, **kwargs):
        try:
            return methode(self, *args, **kwargs)
        except ErreurApiClient:
            raise
        except Exception as exc:  # noqa: BLE001 — jamais un crash de l'UI
            raise ErreurApiClient(str(exc)) from exc
    return enveloppe


class AccesDirectDonnees:
    """Même surface de méthodes que `ApiClient`, lectures directes en base,
    écritures déléguées à un `ApiClient` HTTP interne (127.0.0.1)."""

    def __init__(self, conn, config: ConfigClient) -> None:
        self._facturation = FacturationService(conn)
        self._paiements = PaiementService(conn)
        self._stats = StatsService(conn)
        self._remises = RemiseService(conn)
        self._pdf = PdfService()
        self._http = ApiClient(config)

    def tester_connexion(self) -> bool:
        return True

    # Historique / impression (lecture seule) -----------------------------------
    @_capturer_erreurs
    def lister_factures(self, date_debut: date | None = None,
                        date_fin: date | None = None) -> list[dict]:
        factures = self._facturation.lister_factures(
            date_debut=date_debut, date_fin=date_fin, inclure_archivees=True,
        )
        return [
            {"id": f.id, "numero": f.numero, "date_facture": f.date_facture.isoformat(),
             "client_nom": f.client_nom, "destination": f.destination,
             "total": f.total_liste, "remise_taux": f.remise_taux, "nb_lignes": f.nb_lignes}
            for f in factures
        ]

    def _facture_ou_404(self, facture_id: int):
        facture = self._facturation.obtenir_facture(facture_id)
        if facture is None:
            raise ErreurApiClient("Facture introuvable.")
        return facture

    @_capturer_erreurs
    def telecharger_pdf(self, facture_id: int) -> bytes:
        facture = self._facture_ou_404(facture_id)
        return self._pdf.generer_facture(facture).read_bytes()

    @_capturer_erreurs
    def telecharger_bordereau(self, facture_id: int) -> bytes:
        facture = self._facture_ou_404(facture_id)
        return self._pdf.generer_bordereau(facture).read_bytes()

    # Paiements -------------------------------------------------------------------
    @_capturer_erreurs
    def lister_factures_paiements(self, recherche: str = "",
                                  client_id: int | None = None,
                                  date_debut: date | None = None,
                                  date_fin: date | None = None) -> list[dict]:
        resultat = self._paiements.lister_avec_solde(
            recherche=recherche, client_id=client_id,
            date_debut=date_debut, date_fin=date_fin,
            inclure_archivees=True,
        )
        return [
            {"id": facture.id, "numero": facture.numero,
             "date_facture": facture.date_facture.isoformat(),
             "client_nom": facture.client_nom, "destination": facture.destination,
             "total": solde.total, "verse": solde.verse, "restant": solde.restant}
            for facture, solde in resultat
        ]

    @_capturer_erreurs
    def obtenir_facture_paiement(self, facture_id: int) -> dict:
        facture = self._paiements.obtenir_facture(facture_id)
        if facture is None:
            raise ErreurApiClient("Facture introuvable.")
        solde = self._paiements.calculer_solde_facture(facture_id)
        versements = self._paiements.historique_versements(facture_id)
        return {
            "id": facture.id, "numero": facture.numero,
            "date_facture": facture.date_facture.isoformat(),
            "client_nom": facture.client_nom, "destination": facture.destination,
            "remise_taux": facture.remise_taux,
            "remise_modifiee_par": facture.remise_modifiee_par,
            "remise_modifiee_le": facture.remise_modifiee_le,
            "solde": {"facture_id": solde.facture_id, "total": solde.total,
                     "verse": solde.verse, "restant": solde.restant},
            "versements": [
                {"id": v.id, "facture_id": v.facture_id,
                 "date_versement": v.date_versement.isoformat(), "montant": v.montant,
                 "machine_origine": v.machine_origine, "role_origine": v.role_origine,
                 "remarque": v.remarque, "created_at": v.created_at}
                for v in versements
            ],
            "lignes": [
                {"designation": l.designation,
                 "quantite": l.quantite, "prix_unitaire": l.prix_unitaire,
                 "total": l.total, "remarque": l.remarque}
                for l in facture.lignes
            ],
        }

    def creer_versement(self, facture_id: int, montant: int,
                        date_versement: date, remarque: str = "") -> dict:
        """Volontairement via HTTP local (file FIFO du serveur) — voir
        docstring du module."""
        return self._http.creer_versement(facture_id, montant, date_versement, remarque)

    def appliquer_remise_annuelle(self, client_id: int, annee: int, ca_annuel: int,
                                  taux: float, note: str = "") -> dict:
        """Volontairement via HTTP local — voir docstring du module."""
        return self._http.appliquer_remise_annuelle(client_id, annee, ca_annuel, taux, note)

    @_capturer_erreurs
    def totaux_paiements(self, **filtres) -> dict:
        totaux = self._paiements.totaux_globaux(
            inclure_archivees=True, **filtres)
        return {"total_facture": totaux.total_facture, "total_verse": totaux.total_verse,
                "total_restant": totaux.total_restant}

    @_capturer_erreurs
    def synthese_client(self, client_id: int, annee: int | None = None,
                        date_debut: date | None = None, date_fin: date | None = None) -> dict:
        synthese = self._paiements.total_depense_par_client(
            client_id, annee=annee, date_debut=date_debut, date_fin=date_fin)
        return {"total_facture": synthese.total_facture, "total_verse": synthese.total_verse,
                "total_restant": synthese.total_restant, "total_remises": synthese.total_remises}

    @_capturer_erreurs
    def rechercher_clients(self, q: str) -> list[dict]:
        return [{"id": c.id, "nom": c.nom, "adresse": c.adresse}
                for c in self._paiements.rechercher_clients(q)]

    # Dashboard / Remises -----------------------------------------------------
    @_capturer_erreurs
    def stats_kpis(self, jour: date | None = None) -> dict:
        jour = jour or date.today()

        def _kpi(k) -> dict:
            return {"valeur": k.valeur, "precedent": k.precedent,
                   "variation_pct": k.variation_pct}

        return {
            "ca_jour": _kpi(self._stats.kpi_ca_jour(jour)),
            "ca_mois": _kpi(self._stats.kpi_ca_mois(jour)),
            "ca_annee": _kpi(self._stats.kpi_ca_annee(jour)),
            "nb_ventes": _kpi(self._stats.kpi_nb_ventes_annee(jour)),
            "panier_moyen": self._stats.panier_moyen_annee(jour),
        }

    @_capturer_erreurs
    def stats_top_produits(self, debut: date, fin: date, par: str = "quantite",
                           limite: int = 10) -> list[dict]:
        return [{"libelle": libelle, "valeur": valeur}
                for libelle, valeur in self._stats.top_produits(
                    debut, fin, par=par, limite=limite)]

    @_capturer_erreurs
    def stats_repartition_gamme(self, debut: date, fin: date) -> list[dict]:
        return [{"gamme": gamme, "ca": ca}
                for gamme, ca in self._stats.repartition_par_gamme(debut, fin)]

    @_capturer_erreurs
    def stats_serie_ca(self, debut: date, fin: date,
                       granularite: str = "mois") -> list[dict]:
        return [{"periode": periode, "ca": ca}
                for periode, ca in self._stats.serie_ca(debut, fin, granularite=granularite)]

    @_capturer_erreurs
    def remises_tableau(self, annee: int) -> list[dict]:
        # Clé exposée "client_adresse", cohérente avec `RemiseLigneOut`
        # (schéma HTTP de `/remises/tableau`) et `LigneRemise.client_adresse`.
        return [
            {"client_id": ligne.client_id, "client_nom": ligne.client_nom,
             "client_adresse": ligne.client_adresse, "ca_annuel": ligne.ca_annuel,
             "taux": ligne.taux, "montant": ligne.montant, "note": ligne.note}
            for ligne in self._remises.tableau_annee(annee)
        ]
