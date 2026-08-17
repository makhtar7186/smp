"""Test de non-régression : enregistrer une facture réelle à partir d'un
panier déjà sauvegardé comme brouillon ne doit PAS supprimer ce brouillon
(bug signalé : le brouillon disparaissait automatiquement de la page
Proforma dès qu'on cliquait « Enregistrer » sur le même panier)."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService
from app.services.proforma_service import ProformaService
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


def _ligne() -> LigneVente:
    return LigneVente(designation="SM TAPISSIER 140X190X", 
                      quantite=2, prix_unitaire=10000)


def test_facturer_un_brouillon_ne_le_supprime_pas(vue):
    vue, application = vue
    vue._lignes = [_ligne()]
    vue.var_client.set("CLIENT A")
    vue.var_destination.set("DAKAR")
    vue._redessiner_panier()
    vue._maj_total()

    vue._enregistrer_brouillon()
    assert len(application.proformas.lister()) == 1

    vue._enregistrer()  # facture usine, à partir du même panier

    assert len(application.proformas.lister()) == 1, (
        "le brouillon ne doit pas être supprimé par un enregistrement direct")
    assert len(application.facturation.lister_factures()) == 1
    # Le panier n'est plus rattaché au brouillon : un futur « Enregistrer en
    # brouillon » recréerait un nouveau brouillon plutôt que de modifier
    # silencieusement celui déjà existant.
    assert vue._edition_proforma_id is None
