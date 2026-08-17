"""Interface Tkinter de l'app Stock : consultation du catalogue avec sa
quantité en stock, saisie d'entrées et d'ajustements, et historique des
mouvements d'un produit sélectionné — via l'API HTTP `/stock` (rôle
`role_stock`, voir `app/api/routes_stock.py`). Aucune autre fonctionnalité
(facturation, paiements, dashboard, gestion clients) volontairement : cette
app est le poste dédié au suivi du stock, rien d'autre — voir CLAUDE.md.

Interface trilingue fr/中文 uniquement (même sous-ensemble volontaire que
`app.client.ui`, pas d'anglais), langue persistée dans `stock_config.json`."""
from __future__ import annotations

import tkinter as tk
import traceback
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

from app.i18n import translations
from app.i18n.translations import t
from app.models.produit import TYPE_OPTION_DIMENSION, TYPE_OPTION_LITRAGE
from app.stock import cache_catalogue, queue_hors_ligne
from app.stock.api_stock_client import (
    ApiStockClient, ErreurApiStock, ErreurAuthentification, ErreurInjoignable,
    ErreurPermission,
)
from app.stock.config_stock import ConfigStock, charger, sauvegarder
from app.ui import theme
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.formatting import format_date, format_nombre
from app.utils.recherche import correspond, decouper_termes

_LANGUES_STOCK = ("fr", "zh")  # sous-ensemble volontaire (pas d'anglais)

_INTERVALLE_AUTO_ACTUALISATION_MS = 15_000  # 15 s : rafraîchissement
# périodique du catalogue, sans attendre un clic sur « Actualiser ».

_LIBELLES_TYPE = {
    "entree": "stock_type_entree",
    "sortie": "stock_type_sortie",
    "ajustement": "stock_type_ajustement",
}
_LIBELLES_SOURCE = {
    "vente": "stock_source_vente",
    "manuel": "stock_source_manuel",
}


