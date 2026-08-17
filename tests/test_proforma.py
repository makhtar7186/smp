"""Tests des brouillons de facture (proforma) : création, modification,
validation (conversion en facture numérotée) et suppression."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.proforma_service import ProformaService
from app.utils.validation import ErreurValidation


def _ligne(quantite: int = 2, prix: int = 10000) -> LigneVente:
    return LigneVente(designation="SM TAPISSIER 140X190X",
                      quantite=quantite, prix_unitaire=prix)


@pytest.fixture()
def services(conn):
    facturation = FacturationService(conn)
    return facturation, ProformaService(conn, facturation)


class TestCreationEtModification:
    def test_enregistrer_sans_numero(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne()])
        assert proforma.id is not None
        assert proforma.total == 20000
        assert not hasattr(proforma, "numero")  # jamais de numéro sur un brouillon

    def test_client_requis(self, services):
        _, proformas = services
        with pytest.raises(ErreurValidation):
            proformas.enregistrer(client_nom="", destination="DAKAR", lignes=[_ligne()])

    def test_panier_vide_refuse(self, services):
        _, proformas = services
        with pytest.raises(ErreurValidation):
            proformas.enregistrer(client_nom="TEST", destination="DAKAR", lignes=[])

    def test_modifier_remplace_lignes(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne(2, 10000)])
        modifie = proformas.modifier(
            proforma.id, client_nom="TEST", destination="DAKAR",
            lignes=[_ligne(3, 10000), _ligne(1, 5000)])
        assert modifie.total == 35000
        relu = proformas.obtenir(proforma.id)
        assert len(relu.lignes) == 2
        assert relu.total == 35000

    def test_telephone_et_matricule_persistes(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne()],
            telephone="77 000 00 00", matricule="DK-1234-A")
        relu = proformas.obtenir(proforma.id)
        assert relu.telephone == "77 000 00 00"
        assert relu.matricule == "DK-1234-A"


class TestTva:
    """Un brouillon affiche désormais le même détail TVA qu'une facture
    réelle (voir CLAUDE.md, section « TVA obligatoire »)."""

    def test_tva_toujours_calculee(self, services):
        from app import config
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne(2, 10000)])
        assert proforma.tva_taux == config.TVA_TAUX_DEFAUT
        assert proforma.total_ttc == proforma.total_net == 20000
        assert proforma.tva_montant == round(20000 * config.TVA_TAUX_DEFAUT / 100)
        assert proforma.total_ht == proforma.total_net - proforma.tva_montant

    def test_tva_prelevee_apres_remise(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne(2, 10000)],
            remise_taux=10.0)
        assert proforma.total_net == 18000
        assert proforma.total_ttc == 18000  # la TVA ne s'ajoute jamais en plus


class TestListeEtSuppression:
    def test_lister_vide(self, services):
        _, proformas = services
        assert proformas.lister() == []

    def test_lister_retourne_totaux_agreges(self, services):
        _, proformas = services
        proformas.enregistrer(client_nom="A", destination="DAKAR",
                              lignes=[_ligne(2, 10000)])
        proformas.enregistrer(client_nom="B", destination="THIES",
                              lignes=[_ligne(1, 5000)])
        liste = proformas.lister()
        assert len(liste) == 2
        totaux = {p.client_nom: p.total_liste for p in liste}
        assert totaux == {"A": 20000, "B": 5000}

    def test_supprimer(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne()])
        proformas.supprimer(proforma.id)
        assert proformas.obtenir(proforma.id) is None


class TestValidation:
    def test_valider_cree_facture_numerotee(self, services):
        facturation, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne(2, 10000)])
        facture = proformas.valider(proforma.id, 260001, date(2026, 7, 29))
        assert facture.id is not None
        assert facture.numero == 260001
        assert facture.total == 20000

    def test_valider_supprime_le_brouillon(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne()])
        proformas.valider(proforma.id, 260001, date(2026, 7, 29))
        assert proformas.obtenir(proforma.id) is None

    def test_facture_validee_apparait_dans_historique(self, services):
        facturation, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne()])
        facture = proformas.valider(proforma.id, 260001, date(2026, 7, 29))
        historique = facturation.lister_factures()
        assert any(f.id == facture.id for f in historique)

    def test_valider_brouillon_inexistant(self, services):
        _, proformas = services
        with pytest.raises(ErreurValidation):
            proformas.valider(9999, 260001, date(2026, 7, 29))

    def test_valider_conserve_remise(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne(2, 10000)],
            remise_taux=10.0)
        facture = proformas.valider(proforma.id, 260001, date(2026, 7, 29))
        assert facture.remise_taux == 10.0
        assert facture.total_net == 18000

    def test_valider_propage_telephone_et_matricule(self, services):
        _, proformas = services
        proforma = proformas.enregistrer(
            client_nom="TEST", destination="DAKAR", lignes=[_ligne()],
            telephone="77 000 00 00", matricule="DK-1234-A")
        facture = proformas.valider(proforma.id, 260001, date(2026, 7, 29))
        assert facture.telephone == "77 000 00 00"
        assert facture.matricule == "DK-1234-A"
