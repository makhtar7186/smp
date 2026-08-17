"""Fenêtre principale de la machine de facturation (offline-first) : nav
restreinte (Facturation, Proforma, Historique local, Produits, Clients),
statut de synchronisation toujours visible. Classe indépendante de
`Application` (comme `app.client.ui.ApplicationClient` l'est déjà) — connectée
au cache SQLite local, jamais à la base boss. Voir CLAUDE.md, section
« Machine de facturation »."""
from __future__ import annotations

import traceback
import tkinter as tk
from tkinter import messagebox, ttk

from app import config
from app.i18n.translations import t
from app.repositories.base_repository import creer_connexion
from app.services.pdf_service import PdfService
from app.services.proforma_service import ProformaService
from app.sync import config_sync
from app.sync.api_sync_client import ApiSyncClient
from app.sync.archive_worker import ArchiveStatutSyncWorker
from app.sync.client_maintenance_hors_ligne import ClientMaintenanceServiceHorsLigne
from app.sync.config_sync import ConfigSync
from app.sync.etat_numerotation import EtatNumerotationRepository
from app.sync.facturation_hors_ligne import FacturationServiceHorsLigne
from app.sync.models import StatutSync
from app.sync.numero_poller_worker import NumeroPollerWorker
from app.sync.numero_reservation import NumeroReservationRepository
from app.sync.numero_resilient import NumeroResilientService
from app.sync.numero_worker import NumeroReservationWorker
from app.sync.queue_repository import QueueSyncRepository
from app.sync.referentiel_worker import ReferentielSyncWorker
from app.sync.referentiels_hors_ligne import (
    ClientRepositoryHorsLigne,
    ProduitRepositoryHorsLigne,
)
from app.sync.worker import SyncWorker
from app.ui import theme
from app.ui.components.sync_status import SyncStatusBadge

_ELEMENTS_NAV = [
    ("facturation", "🧾", "nav_facturation"),
    ("proforma", "📝", "nav_proforma"),
    ("ventes", "📚", "nav_ventes"),
    ("produits", "🛏", "nav_produits"),
    ("clients", "👥", "nav_clients"),
]


