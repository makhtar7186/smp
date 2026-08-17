"""Entité Proforma : brouillon de facture sans numéro."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models.vente import LigneVente


@dataclass
class Proforma:
    """Brouillon de facture usine, sans numéro tant qu'il n'est pas validé.

    À la validation (`ProformaService.valider`), il devient une `Facture`
    usine à part entière — numéro attribué à ce moment-là — et le brouillon
    est supprimé : il ne subsiste plus que sous forme de facture."""

    id: int | None = None
    date_creation: date = field(default_factory=date.today)
    client_nom: str = ""
    destination: str = ""
    telephone: str = ""  # téléphone du client, dénormalisé (comme sur Facture)
    matricule: str = ""  # matricule du véhicule de livraison, saisi librement
    etabli_par: str = ""
    remise_taux: float = 0.0
    lignes: list[LigneVente] = field(default_factory=list)
    # Champs agrégés remplis par ProformaRepository.lister() (affichage liste)
    total_liste: int = 0
    nb_lignes: int = 0

    @property
    def total(self) -> int:
        return sum(ligne.total for ligne in self.lignes)

    @property
    def remise_montant(self) -> int:
        return round(self.total * self.remise_taux / 100) if self.remise_taux else 0

    @property
    def total_net(self) -> int:
        return self.total - self.remise_montant

    # TVA — un brouillon affiche désormais le même détail HT/TVA/TTC qu'une
    # facture réelle (voir CLAUDE.md, section « TVA obligatoire »), calculé
    # dynamiquement (jamais stocké : un brouillon n'est jamais figé) plutôt
    # que persisté comme `Facture.tva_taux`. Import différé pour éviter un
    # cycle (même idiome que `facturation_service.py._preparer_facture`).
    @property
    def tva_taux(self) -> float:
        from app import config
        return config.TVA_TAUX_DEFAUT

    @property
    def tva_montant(self) -> int:
        """Montant de la TVA, prélevé SUR le total net — voir
        `Facture.tva_montant` pour le raisonnement complet."""
        return round(self.total_net * self.tva_taux / 100) if self.tva_taux else 0

    @property
    def total_ht(self) -> int:
        return self.total_net - self.tva_montant

    @property
    def total_ttc(self) -> int:
        return self.total_net
