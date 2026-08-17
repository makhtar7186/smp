"""Vue Historique complet distant (machine de facturation en mode étendu) —
réutilise `app.client.ui.OngletHistorique` tel quel via un petit adaptateur
routé vers les endpoints `/admin/factures*` (`role_facturation`, type
« usine »), plutôt que de réécrire une page de recherche/impression depuis
zéro. Complète (ne remplace pas) la page « Historique (local) » héritée
d'`ApplicationFacturation` : celle-ci ne montre que les factures créées sur
CE poste (cache local, fonctionne hors ligne) ; celle-ci montre l'historique
complet de la machine boss (réseau uniquement). Voir CLAUDE.md, section
« Machine de facturation »."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import ttk

from app.client.ui import OngletHistorique
from app.i18n.translations import t
from app.sync.api_sync_client import ApiSyncClient
from app.sync.config_sync import ConfigSync
from app.ui import theme


class _AdaptateurHistoriqueAdmin:
    """Mêmes noms de méthode qu'`app.client.api_client.ApiClient` (celles
    utilisées par `OngletHistorique`), routés vers les endpoints usine de
    `ApiSyncClient` (`/admin/factures*`)."""

    def __init__(self, api_admin: ApiSyncClient) -> None:
        self._api = api_admin

    def lister_factures(self, date_debut: date | None = None,
                        date_fin: date | None = None) -> list[dict]:
        # archivee=False : une facture archivée (page Archive) ne doit jamais
        # apparaître dans l'historique, ni localement ni ici — sans ce
        # filtre, `lister_factures_admin` (pensé pour la page Archive, qui a
        # justement besoin de voir les deux états) renvoie tout, y compris
        # les factures archivées.
        return self._api.lister_factures_admin(
            archivee=False, date_debut=date_debut, date_fin=date_fin)

    def telecharger_pdf(self, facture_id: int) -> bytes:
        return self._api.telecharger_pdf_admin(facture_id)

    def telecharger_bordereau(self, facture_id: int) -> bytes:
        return self._api.telecharger_bordereau_admin(facture_id)


class _AppAdapte:
    """Objet « app » minimal exposant `.api`/`.config`, seuls attributs dont
    `OngletHistorique` a besoin."""

    def __init__(self, api: _AdaptateurHistoriqueAdmin, config: ConfigSync) -> None:
        self.api = api
        self.config = config


class HistoriqueDistantView(ttk.Frame):
    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        ttk.Label(self, text=t("hist_distant_titre"), style="Titre.TLabel").pack(
            anchor="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))
        app_adapte = _AppAdapte(
            _AdaptateurHistoriqueAdmin(application.api_admin), application._config_sync)
        self._onglet = OngletHistorique(self, app_adapte)
        self._onglet.pack(fill="both", expand=True)

    def rafraichir(self) -> None:
        self._onglet.actualiser()
