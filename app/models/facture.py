"""Entité Facture."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.vente import LigneVente


@dataclass
class Facture:
    """Facture client : numéro continu, date, destination et lignes de vente."""

    id: int | None = None
    numero: int = 0            # numérotation continue (jamais de remise à zéro annuelle)
    date_facture: date = field(default_factory=date.today)
    client_id: int | None = None
    client_nom: str = ""       # dénormalisé pour affichage/PDF
    destination: str = ""
    telephone: str = ""        # téléphone du client, dénormalisé (affichage/PDF)
    matricule: str = ""        # matricule du véhicule de livraison, saisi librement
    etabli_par: str = ""
    archivee: bool = False     # masquée de l'historique des ventes (n'affecte pas les stats)
    remise_taux: float = 0.0   # % appliqué à CETTE facture (0 = aucune remise)
    remise_modifiee_par: str = ""  # 'role_principal' | 'role_client' | 'local' — traçabilité
    remise_modifiee_le: str = ""   # ISO datetime de la dernière modification de remise_taux
    tva_taux: float = 0.0      # % de TVA appliqué — toujours config.TVA_TAUX_DEFAUT, non modifiable
    lignes: list[LigneVente] = field(default_factory=list)
    # Champs agrégés remplis par FactureRepository.lister() (affichage liste)
    total_liste: int = 0
    nb_lignes: int = 0

    @property
    def total(self) -> int:
        """Total brut de la facture (marchandise) : somme des totaux de lignes,
        avant remise (formule Excel SUM)."""
        return sum(ligne.total for ligne in self.lignes)

    @property
    def remise_montant(self) -> int:
        """Montant de la remise appliquée à cette facture, en FCFA."""
        return round(self.total * self.remise_taux / 100) if self.remise_taux else 0

    @property
    def total_net(self) -> int:
        """Total réellement facturé (après remise) — c'est le montant dû."""
        return self.total - self.remise_montant

    @property
    def tva_montant(self) -> int:
        """Montant de la TVA, prélevé SUR le total net (après remise) — la
        TVA ne s'ajoute jamais en plus de ce que le client doit payer :
        c'est nous qui la reversons sur ce montant, jamais le client qui
        paie un supplément. `total_net` reste donc le montant réellement dû
        que la TVA soit active ou non (voir `total_ttc`)."""
        return round(self.total_net * self.tva_taux / 100) if self.tva_taux else 0

    @property
    def total_ht(self) -> int:
        """Total hors taxe : le total net diminué de la TVA qui y est
        incluse (jamais ajoutée en plus)."""
        return self.total_net - self.tva_montant

    @property
    def total_ttc(self) -> int:
        """Total toutes taxes comprises = total net (le montant réellement
        facturé au client ne change pas selon que la TVA soit activée ou
        non — seule sa décomposition HT/TVA affichée sur le PDF change)."""
        return self.total_net
