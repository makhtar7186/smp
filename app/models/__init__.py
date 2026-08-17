"""Entités métier (dataclasses pures, sans dépendance UI ni SQL)."""
from app.models.client import Client
from app.models.produit import Produit
from app.models.vente import LigneVente
from app.models.facture import Facture
from app.models.proforma import Proforma
from app.models.remise import Remise
from app.models.versement import Versement
from app.models.mouvement_stock import MouvementStock
from app.models.queue_sync import OperationSync
from app.models.historique_fusion import HistoriqueFusion

__all__ = ["Client", "Produit", "LigneVente", "Facture", "Proforma", "Remise", "Versement",
           "MouvementStock", "OperationSync", "HistoriqueFusion"]
