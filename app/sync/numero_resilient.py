"""Numérotation résiliente (machine de facturation) — palier 1 final, voir
CLAUDE.md, section « Numérotation résiliente » :

- **Suggestion instantanée (`suggerer_numero`)** : jamais de réseau, jamais
  de blocage — `base_connu + 1`, `base_connu` étant maintenu à jour en
  arrière-plan par `NumeroPollerWorker` (sondage `GET /factures/dernier-numero`
  toutes les 3-5 s). Ce numéro reste figé pour la facture en cours de saisie
  (voir `FacturationView`). Bascule vers le pool de secours (palier 2) puis
  le calcul déterministe (palier 3) UNIQUEMENT si le poller de fond est en
  coupure soutenue (`EtatNumerotationRepository.coupure_soutenue`, 20-30 s
  sans sondage réussi) — pas sur un simple ralentissement isolé.
- **Confirmation silencieuse (`confirmer_numero`)** : appelée juste avant
  l'écriture réelle (clic Enregistrer) — le seul endroit avec un vrai verrou
  serveur (`POST /factures/reserver-numeros`, délai court). Réponse conforme
  ou différente → le numéro confirmé est utilisé, sans que l'utilisateur ne
  voie rien d'anormal. Échec/timeout → le numéro suggéré est gardé tel quel
  (aucun repli forcé, aucun blocage), mais inséré directement dans le pool
  local et `base_connu` avancé en conséquence — un futur `suggerer_numero()`
  ne le reproposera donc jamais, sans qu'une confirmation serveur n'ait
  jamais eu lieu (risque résiduel accepté, corrigible via le champ
  modifiable)."""
from __future__ import annotations

from app.sync.api_sync_client import ApiSyncClient, ErreurApiSync
from app.sync.etat_numerotation import EtatNumerotationRepository
from app.sync.numero_reservation import NumeroReservationRepository
from app.sync.numero_worker import taille_bloc_secours


class NumeroResilientService:
    """Point d'entrée unique pour obtenir le prochain numéro à utiliser sur
    la machine de facturation."""

    def __init__(self, numeros: NumeroReservationRepository,
                 etat: EtatNumerotationRepository, api: ApiSyncClient) -> None:
        self._numeros = numeros
        self._etat = etat
        self._api = api

    def suggerer_numero(self) -> int:
        """Palier 1 (nominal) : instantané, sans réseau — voir docstring du
        module. Ne consomme rien dans le pool local (contrairement à l'ancien
        `obtenir_numero`) : une simple suggestion, jamais engagée tant que
        `confirmer_numero` n'a pas été appelé."""
        if not self._etat.coupure_soutenue():
            return self._etat.lire().base_connu + 1

        numero = self._numeros.prochain_disponible("usine")
        if numero is not None and numero > 0:
            # Garde-fou : ignore toute entrée résiduelle ≤ 0 (bug corrigé de
            # `_calculer_bloc_local`, voir CLAUDE.md — une base migrée peut
            # encore en porter une, purgée par ailleurs à la connexion, mais
            # ce garde-fou reste la dernière ligne de défense en mémoire).
            return numero

        return self._calculer_bloc_local()

    def confirmer_numero(self, numero_suggere: int) -> int:
        """Appelée juste avant l'écriture réelle — voir docstring du module.
        Retourne le numéro à utiliser réellement pour l'enregistrement, déjà
        présent dans le pool local (`numeros_reserves`), quelle que soit
        l'issue de la confirmation réseau."""
        try:
            resultat = self._api.reserver_numeros(1, delai_court=True)
        except ErreurApiSync:
            return self._accepter_sans_confirmation(numero_suggere)

        self._etat.definir_n_rang(
            resultat.get("n_postes_actifs", 1), resultat.get("rang", 0))
        numeros = resultat["numeros"]
        if not numeros:
            return self._accepter_sans_confirmation(numero_suggere)
        numero = numeros[0]
        self._etat.definir_base_si_superieur(numero)
        self._numeros.ajouter_bloc("usine", numeros)
        return numero

    def _accepter_sans_confirmation(self, numero: int) -> int:
        """Serveur injoignable/lent au moment de la confirmation : le numéro
        suggéré est gardé tel quel, jamais bloquant — voir docstring du
        module."""
        self._numeros.ajouter_bloc("usine", [numero])
        self._etat.definir_base_si_superieur(numero)
        return numero

    def _calculer_bloc_local(self) -> int:
        """Palier 3 : calcule un bloc entier de secours, sans réseau, et
        l'insère dans le pool local — `prochain_k` (jamais réutilisé) avance
        à chaque appel, mais `base_connu` reste volontairement intact : ce
        n'est qu'une information CONFIRMÉE par le serveur (dernière
        réservation réussie), jamais mise à jour à partir d'un calcul local
        — sinon les blocs suivants, calculés par ce même poste ou par un
        autre resté hors ligne, dériveraient chacun depuis une base
        différente et pourraient se chevaucher.

        Le `+ 1` est essentiel : `base_connu` est le plus haut numéro DÉJÀ
        utilisé (ou réservé) — sans lui, le poste de rang 0 calculerait, à
        son tout premier bloc (k=0), `debut = base_connu + (0 + 0) × taille
        = base_connu`, et réémettrait donc le numéro d'une facture déjà
        existante (ou, sur une machine jamais encore synchronisée, 0 — un
        numéro invalide qui bloque silencieusement tout enregistrement,
        voir CLAUDE.md « Numérotation résiliente »)."""
        etat = self._etat.lire()
        taille = taille_bloc_secours(etat.n_connu)
        k = self._etat.consommer_prochain_k()
        debut = etat.base_connu + 1 + (etat.rang_connu + k * etat.n_connu) * taille
        bloc = list(range(debut, debut + taille))
        self._numeros.ajouter_bloc("usine", bloc)
        return bloc[0]
