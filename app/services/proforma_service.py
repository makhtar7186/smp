"""Service des brouillons de facture (proforma) : création, modification,
validation (conversion en facture usine numérotée) et suppression."""
from __future__ import annotations

import sqlite3
from datetime import date

from app.models import Facture, LigneVente, Proforma
from app.repositories.proforma_repository import ProformaRepository
from app.services.facturation_service import FacturationService
from app.utils.validation import ErreurValidation


class ProformaService:
    """Un brouillon n'a jamais de numéro : il n'en reçoit un qu'au moment de
    sa validation (`valider`), où il devient une facture usine à part
    entière et cesse d'exister comme brouillon."""

    def __init__(self, conn: sqlite3.Connection, facturation: FacturationService) -> None:
        self._proformas = ProformaRepository(conn)
        self._facturation = facturation

    def enregistrer(
        self,
        client_nom: str,
        destination: str,
        lignes: list[LigneVente],
        etabli_par: str = "",
        remise_taux: float = 0.0,
        date_creation: date | None = None,
        telephone: str = "",
        matricule: str = "",
    ) -> Proforma:
        """Valide et enregistre un NOUVEAU brouillon (toujours une insertion)."""
        proforma = self._preparer(client_nom, destination, lignes, etabli_par,
                                  remise_taux, date_creation, telephone, matricule)
        return self._proformas.enregistrer(proforma)

    def modifier(
        self,
        proforma_id: int,
        client_nom: str,
        destination: str,
        lignes: list[LigneVente],
        etabli_par: str = "",
        remise_taux: float = 0.0,
        date_creation: date | None = None,
        telephone: str = "",
        matricule: str = "",
    ) -> Proforma:
        """Corrige un brouillon déjà enregistré (même validations que la
        création) : en-tête et lignes intégralement remplacés."""
        proforma = self._preparer(client_nom, destination, lignes, etabli_par,
                                  remise_taux, date_creation, telephone, matricule)
        proforma.id = proforma_id
        return self._proformas.modifier(proforma)

    def _preparer(
        self,
        client_nom: str,
        destination: str,
        lignes: list[LigneVente],
        etabli_par: str,
        remise_taux: float,
        date_creation: date | None,
        telephone: str = "",
        matricule: str = "",
    ) -> Proforma:
        client_nom = str(client_nom or "").strip()
        if not client_nom:
            raise ErreurValidation("fact_client_requis")
        if not lignes:
            raise ErreurValidation("fact_panier_vide")
        if not 0 <= remise_taux <= 100:
            raise ErreurValidation("fact_remise_invalide")
        for ligne in lignes:
            self._facturation.valider_ligne(ligne)
        return Proforma(
            date_creation=date_creation or date.today(),
            client_nom=client_nom, destination=destination.strip(),
            telephone=telephone.strip(), matricule=matricule.strip(),
            etabli_par=etabli_par.strip(), remise_taux=remise_taux, lignes=lignes,
        )

    # Consultation ------------------------------------------------------------
    def obtenir(self, proforma_id: int) -> Proforma | None:
        return self._proformas.obtenir(proforma_id)

    def lister(self) -> list[Proforma]:
        return self._proformas.lister()

    def supprimer(self, proforma_id: int) -> None:
        self._proformas.supprimer(proforma_id)

    # Validation ----------------------------------------------------------------
    def valider(self, proforma_id: int, numero: int, date_facture: date) -> Facture:
        """Convertit le brouillon en facture usine numérotée, puis le
        supprime : il ne subsiste plus que sous forme de facture."""
        proforma = self._proformas.obtenir(proforma_id)
        if proforma is None:
            raise ErreurValidation("proforma_introuvable")
        lignes = [
            LigneVente(
                designation=ligne.designation,
                quantite=ligne.quantite, prix_unitaire=ligne.prix_unitaire,
                remarque=ligne.remarque,
            )
            for ligne in proforma.lignes
        ]
        facture = self._facturation.enregistrer_facture(
            numero=numero, date_facture=date_facture, nom_client=proforma.client_nom,
            destination=proforma.destination, lignes=lignes,
            etabli_par=proforma.etabli_par,
            remise_taux=proforma.remise_taux,
            telephone=proforma.telephone,
            matricule=proforma.matricule,
        )
        self._proformas.supprimer(proforma_id)
        return facture
