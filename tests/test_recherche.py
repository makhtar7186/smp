"""Tests de l'utilitaire de recherche multi-termes (app.utils.recherche)."""
from __future__ import annotations

from app.utils.recherche import correspond, decouper_termes


class TestDecouperTermes:
    def test_terme_unique(self):
        assert decouper_termes("ALPHA") == ["alpha"]

    def test_plusieurs_termes(self):
        assert decouper_termes("ALPHA, BETA,  Gamma ") == ["alpha", "beta", "gamma"]

    def test_chaine_vide(self):
        assert decouper_termes("") == []

    def test_virgules_superflues(self):
        assert decouper_termes(",, ALPHA ,,") == ["alpha"]


class TestCorrespond:
    def test_aucun_terme_ne_correspond_jamais(self):
        assert correspond("ALPHA", []) is False

    def test_un_terme_correspondant(self):
        assert correspond("ALPHA DUPONT", ["dupont"]) is True

    def test_logique_ou_entre_les_termes(self):
        assert correspond("BETA", ["alpha", "beta"]) is True
        assert correspond("GAMMA", ["alpha", "beta"]) is False

    def test_insensible_a_la_casse(self):
        assert correspond("Dakar", ["DAKAR"]) is True

    def test_valeur_vide_ou_none(self):
        assert correspond("", ["alpha"]) is False
