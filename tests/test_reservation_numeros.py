"""Tests de la réservation de blocs de numéros (numérotation continue, boss)
— voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
from app.repositories.reservation_repository import ReservationNumeroRepository
from app.services.facturation_service import FacturationService


def _service(chemin_db: Path) -> FacturationService:
    conn = creer_connexion(chemin_db)
    return FacturationService(conn, reservations=ReservationNumeroRepository(conn))


def test_reservation_puis_facturation_directe_ne_collisionnent_pas(tmp_path: Path) -> None:
    """Un bloc distribué à une machine de facturation ne doit jamais être
    réémis par la facturation directe du boss."""
    chemin_db = tmp_path / "test.db"
    service = _service(chemin_db)
    reference = date(2026, 3, 1)

    numeros = service.reserver_bloc_numeros(5, machine_id="comptoir-1")
    assert numeros == [1, 2, 3, 4, 5]

    # Sans le registre de réservations, le boss réémettrait 1 (aucune facture
    # n'existe encore réellement) — avec, il doit sauter tout le bloc.
    assert service.prochain_numero() == 6

    facture = service.enregistrer_facture(
        numero=service.prochain_numero(), date_facture=reference,
        nom_client="TEST", destination="DAKAR",
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=1, prix_unitaire=10000)],
    )
    assert facture.numero == 6


def test_pas_de_plafond_ni_de_troncature(tmp_path: Path) -> None:
    """Numérotation continue : contrairement à l'ancien schéma AANNNN
    (plafonné à 9999 factures/an), une réservation ne doit jamais être
    tronquée, quelle que soit la quantité demandée."""
    chemin_db = tmp_path / "test.db"
    service = _service(chemin_db)

    # Dépasse largement l'ancien plafond annuel de 9999 — jamais tronqué.
    premier_bloc = service.reserver_bloc_numeros(15000)
    assert len(premier_bloc) == 15000
    assert premier_bloc == list(range(1, 15001))

    second_bloc = service.reserver_bloc_numeros(5)
    assert second_bloc == [15001, 15002, 15003, 15004, 15005]


class TestReservationJit:
    """`reserver_numero_jit` (palier 1) : reprend un numéro abandonné par
    la MÊME machine plutôt que d'en brûler un nouveau — voir CLAUDE.md,
    section « Numérotation résiliente »."""

    def test_reprend_le_numero_abandonne_par_la_meme_machine(self, tmp_path: Path) -> None:
        service = _service(tmp_path / "test.db")
        premier = service.reserver_numero_jit("poste-1")
        assert premier == 1

        # Rien n'a été facturé entre-temps (fermeture de l'app sans
        # enregistrer) : redemander depuis la MÊME machine reprend le même
        # numéro plutôt que d'avancer à 2.
        second = service.reserver_numero_jit("poste-1")
        assert second == 1

    def test_avance_normalement_une_fois_la_facture_enregistree(self, tmp_path: Path) -> None:
        service = _service(tmp_path / "test.db")
        numero = service.reserver_numero_jit("poste-1")
        service.enregistrer_facture(
            numero=numero, date_facture=date(2026, 3, 1), nom_client="TEST",
            destination="DAKAR",
            lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)],
        )
        suivant = service.reserver_numero_jit("poste-1")
        assert suivant == numero + 1

    def test_n_avance_pas_les_numeros_d_une_autre_machine(self, tmp_path: Path) -> None:
        """Un numéro abandonné par le poste A n'est jamais repris par le
        poste B — seule la machine qui l'a reçu peut le reprendre, sans
        quoi deux machines pourraient toutes deux croire détenir le même
        numéro."""
        service = _service(tmp_path / "test.db")
        premier = service.reserver_numero_jit("poste-A")
        deuxieme = service.reserver_numero_jit("poste-B")
        assert premier == 1
        assert deuxieme == 2  # jamais repris, avance normalement

    def test_bloc_deja_distribue_n_est_jamais_repris(self, tmp_path: Path) -> None:
        """Le plancher tient compte du dernier bloc de secours (palier 2)
        déjà distribué (jamais réémis, comme `reserver_bloc_numeros`), mais
        seule une réservation JIT de taille 1 peut être reprise — reprendre
        un BLOC serait risqué, le boss ne sachant pas combien de numéros de
        ce bloc la machine a déjà consommés localement."""
        service = _service(tmp_path / "test.db")
        service.reserver_bloc_numeros(5, machine_id="poste-1")  # 1..5, jamais repris
        numero = service.reserver_numero_jit("poste-1")
        assert numero == 6
        # Toujours pas de facture réelle : CETTE réservation JIT (taille 1,
        # elle) est en revanche reprise.
        assert service.reserver_numero_jit("poste-1") == 6


def test_reservations_concurrentes_sans_chevauchement(tmp_path: Path) -> None:
    """N machines demandent un bloc de 7 numéros au même instant : jamais deux
    blocs qui se chevauchent, même sous forte concurrence simulée."""
    chemin_db = tmp_path / "test.db"
    creer_connexion(chemin_db).close()  # crée le schéma avant le fan-out de threads
    n = 15
    quantite = 7

    def _reserver(i: int) -> list[int]:
        service = _service(chemin_db)
        return service.reserver_bloc_numeros(quantite, machine_id=f"machine-{i}")

    with ThreadPoolExecutor(max_workers=n) as executor:
        blocs = list(executor.map(_reserver, range(n)))

    tous_les_numeros: list[int] = []
    for bloc in blocs:
        assert len(bloc) == quantite
        tous_les_numeros.extend(bloc)

    assert len(tous_les_numeros) == len(set(tous_les_numeros)), (
        "des blocs réservés se chevauchent")
    assert len(tous_les_numeros) == n * quantite
