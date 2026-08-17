"""Tests du mode hors ligne de l'app Stock : cache local du catalogue
(`app.stock.cache_catalogue`) et file d'attente locale des mouvements de
stock saisis hors ligne (`app.stock.queue_hors_ligne`) — voir CLAUDE.md,
section « App Stock — mode hors ligne »."""
from __future__ import annotations

from app.stock import cache_catalogue, queue_hors_ligne


class TestCacheCatalogue:
    def test_vide_par_defaut(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_catalogue, "CHEMIN_CACHE_CATALOGUE",
                            tmp_path / "cache.json")
        produits, horodatage = cache_catalogue.charger()
        assert produits == []
        assert horodatage == ""

    def test_sauvegarder_puis_charger(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_catalogue, "CHEMIN_CACHE_CATALOGUE",
                            tmp_path / "cache.json")
        produits = [{"id": 1, "nom": "BIDON", "quantite_stock": 12}]
        cache_catalogue.sauvegarder(produits)
        relus, horodatage = cache_catalogue.charger()
        assert relus == produits
        assert horodatage  # un horodatage a bien été écrit

    def test_sauvegarde_ecrase_le_precedent_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cache_catalogue, "CHEMIN_CACHE_CATALOGUE",
                            tmp_path / "cache.json")
        cache_catalogue.sauvegarder([{"id": 1, "nom": "A"}])
        cache_catalogue.sauvegarder([{"id": 2, "nom": "B"}])
        relus, _ = cache_catalogue.charger()
        assert relus == [{"id": 2, "nom": "B"}]

    def test_fichier_corrompu_traite_comme_vide(self, tmp_path, monkeypatch):
        chemin = tmp_path / "cache.json"
        chemin.write_text("{ceci n'est pas du json", encoding="utf-8")
        monkeypatch.setattr(cache_catalogue, "CHEMIN_CACHE_CATALOGUE", chemin)
        produits, horodatage = cache_catalogue.charger()
        assert produits == []
        assert horodatage == ""


class TestQueueHorsLigne:
    def test_vide_par_defaut(self, tmp_path, monkeypatch):
        monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "queue.json")
        assert queue_hors_ligne.charger() == []

    def test_ajouter_puis_charger(self, tmp_path, monkeypatch):
        monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "queue.json")
        queue_hors_ligne.ajouter("entree", produit_id=1, quantite=10, note="Livraison")
        items = queue_hors_ligne.charger()
        assert len(items) == 1
        assert items[0].type_operation == "entree"
        assert items[0].produit_id == 1
        assert items[0].quantite == 10
        assert items[0].note == "Livraison"
        assert items[0].date_saisie  # horodatage renseigné

    def test_ajustement_delta_negatif_conserve(self, tmp_path, monkeypatch):
        monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "queue.json")
        queue_hors_ligne.ajouter("ajustement", produit_id=2, quantite=-5, note="Casse")
        items = queue_hors_ligne.charger()
        assert items[0].quantite == -5

    def test_retirer(self, tmp_path, monkeypatch):
        monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "queue.json")
        queue_hors_ligne.ajouter("entree", produit_id=1, quantite=10)
        queue_hors_ligne.ajouter("entree", produit_id=2, quantite=5)
        queue_hors_ligne.retirer(0)
        items = queue_hors_ligne.charger()
        assert len(items) == 1
        assert items[0].produit_id == 2

    def test_retirer_index_hors_bornes_ne_leve_pas(self, tmp_path, monkeypatch):
        monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", tmp_path / "queue.json")
        queue_hors_ligne.ajouter("entree", produit_id=1, quantite=10)
        queue_hors_ligne.retirer(99)
        assert len(queue_hors_ligne.charger()) == 1

    def test_fichier_corrompu_traite_comme_vide(self, tmp_path, monkeypatch):
        chemin = tmp_path / "queue.json"
        chemin.write_text("{ceci n'est pas du json", encoding="utf-8")
        monkeypatch.setattr(queue_hors_ligne, "CHEMIN_QUEUE", chemin)
        assert queue_hors_ligne.charger() == []
