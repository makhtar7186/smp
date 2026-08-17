"""Tests de FacturationServiceHorsLigne : numérotation exclusivement issue du
pool réservé, atomicité de l'écriture + enfilage de synchro."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import LigneVente
from app.sync.facturation_hors_ligne import FacturationServiceHorsLigne
from app.sync.numero_reservation import NumeroReservationRepository
from app.sync.queue_repository import QueueSyncRepository
from app.utils.validation import ErreurValidation


def _service(conn) -> FacturationServiceHorsLigne:
    return FacturationServiceHorsLigne(
        conn, queue=QueueSyncRepository(conn), numeros=NumeroReservationRepository(conn))


def _ligne() -> LigneVente:
    return LigneVente(designation="SM TAPISSIER 140X190X", 
                      quantite=2, prix_unitaire=10000)


def test_prochain_numero_leve_si_pool_vide(conn) -> None:
    service = _service(conn)
    with pytest.raises(ErreurValidation):
        service.prochain_numero()


def test_prochain_numero_tire_du_pool_jamais_ad_hoc(conn) -> None:
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001, 260002])
    service = FacturationServiceHorsLigne(conn, queue=QueueSyncRepository(conn),
                                          numeros=numeros)
    assert service.prochain_numero() == 260001


def test_numero_saisi_manuellement_hors_pool_est_rejete(conn) -> None:
    """Un numéro non issu du pool réservé ne doit jamais être accepté — même
    saisi manuellement — sinon la garantie « jamais de numéro ad hoc hors
    ligne » serait contournée."""
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001])
    service = FacturationServiceHorsLigne(conn, queue=QueueSyncRepository(conn),
                                          numeros=numeros)
    with pytest.raises(ErreurValidation):
        service.enregistrer_facture(
            numero=999999, date_facture=date(2026, 3, 1), nom_client="TEST",
            destination="DAKAR", lignes=[_ligne()])


def test_reserver_bloc_numeros_indisponible_sur_la_machine_de_facturation(conn) -> None:
    service = _service(conn)
    with pytest.raises(ErreurValidation):
        service.reserver_bloc_numeros(10)


def test_enregistrement_et_enfilage_sont_atomiques(conn) -> None:
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001])
    queue = QueueSyncRepository(conn)
    service = FacturationServiceHorsLigne(conn, queue=queue, numeros=numeros)

    facture = service.enregistrer_facture(
        numero=260001, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR", lignes=[_ligne()],
    )
    assert facture.id is not None

    # La facture existe localement...
    assert service.obtenir_facture(facture.id) is not None
    # ...et la même transaction a enfilé l'opération de synchro.
    operations = queue.lister()
    assert len(operations) == 1
    assert operations[0].type_operation == "creation_facture"
    assert operations[0].cle_correlation == "facture:260001"
    assert operations[0].payload["nom_client"] == "TEST"
    assert operations[0].payload["lignes"][0]["designation"] == "SM TAPISSIER 140X190X"

    # Le numéro consommé n'est plus disponible dans le pool.
    assert numeros.compter_disponibles() == 0


def test_payload_transporte_telephone_et_matricule(conn) -> None:
    """Sans ça, le boss recevrait une facture sans ces champs (voir CLAUDE.md,
    section « Téléphone et matricule »)."""
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001])
    queue = QueueSyncRepository(conn)
    service = FacturationServiceHorsLigne(conn, queue=queue, numeros=numeros)

    facture = service.enregistrer_facture(
        numero=260001, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR", lignes=[_ligne()],
        telephone="77 000 00 00", matricule="DK-1234-A",
    )
    assert facture.telephone == "77 000 00 00"
    assert facture.matricule == "DK-1234-A"
    operations = queue.lister()
    assert operations[0].payload["telephone"] == "77 000 00 00"
    assert operations[0].payload["matricule"] == "DK-1234-A"


def test_modification_avant_synchro_ecrase_la_meme_ligne_de_queue(conn) -> None:
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001])
    queue = QueueSyncRepository(conn)
    service = FacturationServiceHorsLigne(conn, queue=queue, numeros=numeros)

    facture = service.enregistrer_facture(
        numero=260001, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR", lignes=[_ligne()],
    )
    service.modifier_facture(
        facture_id=facture.id, numero=260001, date_facture=date(2026, 3, 1),
        nom_client="TEST MODIFIE", destination="DAKAR", lignes=[_ligne()],
    )

    operations = queue.lister()
    assert len(operations) == 1, "la modification doit écraser la création encore en attente"
    assert operations[0].payload["nom_client"] == "TEST MODIFIE"


def test_suppression_enfile_operation_avec_le_numero(conn) -> None:
    """Sans cette synchro, le boss continuerait de voir une facture qui
    n'existe plus sur la machine de facturation (voir CLAUDE.md)."""
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001])
    queue = QueueSyncRepository(conn)
    service = FacturationServiceHorsLigne(conn, queue=queue, numeros=numeros)
    facture = service.enregistrer_facture(
        numero=260001, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR", lignes=[_ligne()])
    queue.marquer_synchronise(queue.lister()[0].id)  # création déjà synchronisée

    service.supprimer_facture(facture.id)

    assert service.obtenir_facture(facture.id) is None
    operations = queue.lister(["en_attente"])
    assert len(operations) == 1
    assert operations[0].type_operation == "suppression_facture"
    assert operations[0].payload["numero"] == 260001


def test_suppression_avant_synchro_ecrase_la_creation_en_attente(conn) -> None:
    """Facture créée puis supprimée avant d'avoir jamais atteint le serveur :
    la file ne doit garder que la suppression, jamais les deux empilées."""
    numeros = NumeroReservationRepository(conn)
    numeros.ajouter_bloc("usine", [260001])
    queue = QueueSyncRepository(conn)
    service = FacturationServiceHorsLigne(conn, queue=queue, numeros=numeros)
    facture = service.enregistrer_facture(
        numero=260001, date_facture=date(2026, 3, 1), nom_client="TEST",
        destination="DAKAR", lignes=[_ligne()])

    service.supprimer_facture(facture.id)

    operations = queue.lister()
    assert len(operations) == 1
    assert operations[0].type_operation == "suppression_facture"
