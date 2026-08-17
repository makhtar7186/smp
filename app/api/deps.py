"""Dépendances FastAPI : une connexion SQLite par requête (sqlite3 n'est pas
thread-safe sur une connexion partagée), fermée en fin de requête."""
from __future__ import annotations

from collections.abc import Iterator

from app.repositories.base_repository import creer_connexion
from app.repositories.reservation_repository import ReservationNumeroRepository
from app.services.facturation_service import FacturationService
from app.services.paiement_service import PaiementService
from app.services.pdf_service import PdfService
from app.services.remise_service import RemiseService
from app.services.stats_service import StatsService
from app.services.stock_service import StockService


def obtenir_facturation() -> Iterator[FacturationService]:
    """`reservations=ReservationNumeroRepository(conn)` : la facturation
    directe du boss (numérotation en ligne) ne doit jamais réémettre un
    numéro déjà distribué en bloc à une machine de facturation — voir
    CLAUDE.md, section « Machine de facturation »."""
    conn = creer_connexion()
    try:
        yield FacturationService(conn, reservations=ReservationNumeroRepository(conn))
    finally:
        conn.close()


def obtenir_paiements() -> Iterator[PaiementService]:
    """Connexion dédiée pour les endpoints de lecture `routes_paiements.py`
    (recherche client, solde, historique, totaux, synthèse) — pas de
    dépendance exposant ClientRepository directement, la recherche client
    passe par `PaiementService.rechercher_clients`. Les écritures de
    versement passent par la file FIFO (`write_queue.py`), qui ouvre sa
    propre connexion dans le thread worker plutôt que celle-ci."""
    conn = creer_connexion()
    try:
        yield PaiementService(conn)
    finally:
        conn.close()


def obtenir_pdf() -> PdfService:
    return PdfService()


def obtenir_stats() -> Iterator[StatsService]:
    conn = creer_connexion()
    try:
        yield StatsService(conn)
    finally:
        conn.close()


def obtenir_remises() -> Iterator[RemiseService]:
    conn = creer_connexion()
    try:
        yield RemiseService(conn)
    finally:
        conn.close()


def obtenir_stock() -> Iterator[StockService]:
    """Connexion dédiée pour les endpoints de lecture `routes_stock.py`
    (catalogue, historique) — les écritures (entrée/ajustement) passent par
    la file FIFO (`write_queue.py`), qui ouvre sa propre connexion dans le
    thread worker plutôt que celle-ci."""
    conn = creer_connexion()
    try:
        yield StockService(conn)
    finally:
        conn.close()
