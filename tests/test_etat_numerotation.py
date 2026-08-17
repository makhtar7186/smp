"""Tests d'EtatNumerotationRepository : `coupure_soutenue` détecte une vraie
coupure du poller de fond (palier 1) — pas un simple ralentissement isolé.
Voir CLAUDE.md, section « Numérotation résiliente »."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.sync.etat_numerotation import EtatNumerotationRepository


def test_coupure_soutenue_vraie_par_defaut_sans_poll_jamais_reussi(conn) -> None:
    etat_repo = EtatNumerotationRepository(conn)
    assert etat_repo.coupure_soutenue()


def test_coupure_non_soutenue_juste_apres_un_poll_reussi(conn) -> None:
    etat_repo = EtatNumerotationRepository(conn)
    etat_repo.marquer_poll_reussi()
    assert not etat_repo.coupure_soutenue()


def test_coupure_soutenue_au_dela_du_seuil(conn) -> None:
    etat_repo = EtatNumerotationRepository(conn)
    etat_repo.marquer_poll_reussi()
    ancien = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    conn.execute(
        "UPDATE etat_numerotation SET dernier_poll_reussi = ? WHERE id = 1", (ancien,))
    conn.commit()

    assert etat_repo.coupure_soutenue(seuil_secondes=25)


def test_pas_de_coupure_soutenue_sous_le_seuil(conn) -> None:
    etat_repo = EtatNumerotationRepository(conn)
    etat_repo.marquer_poll_reussi()
    recent = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
    conn.execute(
        "UPDATE etat_numerotation SET dernier_poll_reussi = ? WHERE id = 1", (recent,))
    conn.commit()

    assert not etat_repo.coupure_soutenue(seuil_secondes=25)
