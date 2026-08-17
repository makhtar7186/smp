"""Tests du pool local de numéros réservés (cache de la machine de
facturation) — voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

from app.sync.numero_reservation import NumeroReservationRepository


def test_prochain_disponible_none_si_pool_vide(conn) -> None:
    repo = NumeroReservationRepository(conn)
    assert repo.prochain_disponible() is None
    assert repo.compter_disponibles() == 0


def test_ajouter_bloc_et_consommer_dans_l_ordre(conn) -> None:
    repo = NumeroReservationRepository(conn)
    repo.ajouter_bloc("usine", [260001, 260002, 260003])
    assert repo.compter_disponibles() == 3

    assert repo.prochain_disponible() == 260001
    repo.marquer_utilise(260001)
    assert repo.compter_disponibles() == 2

    assert repo.prochain_disponible() == 260002
    repo.marquer_utilise(260002)
    assert repo.prochain_disponible() == 260003


def test_ajouter_bloc_deja_present_ignore_les_doublons(conn) -> None:
    repo = NumeroReservationRepository(conn)
    repo.ajouter_bloc("usine", [260001, 260002])
    repo.ajouter_bloc("usine", [260002, 260003])  # 260002 en double, silencieusement ignoré
    assert repo.compter_disponibles() == 3


def test_pools_distincts_par_type_facture(conn) -> None:
    repo = NumeroReservationRepository(conn)
    repo.ajouter_bloc("usine", [260001])
    repo.ajouter_bloc("client", [260002])
    assert repo.prochain_disponible("usine") == 260001
    assert repo.prochain_disponible("client") == 260002
