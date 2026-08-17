"""Vue « API distante » : configuration et pilotage du serveur d'accès
distant en lecture seule (voir `services/api_management_service.py`)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from app.i18n.translations import t
from app.services.api_management_service import ErreurGestionApi
from app.ui import theme
from app.ui.components.toast import afficher_toast


class ApiView(ttk.Frame):
    """Réglages (hôte/port/jeton) + démarrage/arrêt du serveur autonome et de
    son démarrage automatique avec Windows."""

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._service = application.api_management
        self._construire()

    def _carte(self, titre: str) -> ttk.Frame:
        cadre = tk.Frame(self, bg=theme.COULEURS["carte"], highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        cadre.pack(fill="x", padx=theme.PAD_L, pady=(0, theme.PAD))
        ttk.Label(cadre, text=titre, style="SousTitre.TLabel").pack(
            anchor="w", padx=theme.PAD, pady=(theme.PAD, theme.PAD_S))
        return cadre

    def _construire(self) -> None:
        ttk.Label(self, text=t("api_titre"), style="Titre.TLabel").pack(
            anchor="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD_S))
        ttk.Label(self, text=t("api_description"), style="Secondaire.TLabel",
                  wraplength=760, justify="left").pack(
            anchor="w", padx=theme.PAD_L, pady=(0, theme.PAD_L))

        # Configuration ---------------------------------------------------
        carte_config = self._carte(t("api_config_titre"))
        ligne_hote = ttk.Frame(carte_config, style="Carte.TFrame")
        ligne_hote.pack(fill="x", padx=theme.PAD, pady=theme.PAD_S)
        ttk.Label(ligne_hote, text=t("api_hote"), style="Carte.TLabel",
                  width=28).pack(side="left")
        self.var_hote = tk.StringVar()
        ttk.Entry(ligne_hote, textvariable=self.var_hote, width=22).pack(side="left")
        ttk.Label(ligne_hote, text=t("api_port"), style="Carte.TLabel").pack(
            side="left", padx=(theme.PAD, 4))
        self.var_port = tk.StringVar()
        ttk.Entry(ligne_hote, textvariable=self.var_port, width=8).pack(side="left")
        ttk.Label(carte_config, text=t("api_hote_aide"), style="Secondaire.TLabel").pack(
            anchor="w", padx=theme.PAD)

        ligne_jeton_client = ttk.Frame(carte_config, style="Carte.TFrame")
        ligne_jeton_client.pack(fill="x", padx=theme.PAD, pady=theme.PAD_S)
        ttk.Label(ligne_jeton_client, text=t("api_jeton_client"), style="Carte.TLabel",
                  width=28).pack(side="left")
        self.var_jeton_client = tk.StringVar()
        ttk.Entry(ligne_jeton_client, textvariable=self.var_jeton_client, width=44).pack(
            side="left", fill="x", expand=True)
        ttk.Button(ligne_jeton_client, text=t("api_generer_jeton_client"),
                  command=self._generer_jeton_client).pack(side="left", padx=(theme.PAD, 0))

        ligne_jeton_principal = ttk.Frame(carte_config, style="Carte.TFrame")
        ligne_jeton_principal.pack(fill="x", padx=theme.PAD, pady=theme.PAD_S)
        ttk.Label(ligne_jeton_principal, text=t("api_jeton_principal"), style="Carte.TLabel",
                  width=28).pack(side="left")
        self.var_jeton_principal = tk.StringVar()
        ttk.Entry(ligne_jeton_principal, textvariable=self.var_jeton_principal,
                 width=44).pack(side="left", fill="x", expand=True)
        ttk.Button(ligne_jeton_principal, text=t("api_generer_jeton_principal"),
                  command=self._generer_jeton_principal).pack(side="left", padx=(theme.PAD, 0))

        ligne_jeton_facturation = ttk.Frame(carte_config, style="Carte.TFrame")
        ligne_jeton_facturation.pack(fill="x", padx=theme.PAD, pady=theme.PAD_S)
        ttk.Label(ligne_jeton_facturation, text=t("api_jeton_facturation"), style="Carte.TLabel",
                  width=28).pack(side="left")
        self.var_jeton_facturation = tk.StringVar()
        ttk.Entry(ligne_jeton_facturation, textvariable=self.var_jeton_facturation,
                 width=44).pack(side="left", fill="x", expand=True)
        ttk.Button(ligne_jeton_facturation, text=t("api_generer_jeton_facturation"),
                  command=self._generer_jeton_facturation).pack(side="left", padx=(theme.PAD, 0))

        ligne_jeton_stock = ttk.Frame(carte_config, style="Carte.TFrame")
        ligne_jeton_stock.pack(fill="x", padx=theme.PAD, pady=theme.PAD_S)
        ttk.Label(ligne_jeton_stock, text=t("api_jeton_stock"), style="Carte.TLabel",
                  width=28).pack(side="left")
        self.var_jeton_stock = tk.StringVar()
        ttk.Entry(ligne_jeton_stock, textvariable=self.var_jeton_stock,
                 width=44).pack(side="left", fill="x", expand=True)
        ttk.Button(ligne_jeton_stock, text=t("api_generer_jeton_stock"),
                  command=self._generer_jeton_stock).pack(side="left", padx=(theme.PAD, 0))

        ttk.Button(carte_config, text=t("enregistrer"), style="Accent.TButton",
                  command=self._enregistrer_config).pack(
            anchor="e", padx=theme.PAD, pady=(theme.PAD_S, theme.PAD))

        # Serveur -----------------------------------------------------------
        carte_serveur = self._carte(t("api_serveur_titre"))
        ligne_statut = ttk.Frame(carte_serveur, style="Carte.TFrame")
        ligne_statut.pack(fill="x", padx=theme.PAD, pady=theme.PAD_S)
        ttk.Label(ligne_statut, text=t("api_statut") + " :", style="Carte.TLabel").pack(
            side="left")
        self._label_statut = ttk.Label(ligne_statut, text="…", style="Carte.TLabel")
        self._label_statut.pack(side="left", padx=(4, theme.PAD_L))
        ttk.Button(ligne_statut, text="↻ " + t("api_actualiser"),
                  command=self._actualiser_statut).pack(side="left")

        ligne_actions = ttk.Frame(carte_serveur, style="Carte.TFrame")
        ligne_actions.pack(fill="x", padx=theme.PAD, pady=(0, theme.PAD_S))
        ttk.Button(ligne_actions, text="▶ " + t("api_demarrer"), style="Accent.TButton",
                  command=self._demarrer).pack(side="left")
        ttk.Button(ligne_actions, text="■ " + t("api_arreter"), style="Danger.TButton",
                  command=self._arreter).pack(side="left", padx=(theme.PAD, 0))

        self.var_demarrage_auto = tk.BooleanVar()
        ttk.Checkbutton(carte_serveur, text=t("api_demarrage_auto"),
                       variable=self.var_demarrage_auto,
                       command=self._basculer_demarrage_auto).pack(
            anchor="w", padx=theme.PAD, pady=(0, theme.PAD))

        self._label_url = ttk.Label(self, text="", style="Secondaire.TLabel")
        self._label_url.pack(anchor="w", padx=theme.PAD_L)

    # Rafraîchissement --------------------------------------------------------
    def rafraichir(self) -> None:
        config = self._service.config()
        self.var_hote.set(config["host"])
        self.var_port.set(str(config["port"]))
        self.var_jeton_client.set(config["token_client"])
        self.var_jeton_principal.set(config["token_principal"])
        self.var_jeton_facturation.set(config["token_facturation"])
        self.var_jeton_stock.set(config["token_stock"])
        try:
            self.var_demarrage_auto.set(self._service.demarrage_auto_actif())
        except Exception:  # noqa: BLE001 — schtasks indisponible, on n'affiche pas d'erreur
            self.var_demarrage_auto.set(False)
        self._actualiser_statut()

    def _actualiser_statut(self) -> None:
        en_ligne = self._service.en_ligne()
        self._label_statut.configure(
            text=t("api_statut_actif") if en_ligne else t("api_statut_inactif"),
            foreground=theme.COULEURS["succes"] if en_ligne else theme.COULEURS["danger"],
        )
        config = self._service.config()
        self._label_url.configure(
            text=f"{t('api_url_test')} http://{config['host']}:{config['port']}/health")

    # Actions -----------------------------------------------------------------
    def _generer_jeton_client(self) -> None:
        self.var_jeton_client.set(self._service.generer_jeton())

    def _generer_jeton_principal(self) -> None:
        self.var_jeton_principal.set(self._service.generer_jeton())

    def _generer_jeton_facturation(self) -> None:
        self.var_jeton_facturation.set(self._service.generer_jeton())

    def _generer_jeton_stock(self) -> None:
        self.var_jeton_stock.set(self._service.generer_jeton())

    def _enregistrer_config(self) -> None:
        hote = self.var_hote.get().strip()
        port_texte = self.var_port.get().strip()
        if not hote or not port_texte:
            messagebox.showerror(t("erreur"), t("api_hote_port_requis"))
            return
        try:
            port = int(port_texte)
        except ValueError:
            messagebox.showerror(t("erreur"), t("nombre_invalide"))
            return
        self._service.enregistrer_config(
            hote, port, self.var_jeton_client.get().strip(),
            self.var_jeton_principal.get().strip(),
            self.var_jeton_facturation.get().strip(),
            self.var_jeton_stock.get().strip())
        afficher_toast(self, t("api_config_enregistree"))
        self._actualiser_statut()

    def _demarrer(self) -> None:
        try:
            self._service.demarrer()
        except ErreurGestionApi as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("api_demarre"))
        self.after(1200, self._actualiser_statut)

    def _arreter(self) -> None:
        try:
            self._service.arreter()
        except ErreurGestionApi as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("api_arrete"))
        self.after(500, self._actualiser_statut)

    def _basculer_demarrage_auto(self) -> None:
        actif = self.var_demarrage_auto.get()
        try:
            self._service.activer_demarrage_auto(actif)
        except ErreurGestionApi as exc:
            messagebox.showerror(t("erreur"), str(exc))
            self.var_demarrage_auto.set(not actif)
            return
        afficher_toast(self, t("api_demarrage_auto_active") if actif
                       else t("api_demarrage_auto_desactive"))
