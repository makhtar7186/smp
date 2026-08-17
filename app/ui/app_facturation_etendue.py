"""Variante étendue de la machine de facturation, utilisée par `SMP.exe`
quand configuré en mode « facturation à distance » (`config.mode_machine`).
Garde tel quel tout ce que fait `ApplicationFacturation` (hors ligne :
Facturation/Proforma/Historique local/Produits/Clients) et ajoute des pages
**réseau uniquement** (pas de cache, pas de mode hors ligne) : Historique
complet, Archive, Paiements, Vue client. Voir CLAUDE.md, section « Machine
de facturation »."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app import config
from app.client.api_client import ApiClient
from app.client.config_client import ConfigClient
from app.i18n.translations import t
from app.services.export_excel_service import ExportExcelService
from app.sync.api_sync_client import ApiSyncClient
from app.ui.app_facturation import ApplicationFacturation


class ApplicationFacturationEtendue(ApplicationFacturation):
    """`ELEMENTS_NAV` étend celui de la classe de base ; `_fabriques_vues`
    étend celui de la classe de base avec les nouvelles pages réseau."""

    ELEMENTS_NAV = ApplicationFacturation.ELEMENTS_NAV + [
        ("historique_complet", "🕘", "nav_historique_complet"),
        ("archive", "🗄", "nav_archive"),
        ("paiements", "💰", "nav_paiements"),
        ("vue_client", "🧮", "nav_vue_client"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.api_admin = ApiSyncClient(self._config_sync)
        self.api = self._construire_api_client()
        self.export_excel = ExportExcelService(self.conn)

    def _construire_api_client(self) -> ApiClient:
        """`OngletPaiements`/`OngletVueClient` (réutilisés tels quels)
        attendent un `ApiClient`/`ConfigClient` — construits ici à partir des
        coordonnées de `ConfigSync` (même jeton `role_facturation`, valable
        en lecture sur `/paiements/*` et en écriture sur la remise annuelle,
        voir CLAUDE.md)."""
        return ApiClient(ConfigClient(
            hote=self._config_sync.hote, port=self._config_sync.port,
            token=self._config_sync.token, machine_id=self._config_sync.machine_id))

    def _fabriques_vues(self) -> dict:
        from app.client.ui import OngletPaiements, OngletVueClient
        from app.ui.views.archive_view_distant import ArchiveDistantView
        from app.ui.views.historique_view_distant import HistoriqueDistantView

        return super()._fabriques_vues() | {
            "historique_complet": HistoriqueDistantView,
            "archive": ArchiveDistantView,
            "paiements": lambda parent, app: OngletPaiements(
                parent, app, autoriser_versement=False),
            "vue_client": lambda parent, app: OngletVueClient(parent, app),
        }

    def _ouvrir_config(self, obligatoire: bool = False) -> None:
        super()._ouvrir_config(obligatoire)
        # Les coordonnées ont pu changer (nouvel hôte/jeton) : reconstruire
        # api_admin/api pour ne pas continuer à parler à l'ancienne machine.
        self.api_admin = ApiSyncClient(self._config_sync)
        self.api = self._construire_api_client()

    def _construire_sidebar(self) -> None:
        super()._construire_sidebar()
        ttk.Button(self._cadre_bas_sidebar, text="🏠 " + t("param_repasser_principale"),
                  command=self._repasser_en_principale).pack(fill="x", pady=(6, 0))

    def _repasser_en_principale(self) -> None:
        if messagebox.askyesno(t("confirmer"), t("param_confirmer_repasser_principale")):
            config.definir_mode_machine("principale")
            messagebox.showinfo(t("succes"), t("param_redemarrage_requis"))


def lancer() -> None:
    """Instancie et lance la machine de facturation en mode étendu."""
    ApplicationFacturationEtendue().mainloop()
