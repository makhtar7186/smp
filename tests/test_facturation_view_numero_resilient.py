"""Test de non-régression : numérotation résiliente, palier 1 final (voir
CLAUDE.md, section « Numérotation résiliente ») — suggestion instantanée
(`suggerer_numero`, sans réseau, jamais de popup) à l'ouverture d'un panier
neuf, puis confirmation silencieuse (`confirmer_numero`) juste avant
l'écriture réelle. Ne se déclenche que sur la machine de facturation
(`numero_resilient` présent), jamais sur le boss. Une correction manuelle du
champ numéro n'est jamais écrasée par la confirmation."""
from __future__ import annotations

import tkinter as tk
from datetime import date

import pytest

from app.models import LigneVente
from app.services.facturation_service import FacturationService
from app.services.pdf_service import PdfService
from app.services.proforma_service import ProformaService
from app.ui import theme
from app.ui.views.facturation_view import FacturationView


class _FauxNumeroResilient:
    def __init__(self, suggestions: list[int]) -> None:
        self._suggestions = list(suggestions)
        self.appels_suggestion = 0
        self.appels_confirmation = 0
        self.derniere_confirmation: int | None = None
        self.numero_confirme: int | None = None

    def suggerer_numero(self) -> int:
        self.appels_suggestion += 1
        return self._suggestions.pop(0)

    def confirmer_numero(self, numero_suggere: int) -> int:
        self.appels_confirmation += 1
        self.derniere_confirmation = numero_suggere
        return self.numero_confirme if self.numero_confirme is not None else numero_suggere


class _FauxApplication:
    pass


@pytest.fixture()
def vue_offline(conn, tmp_path):
    application = _FauxApplication()
    application.conn = conn
    application.facturation = FacturationService(conn)
    application.proformas = ProformaService(conn, application.facturation)
    application.pdf = PdfService(tmp_path)
    application.numero_resilient = _FauxNumeroResilient([777, 778, 779])

    root = tk.Tk()
    root.withdraw()
    theme.appliquer_theme(root)
    vue = FacturationView(root, application)
    yield vue, application
    root.destroy()


def test_suggestion_instantanee_sans_popup(vue_offline) -> None:
    vue, application = vue_offline
    vue.rafraichir()
    assert vue.var_numero.get() == "777"
    assert application.numero_resilient.appels_suggestion == 1


def test_numero_deja_affecte_ne_redeclenche_pas_la_suggestion(vue_offline) -> None:
    vue, application = vue_offline
    vue.var_numero.set("999")
    vue.rafraichir()
    assert vue.var_numero.get() == "999"
    assert application.numero_resilient.appels_suggestion == 0


def test_nouvelle_facture_redemande_silencieusement(vue_offline) -> None:
    vue, application = vue_offline
    vue.rafraichir()
    assert vue.var_numero.get() == "777"

    vue._reinitialiser_panier()
    assert vue.var_numero.get() == "778"
    assert application.numero_resilient.appels_suggestion == 2


def test_enregistrement_confirme_silencieusement_le_numero_suggere(vue_offline) -> None:
    vue, application = vue_offline
    vue.rafraichir()
    assert vue.var_numero.get() == "777"

    vue.var_client.set("Client X")
    vue._lignes.append(LigneVente(designation="ART", quantite=1, prix_unitaire=1000))
    vue._enregistrer()

    assert application.numero_resilient.appels_confirmation == 1
    assert application.numero_resilient.derniere_confirmation == 777
    assert application.facturation.numero_existe(777)


def test_confirmation_ajuste_silencieusement_si_le_serveur_renvoie_autre_chose(
    vue_offline,
) -> None:
    vue, application = vue_offline
    vue.rafraichir()
    assert vue.var_numero.get() == "777"
    application.numero_resilient.numero_confirme = 780  # collision détectée côté serveur

    vue.var_client.set("Client X")
    vue._lignes.append(LigneVente(designation="ART", quantite=1, prix_unitaire=1000))
    vue._enregistrer()

    assert application.facturation.numero_existe(780)
    assert not application.facturation.numero_existe(777)


def test_numero_modifie_manuellement_n_est_jamais_ecrase(vue_offline) -> None:
    vue, application = vue_offline
    vue.rafraichir()
    assert vue.var_numero.get() == "777"
    vue.var_numero.set("42")  # correction manuelle, s'écarte de la suggestion

    vue.var_client.set("Client X")
    vue._lignes.append(LigneVente(designation="ART", quantite=1, prix_unitaire=1000))
    vue._enregistrer()

    assert application.numero_resilient.appels_confirmation == 0
    assert application.facturation.numero_existe(42)


def test_edition_facture_existante_ne_confirme_jamais(vue_offline) -> None:
    vue, application = vue_offline
    facture = application.facturation.enregistrer_facture(
        numero=500, date_facture=date(2026, 8, 11), nom_client="A", destination="X",
        lignes=[LigneVente(designation="ART", quantite=1, prix_unitaire=1000)])
    vue.charger_pour_edition(application.facturation.obtenir_facture(facture.id))

    vue._enregistrer()

    assert application.numero_resilient.appels_confirmation == 0
