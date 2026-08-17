"""Test de non-régression : la vérification de stock lors de la correction
d'une facture déjà enregistrée doit créditer la quantité que CETTE facture
avait déjà sortie du stock — sans quoi toute correction à la baisse d'une
facture ayant vidé le stock serait refusée à tort (voir CLAUDE.md, « Gestion
de stock »). Exemple : facture de 100 plats, stock actuel à 2 après cette
vente ; corriger à 50 (retour de 50 articles) doit être accepté car
50 <= 2 + 100, pas comparé aux 2 seuls en stock."""
from __future__ import annotations

import tkinter as tk
from datetime import date

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService
from app.services.proforma_service import ProformaService
from app.services.stock_service import StockService
from app.ui import theme
from app.ui.views.facturation_view import FacturationView


class _FauxApplication:
    pass


@pytest.fixture()
def vue(conn, tmp_path):
    application = _FauxApplication()
    application.conn = conn
    application.facturation = FacturationService(conn)
    application.proformas = ProformaService(conn, application.facturation)
    application.pdf = PdfService(tmp_path)

    root = tk.Tk()
    root.withdraw()
    theme.appliquer_theme(root)
    vue = FacturationView(root, application)
    vue.rafraichir()
    yield vue, application
    root.destroy()


def _editer_premiere_ligne(vue, produit, quantite: str) -> None:
    """Simule le chargement de la première ligne du panier dans le
    formulaire (comme `_editer_ligne` après une sélection dans le tableau)
    puis la validation du formulaire (`_ajouter_ligne`, en mode édition)."""
    vue._indice_edition = 0
    vue._produit_choisi_id = produit.id
    vue.var_designation.set(produit.designation)
    vue.var_quantite.set(quantite)
    vue.var_prix.set(str(produit.prix))
    vue._ajouter_ligne()


def test_correction_a_la_baisse_creditee_par_la_quantite_deja_sortie(vue):
    vue, application = vue
    stock = StockService(application.conn)
    produit = stock.creer_produit("PLAT", prix=1000)
    stock.entrer_stock(produit.id, 102)

    facture = application.facturation.enregistrer_facture(
        numero=1, date_facture=date(2026, 8, 7), nom_client="X", destination="Y",
        lignes=[LigneVente(produit_id=produit.id, designation="PLAT",
                           quantite=100, prix_unitaire=1000)])
    assert stock.lister_produits()[0].quantite_stock == 2

    vue.charger_pour_edition(application.facturation.obtenir_facture(facture.id))
    _editer_premiere_ligne(vue, produit, "50")

    assert vue._erreur_ligne.get() == ""
    assert vue._lignes[0].quantite == 50


def test_correction_au_dela_du_credit_disponible_refusee(vue):
    vue, application = vue
    stock = StockService(application.conn)
    produit = stock.creer_produit("PLAT", prix=1000)
    stock.entrer_stock(produit.id, 102)

    facture = application.facturation.enregistrer_facture(
        numero=1, date_facture=date(2026, 8, 7), nom_client="X", destination="Y",
        lignes=[LigneVente(produit_id=produit.id, designation="PLAT",
                           quantite=100, prix_unitaire=1000)])

    vue.charger_pour_edition(application.facturation.obtenir_facture(facture.id))
    _editer_premiere_ligne(vue, produit, "103")  # 103 > 2 (stock) + 100 (déjà sorti)

    assert vue._erreur_ligne.get() != ""
    assert vue._lignes[0].quantite == 100  # ligne inchangée, correction refusée


def test_nouvelle_facture_n_a_aucun_credit(vue):
    """Sans édition d'une facture existante, aucune quantité originale à
    créditer : le contrôle reste le stock physique nu."""
    vue, application = vue
    stock = StockService(application.conn)
    produit = stock.creer_produit("PLAT", prix=1000)
    stock.entrer_stock(produit.id, 5)

    vue._produit_choisi_id = produit.id
    vue.var_designation.set(produit.designation)
    vue.var_quantite.set("10")
    vue.var_prix.set("1000")
    vue._ajouter_ligne()

    assert vue._erreur_ligne.get() != ""
    assert vue._lignes == []
