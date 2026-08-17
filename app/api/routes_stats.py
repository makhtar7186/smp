"""Endpoints Dashboard (KPI, tops, répartition, évolution) + Remises
annuelles (lecture du tableau) — utilisés par l'onglet « Dashboard »/« Remises »
du mode client (`app/client/ui.py`), qui héberge désormais la base sur la
machine du boss. Lecture seule, ouverte à n'importe quel rôle valide (mêmes
lectures agrégées non sensibles que `/factures`) — voir CLAUDE.md."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends

from app.api.auth import verifier_token
from app.api.deps import obtenir_remises, obtenir_stats
from app.api.schemas import (
    DashboardKpisOut,
    KPIOut,
    RemiseLigneOut,
    RepartitionGammeOut,
    SerieCaPointOut,
    TopProduitOut,
)
from app.services.remise_service import RemiseService
from app.services.stats_service import StatsService

routeur_stats = APIRouter(prefix="/stats", dependencies=[Depends(verifier_token)])
routeur_remises_lecture = APIRouter(prefix="/remises", dependencies=[Depends(verifier_token)])


def _kpi_out(kpi) -> KPIOut:
    return KPIOut(valeur=kpi.valeur, precedent=kpi.precedent,
                 variation_pct=kpi.variation_pct)


@routeur_stats.get("/kpis", response_model=DashboardKpisOut)
def kpis(
    jour: date | None = None,
    stats: StatsService = Depends(obtenir_stats),
) -> DashboardKpisOut:
    """Mêmes KPI que `DashboardView.rafraichir()` : CA jour/mois/année (vs
    période précédente), nombre de ventes de l'année, panier moyen."""
    jour = jour or date.today()
    return DashboardKpisOut(
        ca_jour=_kpi_out(stats.kpi_ca_jour(jour)),
        ca_mois=_kpi_out(stats.kpi_ca_mois(jour)),
        ca_annee=_kpi_out(stats.kpi_ca_annee(jour)),
        nb_ventes=_kpi_out(stats.kpi_nb_ventes_annee(jour)),
        panier_moyen=stats.panier_moyen_annee(jour),
    )


@routeur_stats.get("/top-produits", response_model=list[TopProduitOut])
def top_produits(
    debut: date, fin: date, par: str = "quantite", limite: int = 10,
    stats: StatsService = Depends(obtenir_stats),
) -> list[TopProduitOut]:
    return [TopProduitOut(libelle=libelle, valeur=valeur)
            for libelle, valeur in stats.top_produits(debut, fin, par=par, limite=limite)]


@routeur_stats.get("/repartition-gamme", response_model=list[RepartitionGammeOut])
def repartition_gamme(
    debut: date, fin: date,
    stats: StatsService = Depends(obtenir_stats),
) -> list[RepartitionGammeOut]:
    return [RepartitionGammeOut(gamme=gamme, ca=ca)
            for gamme, ca in stats.repartition_par_gamme(debut, fin)]


@routeur_stats.get("/serie-ca", response_model=list[SerieCaPointOut])
def serie_ca(
    debut: date, fin: date, granularite: str = "mois",
    stats: StatsService = Depends(obtenir_stats),
) -> list[SerieCaPointOut]:
    return [SerieCaPointOut(periode=periode, ca=ca)
            for periode, ca in stats.serie_ca(debut, fin, granularite=granularite)]


@routeur_remises_lecture.get("/tableau", response_model=list[RemiseLigneOut])
def tableau_remises(
    annee: int,
    remises: RemiseService = Depends(obtenir_remises),
) -> list[RemiseLigneOut]:
    """CA annuel par client + remise déjà saisie — équivalent distant de
    `RemisesView.rafraichir()`. L'écriture existe déjà : `POST
    /clients/{id}/remise-annuelle` (`app/api/routes_paiements.py`)."""
    return [
        RemiseLigneOut(
            client_id=ligne.client_id, client_nom=ligne.client_nom,
            client_adresse=ligne.client_adresse,
            ca_annuel=ligne.ca_annuel,
            taux=ligne.taux, montant=ligne.montant, note=ligne.note,
        )
        for ligne in remises.tableau_annee(annee)
    ]
