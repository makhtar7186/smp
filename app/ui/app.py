"""Fenêtre principale : barre latérale de navigation, zone de contenu, langue."""
from __future__ import annotations

import traceback
import tkinter as tk
from tkinter import messagebox, ttk

from app import config
from app.i18n import translations
from app.i18n.translations import t
from app.repositories.base_repository import creer_connexion
from app.services.api_management_service import ApiManagementService
from app.services.client_maintenance_service import ClientMaintenanceService
from app.services.export_excel_service import ExportExcelService
from app.services.facturation_service import FacturationService
from app.services.paiement_service import PaiementService
from app.services.pdf_service import PdfService
from app.services.proforma_service import ProformaService
from app.services.remise_service import RemiseService
from app.services.stats_service import StatsService
from app.ui import theme

_ELEMENTS_NAV = [
    ("dashboard", "📊", "nav_dashboard"),
    ("analyse", "🔍", "nav_analyse"),
    ("facturation", "🧾", "nav_facturation"),
    ("proforma", "📝", "nav_proforma"),
    ("ventes", "📚", "nav_ventes"),
    ("archive", "🗄", "nav_archive"),
    ("produits", "🛏", "nav_produits"),
    ("clients", "👥", "nav_clients"),
    ("remises", "🎁", "nav_remises"),
    ("paiements", "💰", "nav_paiements"),
    ("vue_client", "🧮", "nav_vue_client"),
    ("api", "🌐", "nav_api"),
    ("journal_fusions", "🗂", "nav_journal_fusions"),
    ("parametres_machine", "⚙", "nav_parametres_machine"),
]


