"""État local (machine de facturation) de l'algorithme de numérotation
résiliente — un seul enregistrement (id=1) dans `etat_numerotation`. Voir
CLAUDE.md, section « Numérotation résiliente »."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.repositories.base_repository import BaseRepository

# Palier 1 → palier 2 : durée d'échec soutenu du poller de fond (pas un
# simple ralentissement isolé) avant de considérer la coupure comme réelle
# et de déclencher le pool de secours (voir CLAUDE.md, « Numérotation
# résiliente »).
_SEUIL_COUPURE_SECONDES = 25


@dataclass
class EtatNumerotation:
    """`base_connu` : plus haut numéro de facture jamais vu localement
    (appris au fil des réservations réussies). `n_connu`/`rang_connu` :
    dernières valeurs communiquées par le boss. `prochain_k` : prochain bloc
    à calculer localement (palier 3), jamais rejoué deux fois.
    `dernier_poll_reussi` : horodatage ISO UTC du dernier sondage réussi du
    poller de fond (palier 1) — chaîne vide tant qu'aucun sondage n'a encore
    réussi."""

    base_connu: int
    n_connu: int
    rang_connu: int
    prochain_k: int
    dernier_poll_reussi: str = ""


class EtatNumerotationRepository(BaseRepository):
    """Lecture/écriture de `etat_numerotation` (cache de la machine de
    facturation uniquement)."""

    def _assurer_ligne(self) -> None:
        self.conn.execute(
            "INSERT INTO etat_numerotation (id, base_connu, n_connu, rang_connu, prochain_k)"
            " VALUES (1, 0, 1, 0, 0)"
            " ON CONFLICT (id) DO NOTHING"
        )
        self.conn.commit()

    def lire(self) -> EtatNumerotation:
        self._assurer_ligne()
        row = self.conn.execute(
            "SELECT * FROM etat_numerotation WHERE id = 1"
        ).fetchone()
        return EtatNumerotation(
            base_connu=row["base_connu"], n_connu=row["n_connu"],
            rang_connu=row["rang_connu"], prochain_k=row["prochain_k"],
            dernier_poll_reussi=row["dernier_poll_reussi"] or "")

    def marquer_poll_reussi(self) -> None:
        """Appelé par `NumeroPollerWorker` après chaque sondage réussi du
        palier 1 — réinitialise le compteur de coupure soutenue."""
        self._assurer_ligne()
        self.conn.execute(
            "UPDATE etat_numerotation SET dernier_poll_reussi = ? WHERE id = 1",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self.conn.commit()

    def coupure_soutenue(self, seuil_secondes: int = _SEUIL_COUPURE_SECONDES) -> bool:
        """Vrai si le poller de fond (palier 1) n'a réussi aucun sondage
        depuis au moins `seuil_secondes` — signe d'une vraie coupure réseau,
        pas d'un simple ralentissement isolé. Vrai également si aucun sondage
        n'a JAMAIS réussi (ex. démarrage sans serveur joignable)."""
        etat = self.lire()
        if not etat.dernier_poll_reussi:
            return True
        try:
            dernier = datetime.fromisoformat(etat.dernier_poll_reussi)
        except ValueError:
            return True
        if dernier.tzinfo is None:
            dernier = dernier.replace(tzinfo=timezone.utc)
        ecoule = (datetime.now(timezone.utc) - dernier).total_seconds()
        return ecoule >= seuil_secondes

    def definir_base_si_superieur(self, numero: int) -> None:
        """Ne fait jamais reculer `base_connu` — toujours le plus haut
        numéro jamais vu localement."""
        self._assurer_ligne()
        self.conn.execute(
            "UPDATE etat_numerotation SET base_connu = ?"
            " WHERE id = 1 AND base_connu < ?",
            (numero, numero),
        )
        self.conn.commit()

    def definir_n_rang(self, n: int, rang: int) -> None:
        self._assurer_ligne()
        self.conn.execute(
            "UPDATE etat_numerotation SET n_connu = ?, rang_connu = ? WHERE id = 1",
            (n, rang),
        )
        self.conn.commit()

    def consommer_prochain_k(self) -> int:
        """Retourne le `k` à utiliser pour le prochain bloc déterministe
        (palier 3), puis l'avance — jamais rejoué deux fois."""
        etat = self.lire()
        self.conn.execute(
            "UPDATE etat_numerotation SET prochain_k = prochain_k + 1 WHERE id = 1"
        )
        self.conn.commit()
        return etat.prochain_k
