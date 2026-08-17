"""Tests de ReferentielSyncWorker : upsert non destructif, préservation des
créations locales en attente de synchro, et préservation exacte du
`modifie_le` serveur (nécessaire à la détection de conflit de fusion). Voir
CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

import tempfile
import time

from app.models import Client
from app.repositories.base_repository import creer_connexion
from app.repositories.client_repository import ClientRepository
from app.repositories.produit_repository import ProduitRepository
from app.sync.referentiel_worker import ReferentielSyncWorker


class _FauxApiReferentiel:
    def __init__(self, produits: list[dict] | None = None,
                clients: list[dict] | None = None) -> None:
        self._produits = produits or []
        self._clients = clients or []

    def referentiel_produits(self) -> list[dict]:
        return self._produits

    def referentiel_clients(self) -> list[dict]:
        return self._clients


def test_synchronise_produits_absents_localement(conn) -> None:
    api = _FauxApiReferentiel(produits=[
        {"nom": "SM TAPISSIER", "type_option": "dimension", "valeur_option": "140X190",
         "prix": 10000, "actif": True},
    ])
    worker = ReferentielSyncWorker(":memory:", api)
    worker.synchroniser(conn)

    produit = ProduitRepository(conn).chercher("SM TAPISSIER", "dimension", "140X190")
    assert produit is not None
    assert produit.prix == 10000


def test_met_a_jour_un_produit_existant_sans_le_dupliquer(conn) -> None:
    from app.models import Produit
    produits = ProduitRepository(conn)
    produits.creer(Produit(nom="SM TAPISSIER", type_option="dimension",
                           valeur_option="140X190", prix=9000))

    api = _FauxApiReferentiel(produits=[
        {"nom": "SM TAPISSIER", "type_option": "dimension", "valeur_option": "140X190",
         "prix": 11000, "actif": True},
    ])
    ReferentielSyncWorker(":memory:", api).synchroniser(conn)

    tous = produits.lister()
    assert len(tous) == 1
    assert tous[0].prix == 11000


def test_renommage_via_id_serveur_met_a_jour_sans_dupliquer(conn) -> None:
    """Bug corrigé : un produit renommé depuis l'app Stock (nom/option
    modifiés via `PUT /stock/produits/{id}`) devenait introuvable par son
    ancien nom au prochain pull descendant et se dupliquait au lieu d'être
    mis à jour. Le premier cycle adopte `id_serveur` (retrouvé par clé
    naturelle, encore valide à ce moment-là) ; un second cycle où le nom a
    changé doit alors retrouver le MÊME produit local via `id_serveur`,
    jamais en créer un second."""
    from app.models import Produit
    produits = ProduitRepository(conn)
    local = produits.creer(Produit(nom="BIDON", type_option="litrage",
                                   valeur_option="5L", prix=2500))
    assert local.id_serveur == 0

    # 1er cycle : le produit boss (id_serveur=42) correspond encore par nom
    # — id_serveur est adopté sur la ligne locale à cette occasion.
    api = _FauxApiReferentiel(produits=[
        {"nom": "BIDON", "type_option": "litrage", "valeur_option": "5L",
         "prix": 2500, "actif": True, "quantite_stock": 10, "id_serveur": 42},
    ])
    ReferentielSyncWorker(":memory:", api).synchroniser(conn)
    assert produits.obtenir(local.id).id_serveur == 42

    # 2e cycle : renommé côté boss (toujours id_serveur=42) — plus aucune
    # correspondance possible par (nom, type_option, valeur_option).
    api2 = _FauxApiReferentiel(produits=[
        {"nom": "BIDON PLASTIQUE", "type_option": "litrage", "valeur_option": "5L",
         "prix": 2500, "actif": True, "quantite_stock": 10, "id_serveur": 42},
    ])
    ReferentielSyncWorker(":memory:", api2).synchroniser(conn)

    tous = produits.lister()
    assert len(tous) == 1, "le produit renommé ne doit jamais être dupliqué"
    assert tous[0].nom == "BIDON PLASTIQUE"
    assert tous[0].id == local.id


def test_synchronise_la_quantite_en_stock_d_un_produit_existant(conn) -> None:
    """La quantité en stock du boss doit se répercuter sur le cache local
    d'une machine de facturation hors ligne — sans cela, le blocage anti-
    survente de la facturation (voir CLAUDE.md) comparerait une quantité
    locale jamais mise à jour par les entrées/ajustements faits ailleurs
    (app Stock)."""
    from app.models import Produit
    produits = ProduitRepository(conn)
    local = produits.creer(Produit(nom="BIDON", type_option="litrage",
                                   valeur_option="5L", prix=2500))
    assert local.quantite_stock == 0

    api = _FauxApiReferentiel(produits=[
        {"nom": "BIDON", "type_option": "litrage", "valeur_option": "5L",
         "prix": 2500, "actif": True, "quantite_stock": 714},
    ])
    ReferentielSyncWorker(":memory:", api).synchroniser(conn)

    assert produits.obtenir(local.id).quantite_stock == 714


def test_preserve_une_creation_locale_absente_du_referentiel(conn) -> None:
    """Un client créé localement (encore en attente de synchro montante) et
    absent de la réponse serveur ne doit jamais être supprimé (aucun DELETE)."""
    clients = ClientRepository(conn)
    local = clients.creer(Client(nom="CREE LOCALEMENT", adresse="DAKAR"))

    api = _FauxApiReferentiel(clients=[
        {"nom": "AUTRE CLIENT", "telephone": "", "adresse": "THIES",
         "modifie_le": "2026-01-01T00:00:00"},
    ])
    ReferentielSyncWorker(":memory:", api).synchroniser(conn)

    assert clients.obtenir(local.id) is not None


def test_preserve_le_modifie_le_fourni_par_le_serveur(conn) -> None:
    api = _FauxApiReferentiel(clients=[
        {"nom": "X", "telephone": "", "adresse": "DAKAR",
         "modifie_le": "2020-05-05T12:00:00"},
    ])
    ReferentielSyncWorker(":memory:", api).synchroniser(conn)

    client = ClientRepository(conn).chercher_par_nom_et_adresse("X", "DAKAR")
    assert client.modifie_le == "2020-05-05T12:00:00"


def test_hors_ligne_ne_leve_pas_d_exception(conn) -> None:
    from app.sync.api_sync_client import ErreurInjoignable

    class _ApiHorsLigne:
        def referentiel_produits(self):
            raise ErreurInjoignable("timeout")

        def referentiel_clients(self):
            raise ErreurInjoignable("timeout")

    worker = ReferentielSyncWorker(":memory:", _ApiHorsLigne())
    worker.synchroniser(conn)  # ne doit pas lever


def test_exception_inattendue_ne_tue_pas_le_thread_daemon() -> None:
    """Bug corrigé : une erreur imprévue pendant un cycle (ex. verrou SQLite
    concurrent, champ inattendu — pas une ErreurApiSync) tuait silencieusement
    ce thread daemon pour le reste de la session (`--windowed`, aucune console
    pour voir la trace) — toute synchro descendante s'arrêtait alors pour de
    bon jusqu'au redémarrage de l'app. `_boucle()` doit survivre et retenter
    au cycle suivant."""
    class _ApiCassantUneFois:
        def __init__(self) -> None:
            self.appels = 0

        def referentiel_produits(self) -> list[dict]:
            self.appels += 1
            if self.appels == 1:
                raise KeyError("champ inattendu simulé")
            return []

        def referentiel_clients(self) -> list[dict]:
            return []

    chemin_db = tempfile.mktemp(suffix=".db")
    creer_connexion(chemin_db).close()
    api = _ApiCassantUneFois()
    worker = ReferentielSyncWorker(chemin_db, api, intervalle_secondes=1)
    worker.demarrer()
    try:
        time.sleep(0.3)
        worker.declencher_immediat()
        time.sleep(0.3)
        assert worker._thread is not None and worker._thread.is_alive()
        assert api.appels >= 2, "le worker doit retenter au cycle suivant"
    finally:
        worker.arreter()