class Application(tk.Tk):
    """Fenêtre principale de SMP Gestion."""

    def __init__(self) -> None:
        super().__init__()
        config.preparer_dossiers()
        self.title(t("app_titre"))
        self.geometry("1280x780")
        self.minsize(1080, 680)
        theme.appliquer_theme(self)
        self.configure(bg=theme.COULEURS["fond"])

        # Services partagés (une connexion pour toute l'application)
        conn = creer_connexion()
        self.facturation = FacturationService(conn)
        self.proformas = ProformaService(conn, self.facturation)
        self.stats = StatsService(conn)
        self.remises = RemiseService(conn)
        self.paiements = PaiementService(conn)
        self.export_excel = ExportExcelService(conn)
        self.clients_maintenance = ClientMaintenanceService(conn)
        self.pdf = PdfService()
        self.api_management = ApiManagementService()
        self.conn = conn

        self._demarrer_api_si_active()

        self._vues: dict[str, ttk.Frame] = {}
        self._boutons_nav: dict[str, tk.Button] = {}
        self._vue_courante: str | None = None
        self._construire()

    # API distante (lecture seule) --------------------------------------------
    def _demarrer_api_si_active(self) -> None:
        """Démarre le serveur API dans un processus **autonome** si
        l'utilisateur l'a activé (réglage `api_actif`, voir README) — il
        continuera de tourner même après la fermeture de cette fenêtre (voir
        `ApiManagementService.demarrer`). Sans jeton configuré, l'API
        refuserait de toute façon toute requête (voir `api.auth`)."""
        if not config.api_active():
            return
        try:
            self.api_management.demarrer()
        except Exception:  # noqa: BLE001 — l'API ne doit jamais bloquer l'appli
            traceback.print_exc()

    # Erreurs -------------------------------------------------------------
    def report_callback_exception(self, exc, val, tb) -> None:
        """Filet de sécurité global : sans lui, une erreur imprévue dans un
        callback Tkinter disparaît silencieusement (l'exécutable --windowed
        n'a pas de console où voir la trace) — l'action semble juste « ne
        rien faire ». Elle est ici affichée à l'écran et journalisée."""
        detail = "".join(traceback.format_exception(exc, val, tb))
        try:
            config.preparer_dossiers()
            with open(config.DOSSIER_DATA / "erreurs.log", "a",
                     encoding="utf-8") as fichier:
                fichier.write(detail + "\n" + "-" * 70 + "\n")
        except OSError:
            pass
        messagebox.showerror(t("erreur"), f"{t('erreur_inattendue')}\n\n{val}")

    # Construction ------------------------------------------------------------
    def _construire(self) -> None:
        """(Re)construit sidebar + zone de contenu (appelé au changement de langue)."""
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
        """Barre latérale : les éléments de nav défilent (molette ou barre de
        défilement) dans un Canvas — avec 15 entrées, une fenêtre de taille
        modeste ne les affichait plus toutes (les derniers onglets, ex.
        Import/API, sortaient de l'écran sans aucun moyen d'y accéder)."""
        sidebar = tk.Frame(self, bg=theme.COULEURS["sidebar"], width=220)
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.grid_propagate(False)
        sidebar.rowconfigure(0, weight=1)
        sidebar.columnconfigure(0, weight=1)

        canvas = tk.Canvas(sidebar, bg=theme.COULEURS["sidebar"], highlightthickness=0,
                           width=220)
        defilement = ttk.Scrollbar(sidebar, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=defilement.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        defilement.grid(row=0, column=1, sticky="ns")

        zone_nav = tk.Frame(canvas, bg=theme.COULEURS["sidebar"])
        fenetre_id = canvas.create_window((0, 0), window=zone_nav, anchor="nw")

        def _maj_scrollregion(_evenement=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _maj_largeur(evenement) -> None:
            canvas.itemconfigure(fenetre_id, width=evenement.width)

        zone_nav.bind("<Configure>", _maj_scrollregion)
        canvas.bind("<Configure>", _maj_largeur)

        def _molette(evenement) -> None:
            canvas.yview_scroll(-1 * (evenement.delta // 120), "units")

        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _molette))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        tk.Label(zone_nav, text="SMP", bg=theme.COULEURS["sidebar"],
                 fg="white", font=("Segoe UI", 14, "bold")).pack(pady=(24, 2))
        tk.Label(zone_nav, text="Gestion", bg=theme.COULEURS["sidebar"],
                 fg=theme.COULEURS["sidebar_texte"],
                 font=theme.POLICES["petit"]).pack(pady=(0, 20))

        for cle, icone, cle_libelle in _ELEMENTS_NAV:
            bouton = tk.Button(
                zone_nav, text=f"  {icone}  {t(cle_libelle)}", anchor="w",
                bg=theme.COULEURS["sidebar"], fg=theme.COULEURS["sidebar_texte"],
                activebackground=theme.COULEURS["sidebar_actif"],
                activeforeground="white", relief="flat", bd=0,
                font=theme.POLICES["nav"], cursor="hand2", padx=14, pady=9,
                command=lambda c=cle: self.afficher_vue(c),
            )
            bouton.pack(fill="x")
            self._boutons_nav[cle] = bouton

        # Sélecteur de langue : fixé en bas de la sidebar, hors zone défilante,
        # pour rester toujours visible quel que soit le nombre d'onglets.
        bas = tk.Frame(sidebar, bg=theme.COULEURS["sidebar"])
        bas.grid(row=1, column=0, columnspan=2, sticky="ew", pady=16, padx=14)
        tk.Label(bas, text=t("langue"), bg=theme.COULEURS["sidebar"],
                 fg=theme.COULEURS["sidebar_texte"],
                 font=theme.POLICES["petit"]).pack(anchor="w")
        self._combo_langue = ttk.Combobox(
            bas, state="readonly", width=14,
            values=[translations.NOMS_LANGUES[code] for code in config.LANGUES_DISPONIBLES],
        )
        self._combo_langue.set(translations.NOMS_LANGUES[translations.langue_active()])
        self._combo_langue.pack(fill="x", pady=(4, 0))
        self._combo_langue.bind("<<ComboboxSelected>>", self._changer_langue)

    def _changer_langue(self, _evenement) -> None:
        """Bascule fr/en/zh et reconstruit toute l'interface."""
        nom_choisi = self._combo_langue.get()
        for code, nom in translations.NOMS_LANGUES.items():
            if nom == nom_choisi:
                translations.definir_langue(code)
                break
        self._construire()

    # Navigation --------------------------------------------------------------
    def afficher_vue(self, cle: str) -> None:
        """Affiche la vue demandée (créée paresseusement) et rafraîchit ses données."""
        # Import local pour éviter les cycles UI ↔ vues
        from app.ui.views.analyse_view import AnalyseView
        from app.ui.views.api_view import ApiView
        from app.ui.views.archive_view import ArchiveView
        from app.ui.views.clients_view import ClientsView
        from app.ui.views.dashboard_view import DashboardView
        from app.ui.views.facturation_view import FacturationView
        from app.ui.views.journal_fusions_view import JournalFusionsView
        from app.ui.views.parametres_machine_view import ParametresMachineView
        from app.ui.views.produits_view import ProduitsView
        from app.ui.views.proforma_view import ProformaView
        from app.ui.views.paiements_view import PaiementsView
        from app.ui.views.remises_view import RemisesView
        from app.ui.views.ventes_view import VentesView
        from app.ui.views.vue_client_view import VueClientView

        fabriques = {
            "dashboard": DashboardView,
            "analyse": AnalyseView,
            "facturation": FacturationView,
            "proforma": ProformaView,
            "ventes": VentesView,
            "archive": ArchiveView,
            "produits": ProduitsView,
            "clients": ClientsView,
            "remises": RemisesView,
            "paiements": PaiementsView,
            "vue_client": VueClientView,
            "api": ApiView,
            "journal_fusions": JournalFusionsView,
            "parametres_machine": ParametresMachineView,
        }
        if cle not in self._vues:
            self._vues[cle] = fabriques[cle](self._conteneur, self)
            self._vues[cle].grid(row=0, column=0, sticky="nsew")

        for autre in self._vues.values():
            autre.grid_remove()
        self._vues[cle].grid()
        vue = self._vues[cle]
        if hasattr(vue, "rafraichir"):
            vue.rafraichir()
        self._vue_courante = cle

        for cle_bouton, bouton in self._boutons_nav.items():
            actif = cle_bouton == cle
            bouton.configure(
                bg=theme.COULEURS["sidebar_actif" if actif else "sidebar"],
                fg="white" if actif else theme.COULEURS["sidebar_texte"],
            )

    def obtenir_vue(self, cle: str) -> ttk.Frame:
        """Instance de la vue (créée si nécessaire) — pour qu'une vue en
        pilote une autre, ex. ouvrir Facturation en mode édition depuis
        l'historique des ventes."""
        if cle not in self._vues:
            self.afficher_vue(cle)
        return self._vues[cle]


def lancer() -> None:
    """Instancie et lance l'application."""
    Application().mainloop()
