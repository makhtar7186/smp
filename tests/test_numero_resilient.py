"""Tests de NumeroResilientService : palier 1 final (suggestion instantanée
+ confirmation silencieuse) et repli sur les paliers 2 (pool de secours) et
3 (calcul déterministe hors ligne) quand le poller de fond est en coupure
soutenue. Voir CLAUDE.md, section « Numérotation résiliente »."""
from __future__ import annotations

import pytest

from app.repositories.base_repository import creer_connexion
from app.sync.api_sync_client import ErreurInjoignable
from app.sync.etat_numerotation import EtatNumerotationRepository
from app.sync.numero_reservation import NumeroReservationRepository
from app.sync.numero_resilient import NumeroResilientService


class _FauxApi:
    def __init__(self, reponses: list | None = None) -> None:
        self._reponses = list(reponses or [])
        self.appels: list[tuple[int, bool]] = []

    def reserver_numeros(self, quantite: int, delai_court: bool = False) -> dict:
        self.appels.append((quantite, delai_court))
        reponse = self._reponses.pop(0)
        if isinstance(reponse, Exception):
            raise reponse
        return reponse


@pytest.fixture()
def service(conn):
    numeros = NumeroReservationRepository(conn)
    etat = EtatNumerotationRepository(conn)
    return numeros, etat


# Suggestion (palier 1, jamais de réseau) -------------------------------------
def test_suggestion_sans_coupure_est_base_plus_un_sans_reseau(service) -> None:
    numeros, etat = service
    etat.definir_base_si_superieur(500)
    etat.marquer_poll_reussi()  # poller de fond actif : pas de coupure soutenue
    api = _FauxApi()
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.suggerer_numero()

    assert numero == 501
    assert api.appels == []  # jamais de réseau pour une simple suggestion


def test_suggestion_coupure_soutenue_retombe_sur_le_pool_de_secours(service) -> None:
    numeros, etat = service
    numeros.ajouter_bloc("usine", [700, 701])  # etat frais : coupure_soutenue() vraie par défaut
    api = _FauxApi()
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.suggerer_numero()

    assert numero == 700  # le plus petit du pool de secours
    assert api.appels == []


def test_suggestion_coupure_soutenue_et_pool_vide_calcule_localement(service) -> None:
    numeros, etat = service
    etat.definir_base_si_superieur(1000)
    etat.definir_n_rang(2, 1)  # 2 postes actifs, ce poste est le rang 1
    api = _FauxApi()
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.suggerer_numero()

    # bloc(k=0) = base(1000) + 1 + (rang(1) + 0*N(2)) * taille(5) = 1006
    assert numero == 1006
    assert numeros.est_disponible(1006)
    assert numeros.est_disponible(1010)  # bloc entier de 5 inséré
    assert api.appels == []


def test_suggestion_ignore_une_entree_residuelle_invalide_dans_le_pool(service) -> None:
    """Défense en profondeur : même si une entrée invalide (≤ 0) subsiste
    dans le pool local (donnée résiduelle d'avant le correctif de
    `_calculer_bloc_local`, voir CLAUDE.md), `suggerer_numero()` ne doit
    jamais la retourner — la purge à la connexion (`base_repository.
    _purger_numeros_reserves_invalides`) est la ligne de défense normale,
    ce garde-fou en mémoire en est une seconde, indépendante."""
    numeros, etat = service
    numeros.conn.execute(
        "INSERT INTO numeros_reserves (type_facture, numero, statut)"
        " VALUES ('usine', 0, 'disponible')")
    numeros.conn.commit()
    etat.definir_base_si_superieur(500)
    api = _FauxApi()
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.suggerer_numero()

    assert numero != 0
    assert numero == 501


def test_suggestion_calcul_local_ne_reemet_jamais_le_numero_deja_connu(service) -> None:
    """Bug corrigé : au rang 0 / bloc k=0, la formule sans `+1` retournait
    exactement `base_connu` — un numéro déjà utilisé (ou, sur une machine
    jamais synchronisée, base_connu=0, un numéro invalide qui bloquait
    silencieusement tout enregistrement). Voir CLAUDE.md."""
    numeros, etat = service
    etat.definir_base_si_superieur(500)  # dernier numéro RÉELLEMENT déjà utilisé
    api = _FauxApi()
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.suggerer_numero()

    assert numero == 501  # jamais 500 (déjà pris)


def test_suggestion_machine_jamais_synchronisee_ne_suggere_jamais_zero(service) -> None:
    """Machine de facturation fraîchement installée (jamais parlé au
    serveur) : `base_connu` vaut 0 par défaut — la suggestion doit rester un
    numéro de facture valide (≥ 1), jamais 0."""
    numeros, etat = service
    api = _FauxApi()
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.suggerer_numero()

    assert numero == 1


def test_appels_successifs_hors_ligne_ne_collisionnent_jamais_entre_deux_postes() -> None:
    """Deux postes (même base/N, rangs différents) suggérant chacun
    plusieurs numéros successifs en coupure soutenue, sans jamais se
    synchroniser entre eux, ne doivent jamais produire le même numéro."""
    numeros_du_poste: dict[int, set[int]] = {0: set(), 1: set()}
    for rang in (0, 1):
        conn = creer_connexion(":memory:")
        numeros = NumeroReservationRepository(conn)
        etat = EtatNumerotationRepository(conn)
        etat.definir_base_si_superieur(5000)
        etat.definir_n_rang(2, rang)
        api = _FauxApi()
        resilient = NumeroResilientService(numeros, etat, api)
        for _ in range(4):
            resilient.suggerer_numero()
        rows = conn.execute("SELECT numero FROM numeros_reserves").fetchall()
        numeros_du_poste[rang] = {row["numero"] for row in rows}
        conn.close()

    assert numeros_du_poste[0].isdisjoint(numeros_du_poste[1])


# Confirmation (palier 1, seul endroit avec un vrai verrou serveur) ----------
def test_confirmation_reussie_retourne_le_numero_du_serveur_et_avance_base(service) -> None:
    numeros, etat = service
    api = _FauxApi([{"numeros": [500], "n_postes_actifs": 1, "rang": 0}])
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.confirmer_numero(499)  # numéro suggéré, ajusté par le serveur

    assert numero == 500
    assert api.appels == [(1, True)]  # toujours quantite=1, délai court
    assert numeros.est_disponible(500)
    assert etat.lire().base_connu == 500


def test_confirmation_echoue_garde_le_numero_suggere_sans_bloquer(service) -> None:
    numeros, etat = service
    api = _FauxApi([ErreurInjoignable("timeout")])
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.confirmer_numero(777)

    assert numero == 777  # aucun repli forcé : le numéro suggéré est gardé tel quel
    assert numeros.est_disponible(777)  # inséré quand même, jamais bloquant
    assert etat.lire().base_connu == 777  # jamais reproposé par une future suggestion


def test_pool_local_reste_source_unique_de_consommation_normale(service) -> None:
    """Une fois un numéro confirmé (ou accepté sans confirmation), il suit le
    même chemin de validation que le pool alimenté par le serveur (voir
    `FacturationServiceHorsLigne.enregistrer_facture`)."""
    numeros, etat = service
    api = _FauxApi([ErreurInjoignable("x")])
    resilient = NumeroResilientService(numeros, etat, api)

    numero = resilient.confirmer_numero(42)
    assert numeros.est_disponible(numero)
    numeros.marquer_utilise(numero)
    assert not numeros.est_disponible(numero)