class FenetreConfig(tk.Toplevel):
    """Boîte de dialogue de saisie/édition de la connexion (IP, port, jeton,
    identifiant de poste optionnel) — même schéma que
    `app.client.ui.FenetreConfig`."""

    def __init__(self, parent: tk.Tk, config: ConfigStock) -> None:
        super().__init__(parent)
        self.title(t("client_connexion_titre"))
        self.resizable(False, False)
        self.configure(bg=theme.COULEURS["fond"])
        self.resultat: ConfigStock | None = None
        self.transient(parent)
        self.grab_set()

        cadre = ttk.Frame(self, padding=theme.PAD_L)
        cadre.pack(fill="both", expand=True)

        ttk.Label(cadre, text=t("client_hote"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_hote = ttk.Entry(cadre)
        self._champ_hote.insert(0, config.hote)
        self._champ_hote.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("client_port"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_port = ttk.Entry(cadre)
        self._champ_port.insert(0, str(config.port))
        self._champ_port.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("client_jeton"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_token = ttk.Entry(cadre, show="•")
        self._champ_token.insert(0, config.token)
        self._champ_token.pack(fill="x", pady=(2, 12))

        ttk.Label(cadre, text=t("client_machine_id"), style="SousTitre.TLabel").pack(anchor="w")
        self._champ_machine = ttk.Entry(cadre)
        self._champ_machine.insert(0, config.machine_id)
        self._champ_machine.pack(fill="x", pady=(2, 16))

        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x")
        ttk.Button(boutons, text=t("annuler"), command=self.destroy).pack(side="right")
        ttk.Button(boutons, text=t("client_enregistrer_connexion"), style="Accent.TButton",
                  command=self._valider).pack(side="right", padx=(0, 8))

        # Taille calculée d'après le contenu réel (voir FenetreConfig,
        # app/client/ui.py, pour le même correctif).
        self.update_idletasks()
        self.geometry(f"{max(420, self.winfo_reqwidth())}x{self.winfo_reqheight()}")

    def _valider(self) -> None:
        hote = self._champ_hote.get().strip()
        token = self._champ_token.get().strip()
        machine_id = self._champ_machine.get().strip()
        try:
            port = int(self._champ_port.get().strip())
        except ValueError:
            messagebox.showerror(t("erreur"), t("client_port_invalide"), parent=self)
            return
        if not hote or not token:
            messagebox.showerror(t("erreur"), t("client_hote_jeton_requis"), parent=self)
            return
        self.resultat = ConfigStock(hote=hote, port=port, token=token,
                                    machine_id=machine_id)
        self.destroy()


class DialogueEntreeStock(simpledialog.Dialog):
    """Saisie de la quantité et d'une note libre pour une entrée de stock."""

    def __init__(self, parent: tk.Widget) -> None:
        self.resultat: tuple[int, str] | None = None
        super().__init__(parent, title=t("stock_entree_titre"))

    def body(self, master: tk.Widget) -> tk.Widget:
        ttk.Label(master, text=t("stock_entree_quantite")).grid(
            row=0, column=0, sticky="w", pady=4)
        self._champ_quantite = ttk.Entry(master)
        self._champ_quantite.grid(row=0, column=1, pady=4)
        ttk.Label(master, text=t("stock_entree_note")).grid(
            row=1, column=0, sticky="w", pady=4)
        self._champ_note = ttk.Entry(master, width=28)
        self._champ_note.grid(row=1, column=1, pady=4)
        return self._champ_quantite

    def validate(self) -> bool:
        try:
            quantite = int(self._champ_quantite.get().strip().replace(" ", ""))
        except ValueError:
            messagebox.showerror(t("erreur"), t("nombre_invalide"), parent=self)
            return False
        if quantite <= 0:
            messagebox.showerror(t("erreur"), t("stock_quantite_invalide"), parent=self)
            return False
        self.resultat = (quantite, self._champ_note.get().strip())
        return True


class DialogueAjustementStock(simpledialog.Dialog):
    """Saisie du delta (signé) et du motif pour un ajustement de stock."""

    def __init__(self, parent: tk.Widget) -> None:
        self.resultat: tuple[int, str] | None = None
        super().__init__(parent, title=t("stock_ajustement_titre"))

    def body(self, master: tk.Widget) -> tk.Widget:
        ttk.Label(master, text=t("stock_ajustement_delta")).grid(
            row=0, column=0, sticky="w", pady=4)
        self._champ_delta = ttk.Entry(master)
        self._champ_delta.grid(row=0, column=1, pady=4)
        ttk.Label(master, text=t("stock_ajustement_motif")).grid(
            row=1, column=0, sticky="w", pady=4)
        self._champ_motif = ttk.Entry(master, width=28)
        self._champ_motif.grid(row=1, column=1, pady=4)
        return self._champ_delta

    def validate(self) -> bool:
        try:
            delta = int(self._champ_delta.get().strip().replace(" ", ""))
        except ValueError:
            messagebox.showerror(t("erreur"), t("nombre_invalide"), parent=self)
            return False
        if delta == 0:
            messagebox.showerror(t("erreur"), t("stock_delta_invalide"), parent=self)
            return False
        self.resultat = (delta, self._champ_motif.get().strip())
        return True


_VALEURS_TYPE_OPTION = {
    "aucune": "",
    "dimension": TYPE_OPTION_DIMENSION,
    "litrage": TYPE_OPTION_LITRAGE,
}


class DialogueNouveauProduit(simpledialog.Dialog):
    """Création d'un nouvel article de catalogue (nom, option, valeur) — seule
    voie de création désormais, voir CLAUDE.md section « Gestion de stock ».
    Le prix reste du ressort exclusif de l'app Facturation (page Produits) :
    ce dialogue ne le propose pas, le produit est créé au prix 0, à corriger
    depuis SMP. Le stock initial est aussi à 0 ; une entrée de stock distincte
    l'alimente."""

    def __init__(self, parent: tk.Widget) -> None:
        self.resultat: tuple[str, str, str] | None = None
        super().__init__(parent, title=t("stock_nouveau_produit_titre"))

    def body(self, master: tk.Widget) -> tk.Widget:
        self._libelles_type_option = {
            "aucune": t("prod_type_option_aucune"),
            "dimension": t("prod_type_option_dimension"),
            "litrage": t("prod_type_option_litrage"),
        }
        ttk.Label(master, text=t("prod_nom")).grid(row=0, column=0, sticky="w", pady=4)
        self._champ_nom = ttk.Entry(master, width=24)
        self._champ_nom.grid(row=0, column=1, pady=4)
        ttk.Label(master, text=t("prod_type_option")).grid(
            row=1, column=0, sticky="w", pady=4)
        self.var_type_option = tk.StringVar(value=self._libelles_type_option["aucune"])
        ttk.Combobox(master, textvariable=self.var_type_option, state="readonly",
                     width=22, values=list(self._libelles_type_option.values())).grid(
            row=1, column=1, pady=4)
        ttk.Label(master, text=t("prod_valeur_option")).grid(
            row=2, column=0, sticky="w", pady=4)
        self._champ_valeur = ttk.Entry(master, width=24)
        self._champ_valeur.grid(row=2, column=1, pady=4)
        return self._champ_nom

    def validate(self) -> bool:
        nom = self._champ_nom.get().strip()
        if not nom:
            messagebox.showerror(t("erreur"), t("champ_obligatoire"), parent=self)
            return False
        cle_type = next(
            (cle for cle, libelle in self._libelles_type_option.items()
             if libelle == self.var_type_option.get()), "aucune")
        type_option = _VALEURS_TYPE_OPTION[cle_type]
        self.resultat = (nom, type_option, self._champ_valeur.get().strip())
        return True


class DialogueModifierProduit(simpledialog.Dialog):
    """Modification du nom/de l'option d'un article existant — jamais le
    prix (réglage exclusif de l'app Facturation). Champs pré-remplis avec
    les valeurs actuelles du produit sélectionné."""

    def __init__(self, parent: tk.Widget, produit: dict) -> None:
        self._produit = produit
        self.resultat: tuple[str, str, str] | None = None
        super().__init__(parent, title=t("stock_bouton_modifier_produit"))

    def body(self, master: tk.Widget) -> tk.Widget:
        self._libelles_type_option = {
            "aucune": t("prod_type_option_aucune"),
            "dimension": t("prod_type_option_dimension"),
            "litrage": t("prod_type_option_litrage"),
        }
        cle_actuelle = next(
            (cle for cle, valeur in _VALEURS_TYPE_OPTION.items()
             if valeur == self._produit.get("type_option", "")), "aucune")

        ttk.Label(master, text=t("prod_nom")).grid(row=0, column=0, sticky="w", pady=4)
        self._champ_nom = ttk.Entry(master, width=24)
        self._champ_nom.insert(0, self._produit.get("nom", ""))
        self._champ_nom.grid(row=0, column=1, pady=4)
        ttk.Label(master, text=t("prod_type_option")).grid(
            row=1, column=0, sticky="w", pady=4)
        self.var_type_option = tk.StringVar(value=self._libelles_type_option[cle_actuelle])
        ttk.Combobox(master, textvariable=self.var_type_option, state="readonly",
                     width=22, values=list(self._libelles_type_option.values())).grid(
            row=1, column=1, pady=4)
        ttk.Label(master, text=t("prod_valeur_option")).grid(
            row=2, column=0, sticky="w", pady=4)
        self._champ_valeur = ttk.Entry(master, width=24)
        self._champ_valeur.insert(0, self._produit.get("valeur_option", ""))
        self._champ_valeur.grid(row=2, column=1, pady=4)
        return self._champ_nom

    def validate(self) -> bool:
        nom = self._champ_nom.get().strip()
        if not nom:
            messagebox.showerror(t("erreur"), t("champ_obligatoire"), parent=self)
            return False
        cle_type = next(
            (cle for cle, libelle in self._libelles_type_option.items()
             if libelle == self.var_type_option.get()), "aucune")
        type_option = _VALEURS_TYPE_OPTION[cle_type]
        self.resultat = (nom, type_option, self._champ_valeur.get().strip())
        return True


class ApplicationStock(tk.Tk):
    """Fenêtre unique : recherche + tableau des produits (avec quantité en
    stock), boutons Entrée/Ajustement (activés sur sélection), panneau
    d'historique des mouvements du produit sélectionné."""

    def __init__(self) -> None:
        super().__init__()
        self.config: ConfigStock = charger()
        translations.definir_langue_memoire(
            self.config.langue if self.config.langue in _LANGUES_STOCK else "fr")
        self.geometry("980x620")
        self.minsize(760, 480)
        theme.appliquer_theme(self)
        self.configure(bg=theme.COULEURS["fond"])
        self.report_callback_exception = self._sur_exception

        self.api: ApiStockClient | None = None
        self._produits: list[dict] = []
        self._produits_affiches: dict[str, dict] = {}

        self._construire()
        self.after(150, self._demarrage)

    # Erreurs -------------------------------------------------------------
    def _sur_exception(self, exc, val, tb) -> None:
        traceback.print_exception(exc, val, tb)
        messagebox.showerror(t("erreur"), f"{t('erreur_inattendue')}\n\n{val}")

    # Démarrage -------------------------------------------------------------
    def _demarrage(self) -> None:
        if self.config.complete:
            self.api = ApiStockClient(self.config)
            self.actualiser()
        else:
            self._ouvrir_config(obligatoire=True)
        self.after(_INTERVALLE_AUTO_ACTUALISATION_MS, self._auto_actualiser)

    def _auto_actualiser(self) -> None:
        """Rafraîchit silencieusement le catalogue en tâche de fond, sans
        attendre une action de l'utilisateur — `actualiser()` n'affiche
        d'erreur que dans le bandeau de statut, jamais de popup, donc sans
        gêne si le réseau est momentanément coupé."""
        if self.api is not None:
            self.actualiser()
        self.after(_INTERVALLE_AUTO_ACTUALISATION_MS, self._auto_actualiser)

    def _ouvrir_config(self, obligatoire: bool = False) -> None:
        dialogue = FenetreConfig(self, self.config)
        self.wait_window(dialogue)
        if dialogue.resultat is not None:
            self.config = dialogue.resultat
            sauvegarder(self.config)
            self.api = ApiStockClient(self.config)
            self.actualiser()
        elif obligatoire:
            messagebox.showwarning(
                t("client_connexion_requise"), t("stock_connexion_requise_msg"))

    # Langue --------------------------------------------------------------
    def _changer_langue(self, _evenement=None) -> None:
        nom_choisi = self._combo_langue.get()
        for code in _LANGUES_STOCK:
            if translations.NOMS_LANGUES[code] == nom_choisi:
                translations.definir_langue_memoire(code)
                self.config.langue = code
                sauvegarder(self.config)
                break
        for enfant in self.winfo_children():
            enfant.destroy()
        self._construire()
        self.actualiser()

    # Construction ----------------------------------------------------------
    def _construire(self) -> None:
        self.title(t("stock_titre"))

        entete = ttk.Frame(self, padding=theme.PAD)
        entete.pack(fill="x")
        ttk.Label(entete, text=t("stock_titre"), style="Titre.TLabel").pack(side="left")
        ttk.Button(entete, text=t("client_connexion"),
                  command=self._ouvrir_config).pack(side="right")
        ttk.Button(entete, text=t("client_actualiser"), style="Accent.TButton",
                  command=self.actualiser).pack(side="right", padx=(0, 8))
        ttk.Button(entete, text=t("stock_bouton_nouveau_produit"),
                  command=self._ouvrir_nouveau_produit).pack(side="right", padx=(0, 8))
        self._bouton_renvoyer = ttk.Button(
            entete, text="", command=self._renvoyer_operations_en_attente,
            state="disabled")
        self._bouton_renvoyer.pack(side="right", padx=(0, 8))
        self._combo_langue = ttk.Combobox(
            entete, state="readonly", width=10,
            values=[translations.NOMS_LANGUES[code] for code in _LANGUES_STOCK],
        )
        self._combo_langue.set(translations.NOMS_LANGUES[translations.langue_active()])
        self._combo_langue.pack(side="right", padx=(0, 8))
        self._combo_langue.bind("<<ComboboxSelected>>", self._changer_langue)

        recherche = ttk.Frame(self, padding=(theme.PAD, 0))
        recherche.pack(fill="x")
        ttk.Label(recherche, text=t("stock_rechercher")).pack(side="left")
        self.var_recherche = tk.StringVar()
        self.var_recherche.trace_add("write", lambda *_: self._filtrer())
        ttk.Entry(recherche, textvariable=self.var_recherche, width=36).pack(
            side="left", padx=(4, 0))

        self._statut = ttk.Label(self, text="", style="Secondaire.TLabel",
                                 padding=(theme.PAD, 4))
        self._statut.pack(fill="x")

        corps = ttk.PanedWindow(self, orient="horizontal")
        corps.pack(fill="both", expand=True, padx=theme.PAD, pady=(0, theme.PAD))

        cadre_produits = ttk.Frame(corps)
        # Le prix est un réglage exclusif de l'app Facturation (voir
        # CLAUDE.md, section « Gestion de stock ») — volontairement absent
        # d'ici, même en lecture.
        colonnes = ("nom", "type_option", "valeur_option", "quantite")
        self._table = ttk.Treeview(cadre_produits, columns=colonnes, show="headings",
                                   selectmode="browse")
        titres = {"nom": t("cli_nom"), "type_option": t("stock_colonne_option"),
                 "valeur_option": t("stock_colonne_valeur"),
                 "quantite": t("stock_colonne_quantite")}
        for cle in colonnes:
            self._table.heading(cle, text=titres[cle])
        self._table.column("nom", width=220)
        self._table.column("type_option", width=100, anchor="center")
        self._table.column("valeur_option", width=100, anchor="center")
        self._table.column("quantite", width=90, anchor="e")
        theme.configurer_lignes_alternees(self._table)
        self._table.tag_configure("stock_negatif", foreground=theme.COULEURS["danger"])
        self._table.bind("<<TreeviewSelect>>", lambda _e: self._selection_changee())
        self._table.pack(fill="both", expand=True, side="left")
        defilement = ttk.Scrollbar(cadre_produits, orient="vertical",
                                   command=self._table.yview)
        self._table.configure(yscrollcommand=defilement.set)
        defilement.pack(fill="y", side="right")
        corps.add(cadre_produits, weight=2)

        cadre_detail = ttk.Frame(corps, padding=(theme.PAD, 0))
        boutons = ttk.Frame(cadre_detail)
        boutons.pack(fill="x", pady=(0, theme.PAD_S))
        self._bouton_entree = ttk.Button(
            boutons, text=t("stock_bouton_entree"), style="Accent.TButton",
            command=self._ouvrir_entree, state="disabled")
        self._bouton_entree.pack(fill="x")
        self._bouton_ajustement = ttk.Button(
            boutons, text=t("stock_bouton_ajustement"),
            command=self._ouvrir_ajustement, state="disabled")
        self._bouton_ajustement.pack(fill="x", pady=(theme.PAD_S, 0))
        self._bouton_modifier = ttk.Button(
            boutons, text=t("stock_bouton_modifier_produit"),
            command=self._ouvrir_modifier_produit, state="disabled")
        self._bouton_modifier.pack(fill="x", pady=(theme.PAD_S, 0))
        self._bouton_supprimer = ttk.Button(
            boutons, text=t("stock_bouton_supprimer_produit"), style="Danger.TButton",
            command=self._supprimer_produit, state="disabled")
        self._bouton_supprimer.pack(fill="x", pady=(theme.PAD_S, 0))

        ttk.Label(cadre_detail, text=t("stock_historique_titre"),
                  style="SousTitre.TLabel").pack(anchor="w", pady=(theme.PAD, 4))
        self._historique = DataTable(cadre_detail, [
            ("date", t("stock_colonne_date"), 110, "center"),
            ("type", t("stock_colonne_type"), 80, "center"),
            ("quantite", t("stock_colonne_quantite"), 70, "e"),
            ("reference", t("stock_colonne_reference"), 110, "w"),
            ("source", t("stock_colonne_source"), 80, "center"),
        ], hauteur=14)
        self._historique.pack(fill="both", expand=True)
        corps.add(cadre_detail, weight=1)

    # Données -----------------------------------------------------------------
    def actualiser(self) -> None:
        """Rafraîchit le catalogue depuis le serveur. En cas de coupure
        réseau (`ErreurInjoignable`), bascule sur le dernier catalogue mis en
        cache (voir `cache_catalogue.py`) plutôt que d'afficher une simple
        erreur — c'est ce qui permet à l'app Stock de rester consultable
        hors ligne (voir CLAUDE.md, section « App Stock — mode hors ligne »).
        Un jeton refusé ou une autre erreur applicative n'est PAS une
        coupure réseau : pas de bascule silencieuse sur le cache dans ces
        cas, l'erreur reste affichée telle quelle."""
        if self.api is None:
            return
        try:
            self._produits = self.api.lister_produits()
        except ErreurInjoignable:
            self._basculer_sur_cache()
            return
        except ErreurAuthentification:
            self._statut.configure(text=t("client_jeton_refuse"),
                                   foreground=theme.COULEURS["danger"])
            return
        except ErreurApiStock as exc:
            self._statut.configure(text=str(exc), foreground=theme.COULEURS["danger"])
            return
        cache_catalogue.sauvegarder(self._produits)
        self._renvoyer_operations_en_attente(afficher_resultat=False)
        self._statut.configure(text="")
        self._filtrer()
        self._maj_bouton_renvoyer()

    def _basculer_sur_cache(self) -> None:
        """Serveur injoignable : utilise le catalogue en cache s'il existe
        (mode dégradé, lecture seule pour l'historique — les entrées/
        ajustements restent possibles, voir `_ouvrir_entree`/`_ouvrir_ajustement`),
        sinon conserve le message d'erreur réseau habituel."""
        produits, horodatage = cache_catalogue.charger()
        if not produits:
            self._statut.configure(text=t("client_injoignable"),
                                   foreground=theme.COULEURS["danger"])
            return
        self._produits = produits
        try:
            horodatage_affiche = datetime.fromisoformat(horodatage).strftime(
                "%d/%m/%Y %H:%M")
        except ValueError:
            horodatage_affiche = horodatage
        self._statut.configure(
            text=t("stock_hors_ligne_cache").format(horodatage_affiche),
            foreground=theme.COULEURS["danger"])
        self._filtrer()
        self._maj_bouton_renvoyer()

    # Mode hors ligne (file d'attente locale) ----------------------------------
    def _maj_bouton_renvoyer(self) -> None:
        n = len(queue_hors_ligne.charger())
        self._bouton_renvoyer.configure(
            text=t("stock_operations_en_attente_bouton").format(n),
            state="normal" if n else "disabled")

    def _renvoyer_operations_en_attente(self, afficher_resultat: bool = True) -> None:
        """Rejoue dans l'ordre les opérations enregistrées hors ligne.
        Appelée silencieusement à chaque rafraîchissement réussi (`actualiser`,
        y compris le cycle automatique toutes les 15 s) et, pour un retour
        immédiat, par le bouton dédié (`afficher_resultat=True`)."""
        if self.api is None:
            return
        items = queue_hors_ligne.charger()
        if not items:
            if afficher_resultat:
                messagebox.showinfo(t("stock_operations_en_attente_titre"),
                                    t("stock_aucune_operation_attente"))
            return
        reussies = 0
        for index in range(len(items) - 1, -1, -1):
            item = items[index]
            try:
                if item.type_operation == "entree":
                    self.api.entrer_stock(item.produit_id, item.quantite, item.note)
                else:
                    self.api.ajuster_stock(item.produit_id, item.quantite, item.note)
            except ErreurApiStock:
                continue
            queue_hors_ligne.retirer(index)
            reussies += 1
        self._maj_bouton_renvoyer()
        if reussies:
            # Reflète les quantités mises à jour côté serveur sans attendre
            # le prochain cycle automatique.
            try:
                self._produits = self.api.lister_produits()
                cache_catalogue.sauvegarder(self._produits)
                self._filtrer()
            except ErreurApiStock:
                pass
        if afficher_resultat:
            messagebox.showinfo(
                t("stock_operations_en_attente_titre"),
                t("stock_operations_envoyees").format(reussies, len(items)))

    def _filtrer(self) -> None:
        # Conserve la sélection courante (id de produit) à travers le
        # rafraîchissement périodique (voir `_auto_actualiser`), pour ne pas
        # interrompre un usager qui s'apprête à cliquer sur Entrée/Ajustement.
        selection_precedente = self._table.selection()
        termes = decouper_termes(self.var_recherche.get())
        produits = [
            p for p in self._produits
            if not termes or correspond(p["nom"], termes)
            or correspond(p.get("valeur_option", ""), termes)
        ]
        self._table.delete(*self._table.get_children())
        self._produits_affiches = {}
        for indice, p in enumerate(produits):
            iid = str(p["id"])
            self._produits_affiches[iid] = p
            tags = [theme.tag_alternance(indice)]
            if p["quantite_stock"] < 0:
                tags.append("stock_negatif")
            self._table.insert(
                "", "end", iid=iid, tags=tuple(tags),
                values=(p["nom"], p.get("type_option", ""), p.get("valeur_option", ""),
                       format_nombre(p["quantite_stock"])),
            )
        if selection_precedente and selection_precedente[0] in self._produits_affiches:
            self._table.selection_set(selection_precedente[0])
        self._selection_changee()

    def _produit_selectionne(self) -> dict | None:
        selection = self._table.selection()
        if not selection:
            return None
        return self._produits_affiches.get(selection[0])

    def _selection_changee(self) -> None:
        produit = self._produit_selectionne()
        etat = "normal" if produit is not None else "disabled"
        self._bouton_entree.configure(state=etat)
        self._bouton_ajustement.configure(state=etat)
        self._bouton_modifier.configure(state=etat)
        self._bouton_supprimer.configure(state=etat)
        self._historique.vider()
        if produit is not None and self.api is not None:
            self._charger_historique(produit["id"])

    def _charger_historique(self, produit_id: int) -> None:
        try:
            mouvements = self.api.historique(produit_id)
        except ErreurApiStock as exc:
            self._statut.configure(text=str(exc), foreground=theme.COULEURS["danger"])
            return
        self._historique.vider()
        if not mouvements:
            self._historique.ajouter(["", t("stock_historique_vide"), "", "", ""])
            return
        for m in mouvements:
            type_libelle = t(_LIBELLES_TYPE.get(m["type_mouvement"], "")) \
                or m["type_mouvement"]
            source_libelle = t(_LIBELLES_SOURCE.get(m["source"], "")) or m["source"]
            self._historique.ajouter([
                format_date(m["cree_le"]), type_libelle,
                format_nombre(m["quantite"]), m.get("reference", ""), source_libelle,
            ])

    # Actions -------------------------------------------------------------
    def _ouvrir_nouveau_produit(self) -> None:
        if self.api is None:
            return
        dialogue = DialogueNouveauProduit(self)
        if dialogue.resultat is None:
            return
        nom, type_option, valeur_option = dialogue.resultat
        try:
            self.api.creer_produit(nom, type_option, valeur_option)
        except ErreurPermission:
            messagebox.showerror(t("client_action_refusee_titre"), t("client_action_refusee_msg"))
            return
        except ErreurApiStock as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("stock_produit_cree"))
        self.actualiser()

    def _ouvrir_modifier_produit(self) -> None:
        produit = self._produit_selectionne()
        if produit is None or self.api is None:
            messagebox.showinfo(t("client_selection_titre"), t("stock_selection_produit_msg"))
            return
        dialogue = DialogueModifierProduit(self, produit)
        if dialogue.resultat is None:
            return
        nom, type_option, valeur_option = dialogue.resultat
        try:
            self.api.modifier_produit(produit["id"], nom, type_option, valeur_option)
        except ErreurPermission:
            messagebox.showerror(t("client_action_refusee_titre"), t("client_action_refusee_msg"))
            return
        except ErreurApiStock as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("stock_produit_modifie"))
        self.actualiser()

    def _supprimer_produit(self) -> None:
        produit = self._produit_selectionne()
        if produit is None or self.api is None:
            messagebox.showinfo(t("client_selection_titre"), t("stock_selection_produit_msg"))
            return
        libelle = f"{produit['nom']} {produit.get('valeur_option', '')}".strip()
        if not messagebox.askyesno(t("confirmer"),
                                   t("stock_supprimer_confirmation").format(libelle)):
            return
        try:
            self.api.supprimer_produit(produit["id"])
        except ErreurPermission:
            messagebox.showerror(t("client_action_refusee_titre"), t("client_action_refusee_msg"))
            return
        except ErreurApiStock as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("stock_produit_supprime"))
        self.actualiser()

    def _ouvrir_entree(self) -> None:
        produit = self._produit_selectionne()
        if produit is None or self.api is None:
            messagebox.showinfo(t("client_selection_titre"), t("stock_selection_produit_msg"))
            return
        dialogue = DialogueEntreeStock(self)
        if dialogue.resultat is None:
            return
        quantite, note = dialogue.resultat
        try:
            self.api.entrer_stock(produit["id"], quantite, note)
        except ErreurPermission:
            messagebox.showerror(t("client_action_refusee_titre"), t("client_action_refusee_msg"))
            return
        except ErreurInjoignable:
            self._proposer_mise_en_attente("entree", produit["id"], quantite, note)
            return
        except ErreurApiStock as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("stock_mouvement_enregistre"))
        self.actualiser()

    def _ouvrir_ajustement(self) -> None:
        produit = self._produit_selectionne()
        if produit is None or self.api is None:
            messagebox.showinfo(t("client_selection_titre"), t("stock_selection_produit_msg"))
            return
        dialogue = DialogueAjustementStock(self)
        if dialogue.resultat is None:
            return
        delta, motif = dialogue.resultat
        try:
            self.api.ajuster_stock(produit["id"], delta, motif)
        except ErreurPermission:
            messagebox.showerror(t("client_action_refusee_titre"), t("client_action_refusee_msg"))
            return
        except ErreurInjoignable:
            self._proposer_mise_en_attente("ajustement", produit["id"], delta, motif)
            return
        except ErreurApiStock as exc:
            messagebox.showerror(t("erreur"), str(exc))
            return
        afficher_toast(self, t("stock_mouvement_enregistre"))
        self.actualiser()

    def _proposer_mise_en_attente(
        self, type_operation: str, produit_id: int, quantite: int, note: str,
    ) -> None:
        """Serveur injoignable au moment de l'entrée/ajustement : propose de
        l'enregistrer localement pour synchronisation automatique au retour
        du réseau (même UX que les versements hors ligne de l'app Client,
        voir `app/client/ui.py._ajouter_versement`)."""
        if messagebox.askyesno(t("client_hors_ligne_titre"),
                               t("stock_operation_hors_ligne_confirmation")):
            queue_hors_ligne.ajouter(type_operation, produit_id, quantite, note)
            self._maj_bouton_renvoyer()
            afficher_toast(self, t("stock_operation_en_attente_ajoutee"))


def lancer() -> None:
    ApplicationStock().mainloop()
