"""Tests du service PDF : facture, bordereau, et facture proforma (brouillon)."""
from __future__ import annotations

from datetime import date

from app.models import Facture, LigneVente, Proforma
from app.services.pdf_service import PdfService


def _ligne() -> LigneVente:
    return LigneVente(designation="SM TAPISSIER 140X190X", 
                      quantite=2, prix_unitaire=10000)


def test_generer_facture(tmp_path):
    pdf = PdfService(tmp_path)
    facture = Facture(numero=260001, date_facture=date(2026, 7, 29),
                      client_nom="TEST", destination="DAKAR", lignes=[_ligne()])
    chemin = pdf.generer_facture(facture)
    assert chemin.exists()
    assert chemin.name == "FACTURE_260001.pdf"


def test_generer_bordereau(tmp_path):
    pdf = PdfService(tmp_path)
    facture = Facture(numero=260001, date_facture=date(2026, 7, 29),
                      client_nom="TEST", destination="DAKAR", lignes=[_ligne()])
    chemin = pdf.generer_bordereau(facture)
    assert chemin.exists()
    assert chemin.name == "BORDEREAU_260001.pdf"


def test_generer_proforma_sans_numero(tmp_path):
    """Une facture proforma n'a pas de numéro — le PDF doit se générer quand
    même, avec un nom de fichier basé sur l'id du brouillon."""
    pdf = PdfService(tmp_path)
    proforma = Proforma(id=7, client_nom="TEST", destination="DAKAR",
                        lignes=[_ligne()])
    chemin = pdf.generer_proforma(proforma)
    assert chemin.exists()
    assert chemin.name == "PROFORMA_7.pdf"


def test_generer_proforma_avec_remise(tmp_path):
    pdf = PdfService(tmp_path)
    proforma = Proforma(id=1, client_nom="TEST", destination="DAKAR",
                        lignes=[_ligne()], remise_taux=10.0)
    chemin = pdf.generer_proforma(proforma)
    assert chemin.exists()


def test_generer_facture_avec_telephone_et_matricule(tmp_path):
    """Téléphone (toujours affiché) et matricule (seulement si renseigné)
    sur facture et bordereau — voir CLAUDE.md, section « Téléphone et
    matricule »."""
    pdf = PdfService(tmp_path)
    facture = Facture(numero=260002, date_facture=date(2026, 7, 29),
                      client_nom="TEST", destination="DAKAR",
                      telephone="77 000 00 00", matricule="DK-1234-A",
                      lignes=[_ligne()])
    assert pdf.generer_facture(facture).exists()
    assert pdf.generer_bordereau(facture).exists()


def test_generer_facture_sans_matricule(tmp_path):
    """Matricule vide (livraison sans véhicule identifié) : ne doit pas
    faire échouer la génération."""
    pdf = PdfService(tmp_path)
    facture = Facture(numero=260003, date_facture=date(2026, 7, 29),
                      client_nom="TEST", destination="DAKAR",
                      telephone="77 000 00 00", lignes=[_ligne()])
    assert pdf.generer_facture(facture).exists()


def test_generer_facture_beaucoup_de_lignes(tmp_path):
    """Facture forçant un saut de page (voir le seuil élargi dans
    `_tableau_lignes`, qui doit laisser assez de place pour le total, la
    mention en lettres et le bloc cachet/signature sans les faire déborder
    hors marge)."""
    pdf = PdfService(tmp_path)
    lignes = [_ligne() for _ in range(60)]
    facture = Facture(numero=260004, date_facture=date(2026, 7, 29),
                      client_nom="TEST", destination="DAKAR",
                      remise_taux=10.0, lignes=lignes)
    chemin = pdf.generer_facture(facture)
    assert chemin.exists()


def test_generer_proforma_montant_en_lettres_montant_nul(tmp_path):
    """Un brouillon sans ligne valorisée (total 0) ne doit pas faire planter
    la conversion en toutes lettres."""
    pdf = PdfService(tmp_path)
    proforma = Proforma(id=2, client_nom="TEST", destination="DAKAR",
                        lignes=[LigneVente(designation="X", quantite=1,
                                           prix_unitaire=0)])
    assert pdf.generer_proforma(proforma).exists()