class FenetreConfigSync(tk.Toplevel):
    """Saisie/édition des coordonnées de connexion à la machine boss et de
    l'identité de ce poste — même idiome que `app.client.ui.FenetreConfig`."""

    def __init__(self, parent: tk.Tk, config_actuelle: ConfigSync) -> None:
        super().__init__(parent)
        self.title(t("sync_premier_lancement_titre"))
        self.resizable(False, False)
        self.configure(bg=theme.COULEURS["fond"])
        self.resultat: ConfigSync | None = None
        self.transient(parent)
        self.grab_set()

        cadre = ttk.Frame(self, padding=theme.PAD_L)
        cadre.pack(fill="both", expand=True)
        ttk.Label(cadre, text=t("sync_premier_lancement_texte"),
                 style="Secondaire.TLabel", wraplength=380, justify="left").pack(
            anchor="w", pady=(0, theme.PAD))

        ttk.Label(cadre, text=t("sync_hote"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_hote = ttk.Entry(cadre)
        self._champ_hote.insert(0, config_actuelle.hote)
        self._champ_hote.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("sync_port"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_port = ttk.Entry(cadre)
        self._champ_port.insert(0, str(config_actuelle.port))
        self._champ_port.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("sync_jeton"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_token = ttk.Entry(cadre, show="•")
        self._champ_token.insert(0, config_actuelle.token)
        self._champ_token.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("sync_machine_id"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_machine = ttk.Entry(cadre)
        self._champ_machine.insert(0, config_actuelle.machine_id)
        self._champ_machine.pack(fill="x", pady=(2, 16))

        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x")
        ttk.Button(boutons, text=t("annuler"), command=self.destroy).pack(side="right")
        ttk.Button(boutons, text=t("sync_valider"), style="Accent.TButton",
                  command=self._valider).pack(side="right", padx=(0, 8))

        # Taille calculée d'après le contenu réel plutôt que fixée en dur : une
        # hauteur figée trop petite (ex. "440x360") coupait silencieusement le
        # bouton "Valider" hors de la fenêtre, avec le redimensionnement
        # désactivé — jamais visible ni cliquable.
        self.update_idletasks()
        self.geometry(f"{max(440, self.winfo_reqwidth())}x{self.winfo_reqheight()}")

    def _valider(self) -> None:
        hote = self._champ_hote.get().strip()
        token = self._champ_token.get().strip()
        machine_id = self._champ_machine.get().strip()
        try:
            port = int(self._champ_port.get().strip())
        except ValueError:
            messagebox.showerror(t("erreur"), t("nombre_invalide"), parent=self)
            return
        if not hote or not token or not machine_id:
            messagebox.showerror(t("erreur"), t("sync_champs_requis"), parent=self)
            return
        self.resultat = ConfigSync(hote=hote, port=port, token=token, machine_id=machine_id)
        self.destroy()


class ApplicationFacturation(tk.Tk):
    """Fenêtre principale de la machine de facturation. Réutilise les mêmes
    vues Tkinter que l'application boss (`FacturationView`, `ProformaView`,
    `VentesView`, `ProduitsView`, `ClientsView`) — jamais Dashboards/Remises/
    Archive/Paiements/Import Excel/API, réservées au boss (vues agrégées/
    globales sans sens à l'échelle d'un seul poste).

    `ELEMENTS_NAV`/`_fabriques_vues`/`_cadre_bas_sidebar` sont des points
    d'extension pensés pour `ApplicationFacturationEtendue`
    (`app/ui/app_facturation_etendue.py`, mode « facturation à distance » de
    `SMP.exe`) — voir CLAUDE.md, section « Machine de facturation »."""

    ELEMENTS_NAV = _ELEMENTS_NAV

    def __init__(self) -> None:
        super().__init__()
        config.preparer_dossiers()
        self.title(t("app_titre"))
        self.geometry("1280x780")
        self.minsize(1080, 680)
        theme.appliquer_theme(self)
        self.configure(bg=theme.COULEURS["fond"])
        self.report_callback_exception = self._sur_exception

        conn = creer_connexion(config.CHEMIN_CACHE_FACTURATION)
        self.conn = conn
        # `on_enfiler` réveille immédiatement la synchro montante dès qu'une
        # opération est committée (facture, client, produit, fusion), plutôt
        # que d'attendre le prochain passage périodique du worker — celui-ci
        # est réaffecté en cours de vie de l'app (`_ouvrir_config`), d'où le
        # lambda qui relit `self.sync_worker` à chaque appel plutôt que de
        # capturer l'instance courante.
        self._queue = QueueSyncRepository(
            conn, on_enfiler=lambda: self.sync_worker.declencher_immediat())
        self._numeros = NumeroReservationRepository(conn)
        self._etat_numerotation = EtatNumerotationRepository(conn)
        self.facturation = FacturationServiceHorsLigne(conn, self._queue, self._numeros)
        self.proformas = ProformaService(conn, self.facturation)
        self.clients_maintenance = ClientMaintenanceServiceHorsLigne(conn, self._queue)
        self._produits_repo = ProduitRepositoryHorsLigne(conn, self._queue)
        self._clients_repo = ClientRepositoryHorsLigne(conn, self._queue)
        self.pdf = PdfService()

        self._config_sync = config_sync.charger()
        api = ApiSyncClient(self._config_sync)
        self.sync_worker = SyncWorker(
            config.CHEMIN_CACHE_FACTURATION, api,
            intervalle_secondes=self._config_sync.intervalle_sync_secondes,
            on_statut_change=self._sur_changement_statut_sync)
        self.referentiel_worker = ReferentielSyncWorker(
            config.CHEMIN_CACHE_FACTURATION, api,
            intervalle_secondes=self._config_sync.intervalle_referentiels_secondes)
        self.numero_worker = NumeroReservationWorker(config.CHEMIN_CACHE_FACTURATION, api)
        # Palier 1 (nominal) : sondage continu en arrière-plan (3-5s) de
        # `GET /factures/dernier-numero` — maintient `base_connu` à jour pour
        # que `NumeroResilientService.suggerer_numero()` reste instantané,
        # sans jamais appeler le réseau lui-même (voir CLAUDE.md).
        self.numero_poller = NumeroPollerWorker(config.CHEMIN_CACHE_FACTURATION, api)
        self.archive_worker = ArchiveStatutSyncWorker(config.CHEMIN_CACHE_FACTURATION, api)
        # Numérotation résiliente (voir CLAUDE.md) : suggestion instantanée
        # (palier 1, sans réseau) puis confirmation silencieuse au moment de
        # l'enregistrement, avec repli sur `self._numeros` (palier 2, pool de
        # secours alimenté par `self.numero_worker`) puis sur le calcul
        # déterministe local (palier 3) si le poller est en coupure soutenue.
        self.numero_resilient = NumeroResilientService(
            self._numeros, self._etat_numerotation, api)

        self._vues: dict[str, ttk.Frame] = {}
        self._boutons_nav: dict[str, tk.Button] = {}
        self._vue_courante: str | None = None
        self._construire()
        self.protocol("WM_DELETE_WINDOW", self._fermer)
        self.after(150, self._demarrage)

    # Erreurs -------------------------------------------------------------
    def _sur_exception(self, exc, val, tb) -> None:
        detail = "".join(traceback.format_exception(exc, val, tb))
        try:
            config.preparer_dossiers()
            with open(config.DOSSIER_DATA / "erreurs.log", "a",
                     encoding="utf-8") as fichier:
                fichier.write(detail + "\n" + "-" * 70 + "\n")
        except OSError:
            pass
        messagebox.showerror(t("erreur"), f"{t('erreur_inattendue')}\n\n{val}")

    # Démarrage / arrêt des workers ---------------------------------------------
    def _demarrage(self) -> None:
        if not self._config_sync.complete:
            self._ouvrir_config(obligatoire=True)
        else:
            self.sync_worker.demarrer()
            self.referentiel_worker.demarrer()
            self.numero_worker.demarrer()
            self.numero_poller.demarrer()
            self.archive_worker.demarrer()

    def _ouvrir_config(self, obligatoire: bool = False) -> None:
        dialogue = FenetreConfigSync(self, self._config_sync)
        self.wait_window(dialogue)
        if dialogue.resultat is not None:
            self._config_sync = dialogue.resultat
            config_sync.sauvegarder(self._config_sync)
            api = ApiSyncClient(self._config_sync)
            self.sync_worker.arreter()
            self.referentiel_worker.arreter()
            self.numero_worker.arreter()
            self.numero_poller.arreter()
            self.archive_worker.arreter()
            self.sync_worker = SyncWorker(
                config.CHEMIN_CACHE_FACTURATION, api,
                intervalle_secondes=self._config_sync.intervalle_sync_secondes,
                on_statut_change=self._sur_changement_statut_sync)
            self.referentiel_worker = ReferentielSyncWorker(
                config.CHEMIN_CACHE_FACTURATION, api,
                intervalle_secondes=self._config_sync.intervalle_referentiels_secondes)
            self.numero_worker = NumeroReservationWorker(config.CHEMIN_CACHE_FACTURATION, api)
            self.numero_poller = NumeroPollerWorker(config.CHEMIN_CACHE_FACTURATION, api)
            self.archive_worker = ArchiveStatutSyncWorker(config.CHEMIN_CACHE_FACTURATION, api)
            self.numero_resilient = NumeroResilientService(
                self._numeros, self._etat_numerotation, api)
            self.sync_worker.demarrer()
            self.referentiel_worker.demarrer()
            self.numero_worker.demarrer()
            self.numero_poller.demarrer()
            self.archive_worker.demarrer()
        elif obligatoire:
            messagebox.showwarning(t("erreur"), t("sync_champs_requis"))

    def _sur_changement_statut_sync(self, statut: StatutSync) -> None:
        """Appelé depuis le THREAD WORKER — jamais toucher Tk directement ici :
        `after(0, ...)` marshalle la mise à jour vers le thread principal."""
        self.after(0, lambda: self._badge_sync.rafraichir(statut))

    def _fermer(self) -> None:
        self.sync_worker.arreter()
        self.referentiel_worker.arreter()
        self.numero_worker.arreter()
        self.numero_poller.arreter()
        self.archive_worker.arreter()
        self.destroy()

    # Construction ------------------------------------------------------------
    def _construire(self) -> None:
        for enfant in self.winfo_children():
            enfant.destroy()
        self._vues.clear()
        self._boutons_nav.clear()
        self.title(t("app_titre"))

        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        self._construire_sidebar()
        self._conteneur = ttk.Frame(self)
        self._conteneur.grid(row=0, column=1, sticky="nsew")
        self._conteneur.rowconfigure(0, weight=1)
        self._conteneur.columnconfigure(0, weight=1)

        self.afficher_vue(self._vue_courante or "facturation")

    def _construire_sidebar(self) -> None:
        sidebar = tk.Frame(self, bg=theme.COULEURS["sidebar"], width=220)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)

        tk.Label(sidebar, text="SMP", bg=theme.COULEURS["sidebar"],
                 fg="white", font=("Segoe UI", 14, "bold")).pack(pady=(24, 2))
        tk.Label(sidebar, text=t("sync_titre_machine_facturation"),
                 bg=theme.COULEURS["sidebar"], fg=theme.COULEURS["sidebar_texte"],
                 font=theme.POLICES["petit"]).pack(pady=(0, 20))

        for cle, icone, cle_libelle in self.ELEMENTS_NAV:
            bouton = tk.Button(
                sidebar, text=f"  {icone}  {t(cle_libelle)}", anchor="w",
                bg=theme.COULEURS["sidebar"], fg=theme.COULEURS["sidebar_texte"],
                activebackground=theme.COULEURS["sidebar_actif"],
                activeforeground="white", relief="flat", bd=0,
                font=theme.POLICES["nav"], cursor="hand2", padx=14, pady=9,
                command=lambda c=cle: self.afficher_vue(c),
            )
            bouton.pack(fill="x")
            self._boutons_nav[cle] = bouton

        bas = tk.Frame(sidebar, bg=theme.COULEURS["sidebar"])
        bas.pack(side="bottom", fill="x", padx=10, pady=12)
        self._cadre_bas_sidebar = bas
        ttk.Button(bas, text="⚙ " + t("sync_connexion"),
                  command=self._ouvrir_config).pack(fill="x", pady=(0, 6))
        self._badge_sync = SyncStatusBadge(bas, self._queue, self.sync_worker)
        self._badge_sync.pack(fill="x")

    # Navigation --------------------------------------------------------------
    def _fabriques_vues(self) -> dict:
        """Point d'extension : `ApplicationFacturationEtendue` complète ce
        dict avec les pages réseau uniquement (Archive/Marges/Factures
        clients/Import/Paiements/Vue client)."""
        from app.ui.views.clients_view import ClientsView
        from app.ui.views.facturation_view import FacturationView
        from app.ui.views.produits_view import ProduitsView
        from app.ui.views.proforma_view import ProformaView
        from app.ui.views.ventes_view import VentesView

        return {
            "facturation": FacturationView,
            "proforma": ProformaView,
            "ventes": lambda parent, app: VentesView(
                parent, app,
                statut_synchro_provider=self._queue.statut_pour_facture),
            "produits": lambda parent, app: ProduitsView(
                parent, app, repository=self._produits_repo, autoriser_fusion=False),
            "clients": lambda parent, app: ClientsView(
                parent, app, repository=self._clients_repo,
                autoriser_dissociation=False),
        }

    def afficher_vue(self, cle: str) -> None:
        fabriques = self._fabriques_vues()
        if cle not in self._vues:
            self._vues[cle] = fabriques[cle](self._conteneur, self)
            self._vues[cle].grid(row=0, column=0, sticky="nsew")

        for autre in self._vues.values():
            autre.grid_remove()
        self._vues[cle].grid()
        vue = self._vues[cle]
        if hasattr(vue, "rafraichir"):
            vue.rafraichir()
        elif hasattr(vue, "actualiser"):
            # Vues réutilisées telles quelles depuis app.client.ui (Onglet*,
            # convention "actualiser" plutôt que "rafraichir") — voir
            # ApplicationFacturationEtendue.
            vue.actualiser()
        self._vue_courante = cle

        for cle_bouton, bouton in self._boutons_nav.items():
            actif = cle_bouton == cle
            bouton.configure(
                bg=theme.COULEURS["sidebar_actif" if actif else "sidebar"],
                fg="white" if actif else theme.COULEURS["sidebar_texte"],
            )

    def obtenir_vue(self, cle: str) -> ttk.Frame:
        if cle not in self._vues:
            self.afficher_vue(cle)
        return self._vues[cle]


def lancer() -> None:
    """Instancie et lance l'application de la machine de facturation."""
    ApplicationFacturation().mainloop()
