"""Test de non-régression : un bug corrigé de `_calculer_bloc_local` (formule
sans `+1`, voir CLAUDE.md, « Numérotation résiliente ») a pu insérer un
numéro invalide (0 ou négatif) comme `disponible` dans `numeros_reserves`,
avant le correctif — resté piégé dans le pool local d'une machine déjà
utilisée, puisque jamais consommé (`_lire_entete` refuse toute saisie ≤ 0).
Corriger le CODE ne suffit pas : une purge défensive doit nettoyer la
DONNÉE déjà écrite (`base_repository._purger_numeros_reserves_invalides`,
appelée à chaque connexion)."""
from __future__ import annotations

from pathlib import Path

from app.repositories.base_repository import creer_connexion
from app.sync.numero_reservation import NumeroReservationRepository


def test_reconnexion_purge_les_numeros_invalides_residuels(tmp_path: Path) -> None:
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    # Simule la donnée corrompue laissée par l'ancien bug (avant le `+1`).
    conn.execute(
        "INSERT INTO numeros_reserves (type_facture, numero, statut)"
        " VALUES ('usine', 0, 'disponible')")
    conn.execute(
        "INSERT INTO numeros_reserves (type_facture, numero, statut)"
        " VALUES ('usine', 261612, 'disponible')")
    conn.commit()
    conn.close()

    conn = creer_connexion(chemin_db)  # ré-exécute _migrer(), donc la purge
    numeros = NumeroReservationRepository(conn)

    assert numeros.prochain_disponible("usine") == 261612  # jamais 0
    assert not numeros.est_disponible(0)


def test_purge_ne_touche_pas_les_numeros_deja_utilises(tmp_path: Path) -> None:
    """Un numéro 0 déjà marqué `utilise` (improbable mais jamais rencontré en
    pratique) ne serait de toute façon jamais reproposé par
    `prochain_disponible` — la purge ne cible que `disponible`, elle ne
    réécrit jamais un historique de consommation réelle."""
    chemin_db = tmp_path / "cache.db"
    conn = creer_connexion(chemin_db)
    conn.execute(
        "INSERT INTO numeros_reserves (type_facture, numero, statut)"
        " VALUES ('usine', 5, 'utilise')")
    conn.commit()
    conn.close()

    conn = creer_connexion(chemin_db)
    row = conn.execute("SELECT numero FROM numeros_reserves WHERE numero = 5").fetchone()
    assert row is not None
