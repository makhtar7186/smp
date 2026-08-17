"""Tests du convertisseur nombre → lettres françaises (mention légale PDF)."""
from app.utils.nombre_lettres import nombre_en_lettres_fr


def test_zero():
    assert nombre_en_lettres_fr(0) == "zéro"


def test_unites_et_dizaines():
    assert nombre_en_lettres_fr(1) == "un"
    assert nombre_en_lettres_fr(11) == "onze"
    assert nombre_en_lettres_fr(21) == "vingt et un"
    assert nombre_en_lettres_fr(71) == "soixante et onze"
    assert nombre_en_lettres_fr(80) == "quatre-vingts"
    assert nombre_en_lettres_fr(81) == "quatre-vingt-un"
    assert nombre_en_lettres_fr(91) == "quatre-vingt-onze"


def test_centaines():
    assert nombre_en_lettres_fr(100) == "cent"
    assert nombre_en_lettres_fr(200) == "deux cents"
    assert nombre_en_lettres_fr(201) == "deux cent un"


def test_milliers():
    assert nombre_en_lettres_fr(1000) == "mille"
    assert nombre_en_lettres_fr(1001) == "mille un"
    assert nombre_en_lettres_fr(2000) == "deux mille"


def test_nombre_compose():
    assert nombre_en_lettres_fr(123456) == "cent vingt-trois mille quatre cent cinquante-six"


def test_million():
    assert nombre_en_lettres_fr(1_000_000) == "un million"
    assert nombre_en_lettres_fr(2_000_000) == "deux millions"


def test_montant_fcfa_realiste():
    assert nombre_en_lettres_fr(141_300) == "cent quarante et un mille trois cents"


def test_negatif():
    assert nombre_en_lettres_fr(-5) == "moins cinq"
