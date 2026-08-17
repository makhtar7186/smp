"""Registre (boss) de la dernière activité connue de chaque machine de
facturation — alimenté par le heartbeat porté sur le canal de synchro
descendante déjà existant (référentiels), jamais une requête dédiée. Sert à
déterminer N (nombre de postes actifs) et le rang de chacun pour le calcul
déterministe de repli hors ligne. Voir CLAUDE.md, section « Numérotation
résiliente »."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.repositories.base_repository import BaseRepository
from app.utils.formatting import horodatage_sql

_FENETRE_ACTIVITE_SECONDES = 60  # un poste sans requête depuis ce délai est inactif


class MachineActiviteRepository(BaseRepository):
    """Lecture/écriture de `machines_actives` (boss uniquement)."""

    def toucher(self, machine_id: str) -> None:
        """Enregistre une activité de `machine_id` à l'instant présent — sans
        effet si `machine_id` est vide (poste non identifié, ex. jeton
        partagé sans en-tête X-Machine-Id)."""
        if not machine_id:
            return
        self.conn.execute(
            "INSERT INTO machines_actives (machine_id, dernier_vu) VALUES (?, ?)"
            " ON CONFLICT (machine_id) DO UPDATE SET dernier_vu = excluded.dernier_vu",
            (machine_id, horodatage_sql()),
        )
        self.conn.commit()

    def machines_actives_triees(
        self, fenetre_secondes: int = _FENETRE_ACTIVITE_SECONDES,
    ) -> list[str]:
        """`machine_id` vus dans la fenêtre d'activité, triés par ordre
        alphabétique — ordre déterministe servant de base à l'attribution du
        rang (le filtrage par fenêtre est fait en Python plutôt qu'en SQL
        pour rester portable SQLite/PostgreSQL, voir CLAUDE.md, « Bascule
        PostgreSQL »)."""
        limite = datetime.utcnow() - timedelta(seconds=fenetre_secondes)
        rows = self.conn.execute(
            "SELECT machine_id, dernier_vu FROM machines_actives"
        ).fetchall()
        actifs = [
            r["machine_id"] for r in rows
            if r["machine_id"] and _vers_datetime(r["dernier_vu"]) >= limite
        ]
        return sorted(actifs)

    def info_activite(
        self, machine_id: str, fenetre_secondes: int = _FENETRE_ACTIVITE_SECONDES,
    ) -> tuple[int, int]:
        """Enregistre l'activité de `machine_id` puis retourne `(n, rang)` :
        `n` = nombre de postes actifs (ce poste inclus), `rang` = position de
        `machine_id` dans la liste triée (0 si vide/absent — dégrade
        proprement la formule du palier 3 au cas contigu classique)."""
        self.toucher(machine_id)
        actifs = self.machines_actives_triees(fenetre_secondes)
        n = max(len(actifs), 1)
        rang = actifs.index(machine_id) if machine_id in actifs else 0
        return n, rang


def _vers_datetime(horodatage: str) -> datetime:
    return datetime.strptime(horodatage, "%Y-%m-%d %H:%M:%S")
