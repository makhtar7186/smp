"""Tests de la file d'attente unifiée de synchronisation (cache local de la
machine de facturation) — voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from app.sync.queue_repository import QueueSyncRepository


def test_enfiler_cree_une_ligne_en_attente(conn) -> None:
    repo = QueueSyncRepository(conn)
    item_id = repo.enfiler("creation_facture", "usine:260001", {"numero": 260001})
    operations = repo.lister()
    assert len(operations) == 1
    assert operations[0].id == item_id
    assert operations[0].statut == "en_attente"
    assert operations[0].payload == {"numero": 260001}


def test_enfiler_meme_correlation_en_attente_ecrase_plutot_que_d_empiler(conn) -> None:
    repo = QueueSyncRepository(conn)
    id1 = repo.enfiler("creation_facture", "usine:260001", {"numero": 260001, "v": 1})
    id2 = repo.enfiler("creation_facture", "usine:260001", {"numero": 260001, "v": 2})
    assert id1 == id2
    operations = repo.lister()
    assert len(operations) == 1
    assert operations[0].payload["v"] == 2


def test_enfiler_meme_correlation_en_erreur_repasse_en_attente(conn) -> None:
    repo = QueueSyncRepository(conn)
    item_id = repo.enfiler("creation_facture", "usine:260001", {"v": 1})
    repo.marquer_erreur(item_id, "fact_panier_vide")
    assert repo.compter_erreur() == 1

    repo.enfiler("modification_facture", "usine:260001", {"v": 2})
    operations = repo.lister()
    assert len(operations) == 1
    assert operations[0].statut == "en_attente"
    assert operations[0].payload["v"] == 2
    assert operations[0].derniere_erreur == ""


def test_enfiler_meme_correlation_deja_synchronisee_cree_une_nouvelle_ligne(conn) -> None:
    repo = QueueSyncRepository(conn)
    id1 = repo.enfiler("creation_facture", "usine:260001", {"v": 1})
    repo.marquer_synchronise(id1)

    id2 = repo.enfiler("modification_facture", "usine:260001", {"v": 2})
    assert id2 != id1
    assert len(repo.lister()) == 2


def test_prochaine_a_traiter_ordre_chronologique(conn) -> None:
    repo = QueueSyncRepository(conn)
    repo.enfiler("creation_client", "client:A|DAKAR", {})
    repo.enfiler("creation_produit", "produit:X", {})
    premiere = repo.prochaine_a_traiter()
    assert premiere.type_operation == "creation_client"


def test_cycle_de_vie_statuts(conn) -> None:
    repo = QueueSyncRepository(conn)
    item_id = repo.enfiler("creation_facture", "usine:260001", {})
    assert repo.compter_en_attente() == 1

    repo.marquer_en_cours(item_id)
    assert repo.compter_en_attente() == 1  # en_cours compte comme "en attente de fin"

    repo.marquer_erreur(item_id, "erreur réseau")
    assert repo.compter_erreur() == 1
    assert repo.compter_en_attente() == 0

    repo.reessayer(item_id)
    assert repo.compter_en_attente() == 1
    assert repo.compter_erreur() == 0


def test_remettre_en_attente_ne_marque_pas_erreur(conn) -> None:
    repo = QueueSyncRepository(conn)
    item_id = repo.enfiler("creation_facture", "usine:260001", {})
    repo.marquer_en_cours(item_id)
    repo.remettre_en_attente(item_id)
    assert repo.compter_erreur() == 0
    assert repo.lister()[0].statut == "en_attente"


def test_prochaine_a_traiter_bloque_sur_une_ligne_en_erreur(conn) -> None:
    """Une erreur métier sur l'item N doit rester bloquante d'un passage du
    worker à l'autre, pas seulement au sein d'un même passage — sinon l'ordre
    chronologique strict serait violé dès le passage suivant."""
    repo = QueueSyncRepository(conn)
    id1 = repo.enfiler("creation_facture", "usine:1", {})
    repo.enfiler("creation_facture", "usine:2", {})
    repo.marquer_erreur(id1, "erreur métier")
    assert repo.prochaine_a_traiter() is None
    repo.reessayer(id1)
    assert repo.prochaine_a_traiter().cle_correlation == "usine:1"


def test_reinitialiser_en_cours_recupere_apres_un_crash(conn) -> None:
    repo = QueueSyncRepository(conn)
    item_id = repo.enfiler("creation_facture", "usine:1", {})
    repo.marquer_en_cours(item_id)
    assert repo.prochaine_a_traiter() is None

    assert repo.reinitialiser_en_cours() == 1
    assert repo.prochaine_a_traiter().id == item_id


def test_statut_pour_facture(conn) -> None:
    repo = QueueSyncRepository(conn)
    assert repo.statut_pour_facture(260001) is None
    item_id = repo.enfiler("creation_facture", "facture:260001", {})
    assert repo.statut_pour_facture(260001) == "en_attente"
    repo.marquer_synchronise(item_id)
    assert repo.statut_pour_facture(260001) == "synchronise"
