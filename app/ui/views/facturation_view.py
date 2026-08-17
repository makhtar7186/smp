"""Vue Facturation : panier de lignes, enregistrement, PDF, bouton Nouvelle facture."""
from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import messagebox, ttk

from app import config
from app.i18n.translations import t
from app.models import LigneVente
from app.repositories.client_repository import ClientRepository
from app.repositories.produit_repository import ProduitRepository
from app.ui import theme
from app.ui.components.autocomplete import AutocompleteEntry
from app.ui.components.champ_date import ChampDate
from app.ui.components.data_table import DataTable
from app.ui.components.toast import afficher_toast
from app.utils.fichiers import ouvrir_fichier
from app.utils.formatting import (
    format_date,
    format_fcfa,
    format_nombre,
    libelle_client,
    parse_date_affichage,
)
from app.utils.validation import (
    ErreurValidation,
    valider_entier_positif,
    valider_nombre_positif,
)


class FacturationView(ttk.Frame):
    """Écran de création de facture.

    Cycle validé avec le propriétaire : Enregistrer/PDF ne vident pas le
    panier ; seul « Nouvelle facture » vide et incrémente le numéro. La TVA
    (`config.TVA_TAUX_DEFAUT`) est toujours active — jamais une case à
    cocher ni un taux saisi ici, le service l'applique automatiquement.
    """

    def __init__(self, parent: tk.Misc, application) -> None:
        super().__init__(parent)
        self.app = application
        self._clients_repo = ClientRepository(application.conn)
        self._produits_repo = ProduitRepository(application.conn)
        self._lignes: list[LigneVente] = []
        self._facture_enregistree_id: int | None = None
        self._produit_choisi = None
        self._indice_edition: int | None = None
        self._edition_facture_id: int | None = None
        self._edition_proforma_id: int | None = None
        # Numéro suggéré (palier 1, voir `_definir_numero_suggere`) — permet
        # de savoir, au moment d'Enregistrer, si l'usager a modifié le champ
        # à la main depuis la suggestion (auquel cas la confirmation
        # silencieuse ne doit jamais l'écraser, voir `_enregistrer`).
        self._numero_suggere: int | None = None
        # Quantité déjà « sortie » du stock par produit dans LA FACTURE
        # ENREGISTRÉE en cours de correction (voir `charger_pour_edition`) —
        # cette quantité sera de toute façon restituée puis réappliquée par
        # `FactureRepository.modifier`, donc le stock réellement disponible
        # pour cette édition est `quantite_stock + ce montant`, jamais
        # peuplé pour une facture neuve ou un brouillon (aucune sortie
        # encore actée) — voir `_verifier_stock_disponible`.
        self._quantites_originales_facture: dict[int, float] = {}
        self._construire()

    # Construction ------------------------------------------------------------
    def _construire(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        self._label_titre = ttk.Label(self, text=t("fact_titre"), style="Titre.TLabel")
        self._label_titre.grid(
            row=0, column=0, sticky="w", padx=theme.PAD_L, pady=(theme.PAD_L, theme.PAD)
        )

        # Bandeau visible uniquement en mode édition d'une facture existante
        self._bandeau_edition = tk.Label(
            self, text="", bg=theme.COULEURS["accent_clair"],
            fg=theme.COULEURS["accent_sombre"], font=theme.POLICES["normal"],
            anchor="w", padx=theme.PAD, pady=6)
        self._bandeau_edition.grid(row=1, column=0, sticky="ew",
                                   padx=theme.PAD_L, pady=(0, theme.PAD))
        self._bandeau_edition.grid_remove()

        # --- En-tête facture -------------------------------------------------
        entete = tk.Frame(self, bg=theme.COULEURS["carte"],
                          highlightthickness=1,
                          highlightbackground=theme.COULEURS["bordure"])
        entete.grid(row=2, column=0, sticky="ew", padx=theme.PAD_L)
        for colonne in range(11):
            entete.columnconfigure(colonne, weight=1 if colonne % 2 else 0)

        self.var_numero = tk.StringVar()
        self.var_date = tk.StringVar(value=format_date(date.today()))
        self.var_client = tk.StringVar()
        self.var_destination = tk.StringVar()

        champs = [
            (t("fact_numero"), self.var_numero, 10),
            (t("fact_date"), self.var_date, 12),
            (t("fact_client"), self.var_client, 24),
            (t("fact_destination"), self.var_destination, 18),
        ]
        for indice, (libelle, variable, largeur) in enumerate(champs):
            tk.Label(entete, text=libelle, bg=theme.COULEURS["carte"],
                     font=theme.POLICES["petit"],
                     fg=theme.COULEURS["texte_secondaire"]).grid(
                row=0, column=indice * 2, sticky="w",
                padx=(theme.PAD, 4), pady=theme.PAD)
            if libelle == t("fact_client"):
                self._champ_client = AutocompleteEntry(
                    entete, largeur=largeur, textvariable=variable,
                    on_select=self._choisir_client)
                self._champ_client.grid(row=0, column=indice * 2 + 1, sticky="ew",
                                        padx=(0, theme.PAD), pady=theme.PAD)
            elif libelle == t("fact_date"):
                ChampDate(entete, largeur=largeur, textvariable=variable).grid(
                    row=0, column=indice * 2 + 1, sticky="w",
                    padx=(0, theme.PAD), pady=theme.PAD)
            else:
                ttk.Entry(entete, textvariable=variable, width=largeur).grid(
                    row=0, column=indice * 2 + 1, sticky="ew",
                    padx=(0, theme.PAD), pady=theme.PAD)

        # Remise propre à cette facture (distincte de la remise annuelle) —
        # placée dans l'en-tête existant plutôt que dans une ligne dédiée,
        # pour ne pas réduire la hauteur disponible au panier en dessous.
        self.var_remise_active = tk.BooleanVar(value=False)
        self.var_remise_taux = tk.StringVar()
        ttk.Checkbutton(entete, text=t("fact_remise_appliquer"),
                        variable=self.var_remise_active,
                        command=self._remise_modifiee).grid(
            row=0, column=8, sticky="w", padx=(theme.PAD, 4), pady=theme.PAD)
        tk.Label(entete, text=t("fact_remise_taux"), bg=theme.COULEURS["carte"],
                 font=theme.POLICES["petit"],
                 fg=theme.COULEURS["texte_secondaire"]).grid(
            row=0, column=9, sticky="w", padx=(0, 4), pady=theme.PAD)
        ttk.Entry(entete, textvariable=self.var_remise_taux, width=6).grid(
            row=0, column=10, sticky="w", padx=(0, theme.PAD), pady=theme.PAD)
        self.var_remise_taux.trace_add("write", lambda *_: self._remise_modifiee())

        # Téléphone (préempli depuis la fiche client, voir `_choisir_client`)
        # et matricule du véhicule de livraison (jamais préempli, propre à
        # chaque livraison) — deuxième ligne d'en-tête, imprimés sous
        # Client/Destination sur facture et bordereau (voir CLAUDE.md,
        # section « Téléphone et matricule »).
        self.var_telephone = tk.StringVar()
        self.var_matricule = tk.StringVar()
        champs_livraison = [
            (t("fact_telephone"), self.var_telephone, 18),
            (t("fact_matricule"), self.var_matricule, 18),
        ]
        for indice, (libelle, variable, largeur) in enumerate(champs_livraison):
            tk.Label(entete, text=libelle, bg=theme.COULEURS["carte"],
                     font=theme.POLICES["petit"],
                     fg=theme.COULEURS["texte_secondaire"]).grid(
                row=1, column=indice * 2, sticky="w",
                padx=(theme.PAD, 4), pady=(0, theme.PAD))
            ttk.Entry(entete, textvariable=variable, width=largeur).grid(
                row=1, column=indice * 2 + 1, sticky="ew",
                padx=(0, theme.PAD), pady=(0, theme.PAD))

        # --- Corps : saisie de ligne + panier -------------------------------
        corps = ttk.Frame(self)
        corps.grid(row=3, column=0, sticky="nsew", padx=theme.PAD_L, pady=theme.PAD)
        corps.columnconfigure(1, weight=1)
        corps.rowconfigure(0, weight=1)

        self._construire_saisie_ligne(corps)
        self._construire_panier(corps)

        # --- Barre d'actions ---------------------------------------------------
        # Total et boutons sur deux lignes distinctes (plutôt que côte à côte
        # dans un même pack) : un total long (remise, gros montant) ne peut
        # ainsi jamais empiéter visuellement sur les boutons, quelle que soit
        # la largeur de la fenêtre.
        actions = ttk.Frame(self)
        actions.grid(row=4, column=0, sticky="ew", padx=theme.PAD_L,
                     pady=(0, theme.PAD_L))
        actions.columnconfigure(0, weight=1)
        self._label_total = ttk.Label(actions, text="", style="Titre.TLabel")
        self._label_total.grid(row=0, column=0, sticky="w", pady=(0, theme.PAD_S))

        barre_boutons = ttk.Frame(actions)
        barre_boutons.grid(row=1, column=0, sticky="ew")
        ttk.Button(barre_boutons, text=t("fact_nouvelle"), style="Danger.TButton",
                   command=self._nouvelle_facture).pack(side="right", padx=(8, 0))
        ttk.Button(barre_boutons, text="🧹 " + t("fact_effacer"),
                   command=self._effacer_facture).pack(side="right", padx=(8, 0))
        self._bouton_bordereau = ttk.Button(
            barre_boutons, text=t("fact_bordereau"), command=self._exporter_bordereau)
        self._bouton_bordereau.pack(side="right", padx=(8, 0))
        ttk.Button(barre_boutons, text=t("fact_imprimer"),
                   command=self._exporter_pdf).pack(side="right", padx=(8, 0))
        self._bouton_enregistrer = ttk.Button(
            barre_boutons, text=t("fact_enregistrer"), style="Accent.TButton",
            command=self._enregistrer)
        self._bouton_enregistrer.pack(side="right", padx=(8, 0))
        self._bouton_brouillon = ttk.Button(
            barre_boutons, text="📝 " + t("fact_save_brouillon"),
            command=self._enregistrer_brouillon)
        self._bouton_brouillon.pack(side="right", padx=(8, 0))
        self._maj_total()

    def _construire_saisie_ligne(self, parent: ttk.Frame) -> None:
        """Formulaire d'ajout d'une ligne au panier (colonne de gauche)."""
        cadre = tk.Frame(parent, bg=theme.COULEURS["carte"],
                         highlightthickness=1,
                         highlightbackground=theme.COULEURS["bordure"])
        cadre.grid(row=0, column=0, sticky="ns", padx=(0, theme.PAD))

        ttk.Label(cadre, text=t("fact_ajouter_ligne"),
                  style="SousTitre.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w",
            padx=theme.PAD, pady=(theme.PAD, theme.PAD_S))

        self.var_produit = tk.StringVar()
        self.var_designation = tk.StringVar()
        self.var_quantite = tk.StringVar()
        self.var_prix = tk.StringVar()
        self._erreur_ligne = tk.StringVar()

        rang = 1

        def champ(libelle: str, widget: tk.Widget) -> None:
            nonlocal rang
            tk.Label(cadre, text=libelle, bg=theme.COULEURS["carte"],
                     font=theme.POLICES["petit"],
                     fg=theme.COULEURS["texte_secondaire"]).grid(
                row=rang, column=0, sticky="w", padx=theme.PAD, pady=(4, 0))
            widget.grid(row=rang + 1, column=0, columnspan=2, sticky="ew",
                        padx=theme.PAD)
            rang += 2

        self._champ_produit = AutocompleteEntry(
            cadre, largeur=30, textvariable=self.var_produit,
            on_select=self._choisir_produit,
        )
        champ(t("fact_produit"), self._champ_produit)
        champ(t("fact_designation"),
              ttk.Entry(cadre, textvariable=self.var_designation, width=32))
        champ(t("fact_quantite"),
              ttk.Entry(cadre, textvariable=self.var_quantite, width=10))
        champ(t("fact_prix_unitaire"),
              ttk.Entry(cadre, textvariable=self.var_prix, width=14))

        tk.Label(cadre, textvariable=self._erreur_ligne,
                 bg=theme.COULEURS["carte"], fg=theme.COULEURS["danger"],
                 font=theme.POLICES["petit"], wraplength=220, justify="left").grid(
            row=rang, column=0, columnspan=2, sticky="w", padx=theme.PAD)
        self._bouton_ajouter = ttk.Button(
            cadre, text="＋ " + t("fact_ajouter_ligne"),
            style="Accent.TButton", command=self._ajouter_ligne)
        self._bouton_ajouter.grid(
            row=rang + 1, column=0, columnspan=2, sticky="ew",
            padx=theme.PAD, pady=theme.PAD)

    def _construire_panier(self, parent: ttk.Frame) -> None:
        """Tableau du panier (colonne de droite)."""
        droite = ttk.Frame(parent)
        droite.grid(row=0, column=1, sticky="nsew")
        droite.rowconfigure(0, weight=1)
        droite.columnconfigure(0, weight=1)
        self._table = DataTable(droite, [
            ("no", t("fact_no_article"), 45, "center"),
            ("quantite", t("fact_quantite"), 80, "center"),
            ("designation", t("fact_designation"), 300, "w"),
            ("pu", t("fact_prix_unitaire"), 110, "e"),
            ("total", t("fact_prix_total"), 120, "e"),
        ])
        self._table.grid(row=0, column=0, sticky="nsew")
        self._table.tree.configure(selectmode="extended")
        self._table.tree.bind("<Double-1>", lambda _e: self._editer_ligne())
        boutons = ttk.Frame(droite)
        boutons.grid(row=1, column=0, sticky="e", pady=(theme.PAD_S, 0))
        ttk.Button(boutons, text="✎ " + t("fact_modifier_ligne"),
                   command=self._editer_ligne).pack(side="left", padx=(0, 8))
        ttk.Button(boutons, text="🗑 " + t("fact_retirer_ligne"),
                   command=self._retirer_ligne).pack(side="left")

    # Rafraîchissement --------------------------------------------------------
    def rafraichir(self) -> None:
        """Recharge clients/produits et propose le prochain numéro si panier neuf."""
        self._clients = self._clients_repo.lister()
        # Étiquette "NOM — adresse" pour distinguer les clients homonymes
        self._clients_par_libelle = {libelle_client(c): c for c in self._clients}
        self._champ_client.definir_valeurs(list(self._clients_par_libelle))
        self._produits = self._produits_repo.lister(actifs_seulement=True)
        # Libellé court pour la recherche, ex. "BIDON 5L"
        self._produits_par_libelle = {p.libelle_recherche: p for p in self._produits}
        self._champ_produit.definir_valeurs(list(self._produits_par_libelle))
        if not self.var_numero.get():
            self.var_numero.set(self._definir_numero_suggere())

    def _definir_numero_suggere(self) -> str:
        """Numéro proposé, sans jamais bloquer ni interroger l'usager (palier
        1 final — voir CLAUDE.md, section « Numérotation résiliente ») : sur
        la machine de facturation, `suggerer_numero()` est instantané (aucun
        réseau, `base_connu + 1` maintenu à jour en arrière-plan par
        `NumeroPollerWorker`) ; sur le boss, simple MAX+1. Le numéro retourné
        reste figé pour cette facture jusqu'à la confirmation silencieuse au
        moment de l'enregistrement (voir `_confirmer_numero_si_necessaire`)."""
        if hasattr(self.app, "numero_resilient"):
            try:
                numero = self.app.numero_resilient.suggerer_numero()
            except Exception:
                self._numero_suggere = None
                return ""
            self._numero_suggere = numero
            return str(numero)
        self._numero_suggere = None
        try:
            return str(self.app.facturation.prochain_numero())
        except ErreurValidation:
            return ""

    # Callbacks ---------------------------------------------------------------
    def _choisir_client(self, libelle: str) -> None:
        """Client existant choisi (parmi d'éventuels homonymes) : fixe son nom
        exact et reprend son adresse connue, sans écraser une destination
        déjà saisie pour cette facture."""
        client = getattr(self, "_clients_par_libelle", {}).get(libelle)
        if client is None:
            return
        self.var_client.set(client.nom)  # nettoie le suffixe "— adresse"
        if not self.var_destination.get().strip() and client.adresse:
            self.var_destination.set(client.adresse)
        if not self.var_telephone.get().strip() and client.telephone:
            self.var_telephone.set(client.telephone)

    def _choisir_produit(self, libelle: str) -> None:
        """Pré-remplit désignation et prix depuis le produit choisi."""
        produit = self._produits_par_libelle.get(libelle)
        self._produit_choisi = produit
        if produit is not None:
            self.var_designation.set(produit.designation)
            self.var_prix.set(str(produit.prix))
            self._produit_choisi_id = produit.id
        else:
            self._produit_choisi_id = None

    def _ajouter_ligne(self) -> None:
        """Valide la saisie et ajoute la ligne au panier."""
        self._erreur_ligne.set("")
        try:
            designation = self.var_designation.get().strip()
            if not designation:
                raise ErreurValidation("champ_obligatoire")
            quantite = valider_nombre_positif(self.var_quantite.get(), strict=True)
            prix = valider_entier_positif(self.var_prix.get())
        except ErreurValidation as erreur:
            self._erreur_ligne.set(t(erreur.cle_message))
            return
        produit_id = getattr(self, "_produit_choisi_id", None)
        if produit_id is None:
            produit_id = self._resoudre_produit_id(designation)
        if produit_id is None:
            self._erreur_ligne.set(t("fact_produit_inconnu"))
            return
        if not self._verifier_stock_disponible(produit_id, quantite):
            return
        ligne = LigneVente(
            produit_id=produit_id,
            designation=designation, quantite=quantite, prix_unitaire=prix,
        )
        if self._indice_edition is not None:
            self._lignes[self._indice_edition] = ligne
            self._quitter_mode_edition()
            self._redessiner_panier()
        else:
            self._lignes.append(ligne)
            self._table.ajouter([
                len(self._lignes),
                format_nombre(ligne.quantite), ligne.designation,
                format_fcfa(ligne.prix_unitaire, False),
                format_fcfa(ligne.total, False),
            ])
        self._vider_formulaire_ligne()
        self._facture_enregistree_id = None  # panier modifié → à ré-enregistrer
        self._maj_total()

    def _resoudre_produit_id(self, designation: str) -> int | None:
        """Retrouve l'id du produit du catalogue dont la désignation
        correspond exactement (comparaison insensible à la casse) à la
        désignation saisie, pour accepter une saisie manuelle du nom sans
        passer par la liste déroulante. La création de produit n'est plus
        possible depuis la facturation (voir CLAUDE.md, section « Gestion de
        stock ») : une désignation sans correspondance est refusée par
        l'appelant plutôt que de créer un nouvel article à la volée."""
        designation_normalisee = designation.strip().upper()
        for produit in self._produits_repo.lister():
            if produit.designation.strip().upper() == designation_normalisee:
                return produit.id
        return None

    def _verifier_stock_disponible(self, produit_id: int, quantite: float) -> bool:
        """Vérifie que la quantité totale demandée pour ce produit (déjà dans
        le panier + la ligne en cours de saisie) ne dépasse pas le stock
        disponible. Lit le stock directement en base (plutôt que le cache
        `self._produits` chargé par `rafraichir()`) pour rester au plus près
        de la quantité réelle.

        En correction d'une facture déjà enregistrée, le stock « disponible »
        n'est pas seulement `quantite_stock` : cette facture a déjà sorti
        `_quantites_originales_facture[produit_id]` unités, restituées puis
        réappliquées par `FactureRepository.modifier` au moment d'enregistrer
        — un retour partiel (ex. facture de 100, stock actuel 2, on corrige
        à 50 après un retour de 50 articles) doit donc être comparé à
        `2 + 100 = 102`, pas à 2 seul, sans quoi toute correction à la baisse
        d'une facture déjà tirée à zéro serait refusée à tort."""
        produit = self._produits_repo.obtenir(produit_id)
        if produit is None:
            return True
        deja_au_panier = sum(
            ligne.quantite for indice, ligne in enumerate(self._lignes)
            if ligne.produit_id == produit_id and indice != self._indice_edition
        )
        stock_disponible = (
            produit.quantite_stock + self._quantites_originales_facture.get(produit_id, 0)
        )
        if deja_au_panier + quantite > stock_disponible:
            self._erreur_ligne.set(
                t("fact_stock_insuffisant").format(format_nombre(stock_disponible))
            )
            return False
        return True

    def _vider_formulaire_ligne(self) -> None:
        """Vide le formulaire de saisie de ligne (pas l'en-tête client/destination)
        pour enchaîner rapidement l'ajout du produit suivant."""
        self._produit_choisi = None
        self._produit_choisi_id = None
        for variable in (self.var_produit, self.var_designation,
                         self.var_quantite, self.var_prix):
            variable.set("")
        self._champ_produit.focus_set()

    def _editer_ligne(self) -> None:
        """Charge la ligne sélectionnée dans le formulaire pour modification."""
        iid = self._table.selection_iid()
        if iid is None:
            return
        indice = self._table.tree.index(iid)
        ligne = self._lignes[indice]
        self._indice_edition = indice
        self._produit_choisi = None
        self._produit_choisi_id = ligne.produit_id
        self.var_designation.set(ligne.designation)
        self.var_quantite.set(format_nombre(ligne.quantite))
        self.var_prix.set(str(ligne.prix_unitaire))
        self._erreur_ligne.set("")
        self._bouton_ajouter.configure(text="✎ " + t("fact_modifier_ligne"))

    def _quitter_mode_edition(self) -> None:
        self._indice_edition = None
        self._bouton_ajouter.configure(text="＋ " + t("fact_ajouter_ligne"))

    def _retirer_ligne(self) -> None:
        iid = self._table.selection_iid()
        if iid is None:
            return
        indice = self._table.tree.index(iid)
        del self._lignes[indice]
        self._quitter_mode_edition()
        self._redessiner_panier()
        self._facture_enregistree_id = None
        self._maj_total()

    def _redessiner_panier(self) -> None:
        self._table.vider()
        for indice, ligne in enumerate(self._lignes, start=1):
            self._table.ajouter([
                indice,
                format_nombre(ligne.quantite), ligne.designation,
                format_fcfa(ligne.prix_unitaire, False),
                format_fcfa(ligne.total, False),
            ])

    def _remise_modifiee(self) -> None:
        """Rafraîchit le total affiché et invalide l'enregistrement précédent
        (la remise vient de changer, il faut ré-enregistrer avant d'exporter)."""
        self._facture_enregistree_id = None
        self._maj_total()

    def _taux_remise_affichage(self) -> float:
        """Taux de remise actuellement saisi, pour l'affichage en direct du
        total (0 si la case n'est pas cochée ou si la saisie n'est pas encore
        un nombre valide — pas d'erreur tant qu'on ne cherche pas à enregistrer)."""
        if not self.var_remise_active.get():
            return 0.0
        try:
            taux = float(self.var_remise_taux.get().strip().replace(",", "."))
        except (ValueError, AttributeError):
            return 0.0
        return taux if 0 <= taux <= 100 else 0.0

    def _taux_remise_pour_enregistrement(self) -> float | None:
        """Taux de remise à enregistrer ; None (+ message) si la case est
        cochée mais la saisie invalide."""
        if not self.var_remise_active.get():
            return 0.0
        try:
            taux = valider_nombre_positif(self.var_remise_taux.get())
        except ErreurValidation as erreur:
            messagebox.showerror(t("erreur"), t(erreur.cle_message))
            return None
        if taux > 100:
            messagebox.showerror(t("erreur"), t("fact_remise_invalide"))
            return None
        return taux

    def _maj_total(self) -> None:
        # Détail brut/remise/TVA réservé à la facture exportée (pdf_service) —
        # ici, un affichage compact évite de masquer les boutons d'action. La
        # TVA est toujours active (taux fixe, non modifiable ici) : le total
        # affiché passe donc toujours par la décomposition TTC.
        brut = sum(ligne.total for ligne in self._lignes)
        taux_remise = self._taux_remise_affichage()
        net = brut - round(brut * taux_remise / 100) if taux_remise else brut
        taux_tva = config.TVA_TAUX_DEFAUT
        self._label_total.configure(
            text=f"{t('fact_total_ttc')} ({taux_tva:g}% incl.) : {format_fcfa(net)}")

    # Actions principales -----------------------------------------------------
    def _lire_entete(self) -> tuple[int, date] | None:
        """Valide numéro et date de l'en-tête ; None si invalide (message affiché)."""
        try:
            numero = valider_entier_positif(self.var_numero.get(), strict=True)
        except ErreurValidation:
            messagebox.showerror(t("erreur"), t("nombre_invalide"))
            return None
        try:
            date_facture = parse_date_affichage(self.var_date.get())
        except ValueError:
            messagebox.showerror(t("erreur"), t("date_invalide"))
            return None
        return numero, date_facture

    def _confirmer_numero_si_necessaire(self, numero: int) -> int:
        """Palier 1 (confirmation silencieuse) : juste avant l'écriture
        réelle d'une NOUVELLE facture — seul endroit avec un vrai verrou
        serveur (voir CLAUDE.md, « Numérotation résiliente »). Jamais en
        correction d'une facture existante (son numéro est déjà acquis), et
        jamais si l'usager a modifié le champ à la main depuis la suggestion
        (une correction manuelle est utilisée telle quelle, jamais écrasée
        silencieusement). Échec/timeout → le numéro suggéré est gardé tel
        quel, jamais bloquant."""
        if not hasattr(self.app, "numero_resilient"):
            return numero
        if self._edition_facture_id is not None:
            return numero
        if numero != self._numero_suggere:
            return numero
        try:
            return self.app.numero_resilient.confirmer_numero(numero)
        except Exception:
            return numero

    def _enregistrer(self) -> None:
        """Enregistre la facture (nouvelle, ou modification si en cours
        d'édition). Ne vide PAS le panier."""
        entete = self._lire_entete()
        if entete is None:
            return
        numero, date_facture = entete
        remise_taux = self._taux_remise_pour_enregistrement()
        if remise_taux is None:
            return
        lignes = [LigneVente(**{
            "produit_id": ligne.produit_id,
            "designation": ligne.designation,
            "quantite": ligne.quantite,
            "prix_unitaire": ligne.prix_unitaire,
        }) for ligne in self._lignes]

        if self._edition_facture_id is not None:
            # Correction d'une facture existante : remplace en-tête + lignes,
            # ne crée jamais de nouvel enregistrement.
            try:
                facture = self.app.facturation.modifier_facture(
                    facture_id=self._edition_facture_id,
                    numero=numero, date_facture=date_facture,
                    nom_client=self.var_client.get(),
                    destination=self.var_destination.get(),
                    lignes=lignes,
                    remise_taux=remise_taux,
                    telephone=self.var_telephone.get().strip(),
                    matricule=self.var_matricule.get().strip(),
                )
            except ErreurValidation as erreur:
                messagebox.showerror(t("erreur"), t(erreur.cle_message))
                return
            afficher_toast(self,
                           f"{t('fact_modifications_enregistrees')} — N° {facture.numero}")
            self._quitter_mode_edition_facture()
            self._reinitialiser_panier()
            return

        numero = self._confirmer_numero_si_necessaire(numero)
        self.var_numero.set(str(numero))
        if self.app.facturation.numero_existe(numero):
            # Un numéro ne peut plus jamais être partagé par deux factures
            # (contrainte UNIQUE côté base, garde-fou final — voir CLAUDE.md,
            # « Numérotation résiliente ») : il n'existe qu'une seule sorte
            # de facture, donc plus aucune raison légitime de forcer un
            # doublon comme autrefois (factures usine/revendeur).
            messagebox.showerror(t("erreur"), t("fact_numero_existe"))
            return
        try:
            facture = self.app.facturation.enregistrer_facture(
                numero=numero,
                date_facture=date_facture,
                nom_client=self.var_client.get(),
                destination=self.var_destination.get(),
                lignes=lignes,
                remise_taux=remise_taux,
                telephone=self.var_telephone.get().strip(),
                matricule=self.var_matricule.get().strip(),
            )
        except ErreurValidation as erreur:
            messagebox.showerror(t("erreur"), t(erreur.cle_message))
            return
        # Le brouillon éventuellement chargé (ou sauvegardé plus tôt dans cette
        # session) n'est PAS supprimé : il ne l'est que via une action
        # explicite (« Valider » ou « Supprimer » depuis la page Proforma).
        # On se contente de quitter son mode d'édition, pour qu'un futur
        # « Enregistrer en brouillon » recrée un nouveau brouillon plutôt que
        # de modifier silencieusement celui-ci.
        self._edition_proforma_id = None
        self._facture_enregistree_id = facture.id
        afficher_toast(self, f"{t('fact_enregistree')} — N° {facture.numero}")

    # Brouillons (proforma) ----------------------------------------------------
    def _enregistrer_brouillon(self) -> None:
        """Enregistre (ou met à jour) le panier courant comme brouillon, sans
        numéro de facture — voir `ProformaService`."""
        if not self._lignes:
            messagebox.showwarning(t("attention"), t("fact_panier_vide"))
            return
        remise_taux = self._taux_remise_pour_enregistrement()
        if remise_taux is None:
            return
        lignes = [LigneVente(**{
            "designation": ligne.designation,
            "quantite": ligne.quantite,
            "prix_unitaire": ligne.prix_unitaire,
        }) for ligne in self._lignes]
        try:
            if self._edition_proforma_id is not None:
                self.app.proformas.modifier(
                    self._edition_proforma_id,
                    client_nom=self.var_client.get(),
                    destination=self.var_destination.get(),
                    lignes=lignes, remise_taux=remise_taux,
                    telephone=self.var_telephone.get().strip(),
                    matricule=self.var_matricule.get().strip(),
                )
                afficher_toast(self, t("fact_brouillon_mis_a_jour"))
            else:
                proforma = self.app.proformas.enregistrer(
                    client_nom=self.var_client.get(),
                    destination=self.var_destination.get(),
                    lignes=lignes, remise_taux=remise_taux,
                    telephone=self.var_telephone.get().strip(),
                    matricule=self.var_matricule.get().strip(),
                )
                self._edition_proforma_id = proforma.id
                afficher_toast(self, t("fact_brouillon_enregistre"))
        except ErreurValidation as erreur:
            messagebox.showerror(t("erreur"), t(erreur.cle_message))

    def charger_pour_edition_proforma(self, proforma) -> None:
        """Charge un brouillon existant dans le formulaire pour le corriger ou
        le compléter. Le numéro de facture affiché n'est qu'une suggestion :
        un brouillon n'en a pas tant qu'il n'est pas validé (page Proforma)."""
        self._edition_facture_id = None
        self._edition_proforma_id = proforma.id
        self.var_client.set(proforma.client_nom)
        self.var_destination.set(proforma.destination)
        self.var_telephone.set(proforma.telephone)
        self.var_matricule.set(proforma.matricule)
        self._lignes = list(proforma.lignes)
        # Un brouillon n'a jamais décrémenté le stock (voir CLAUDE.md, TVA/
        # proforma) : aucun « déjà sorti » à créditer lors de sa correction.
        self._quantites_originales_facture = {}
        self._quitter_mode_edition()
        self._redessiner_panier()
        self.var_remise_active.set(bool(proforma.remise_taux))
        self.var_remise_taux.set(format_nombre(proforma.remise_taux)
                                 if proforma.remise_taux else "")
        self._maj_total()
        self._facture_enregistree_id = None

        self._bandeau_edition.configure(text=t("fact_bandeau_brouillon"))
        self._bandeau_edition.grid()
        self._bouton_enregistrer.configure(state="disabled")
        self._bouton_brouillon.configure(text="💾 " + t("fact_enregistrer_modif"))
        # Un bordereau de livraison n'a pas de sens pour un simple brouillon
        # (rien n'est encore commandé/facturé) — seule l'impression proforma
        # (bouton Imprimer, voir _exporter_pdf) reste pertinente.
        self._bouton_bordereau.configure(state="disabled")

    # Édition d'une facture déjà enregistrée --------------------------------
    def charger_pour_edition(self, facture) -> None:
        """Charge une facture existante (en-tête + lignes) dans le formulaire
        pour la corriger, au lieu de la supprimer et tout ressaisir."""
        self._edition_proforma_id = None
        self._bouton_bordereau.configure(state="normal")
        self._edition_facture_id = facture.id
        self.var_numero.set(str(facture.numero))
        self.var_date.set(format_date(facture.date_facture))
        self.var_client.set(facture.client_nom)
        self.var_destination.set(facture.destination)
        self.var_telephone.set(facture.telephone)
        self.var_matricule.set(facture.matricule)
        self._lignes = list(facture.lignes)
        # Quantité déjà sortie du stock par produit dans CETTE facture —
        # créditée lors de la vérification de stock pendant sa correction
        # (voir `_verifier_stock_disponible`), puisque `FactureRepository.
        # modifier` restitue puis réapplique ces sorties à l'enregistrement.
        self._quantites_originales_facture = {}
        for ligne in facture.lignes:
            if ligne.produit_id:
                self._quantites_originales_facture[ligne.produit_id] = (
                    self._quantites_originales_facture.get(ligne.produit_id, 0)
                    + ligne.quantite
                )
        self._quitter_mode_edition()
        self._redessiner_panier()
        self.var_remise_active.set(bool(facture.remise_taux))
        self.var_remise_taux.set(format_nombre(facture.remise_taux)
                                 if facture.remise_taux else "")
        self._maj_total()
        self._facture_enregistree_id = None

        self._bandeau_edition.configure(
            text=t("fact_bandeau_edition").format(facture.numero))
        self._bandeau_edition.grid()
        self._bouton_enregistrer.configure(
            state="normal", text="💾 " + t("fact_enregistrer_modif"))

    def _quitter_mode_edition_facture(self) -> None:
        """Revient au mode création normale (bandeau et libellés des boutons),
        que l'édition en cours portât sur une facture existante ou un
        brouillon (proforma)."""
        self._edition_facture_id = None
        self._edition_proforma_id = None
        self._bandeau_edition.grid_remove()
        self._bouton_enregistrer.configure(state="normal", text=t("fact_enregistrer"))
        self._bouton_brouillon.configure(text="📝 " + t("fact_save_brouillon"))
        self._bouton_bordereau.configure(state="normal")

    def _facture_pour_pdf(self):
        """Facture à exporter : celle enregistrée, sinon le panier courant."""
        from app.models import Facture
        if self._facture_enregistree_id:
            return self.app.facturation.obtenir_facture(self._facture_enregistree_id)
        entete = self._lire_entete()
        if entete is None or not self._lignes:
            if not self._lignes:
                messagebox.showwarning(t("attention"), t("fact_panier_vide"))
            return None
        numero, date_facture = entete
        return Facture(
            numero=numero, date_facture=date_facture,
            client_nom=self.var_client.get().strip().upper(),
            destination=self.var_destination.get().strip(),
            telephone=self.var_telephone.get().strip(),
            matricule=self.var_matricule.get().strip(),
            remise_taux=self._taux_remise_affichage(),
            tva_taux=config.TVA_TAUX_DEFAUT,
            lignes=self._lignes,
        )

    def _proforma_pour_pdf(self):
        """Brouillon à exporter en PDF (aperçu « FACTURE PROFORMA », sans
        numéro) : celui en cours d'édition, avec le contenu actuel du panier."""
        from app.models import Proforma
        if not self._lignes:
            messagebox.showwarning(t("attention"), t("fact_panier_vide"))
            return None
        return Proforma(
            id=self._edition_proforma_id or 0,
            client_nom=self.var_client.get().strip().upper(),
            destination=self.var_destination.get().strip(),
            telephone=self.var_telephone.get().strip(),
            matricule=self.var_matricule.get().strip(),
            remise_taux=self._taux_remise_affichage(),
            lignes=self._lignes,
        )

    def _exporter_pdf(self) -> None:
        if self._edition_proforma_id is not None:
            proforma = self._proforma_pour_pdf()
            if proforma is None:
                return
            chemin = self.app.pdf.generer_proforma(proforma)
        else:
            facture = self._facture_pour_pdf()
            if facture is None:
                return
            chemin = self.app.pdf.generer_facture(facture)
        afficher_toast(self, t("fact_pdf_genere") + chemin.name)
        ouvrir_fichier(chemin)

    def _exporter_bordereau(self) -> None:
        facture = self._facture_pour_pdf()
        if facture is None:
            return
        chemin = self.app.pdf.generer_bordereau(facture)
        afficher_toast(self, t("fact_pdf_genere") + chemin.name)
        ouvrir_fichier(chemin)

    def _nouvelle_facture(self) -> None:
        """Vide le panier et passe au numéro suivant (seul point d'incrément).
        Quitte aussi le mode édition d'une facture existante s'il était actif."""
        if self._lignes and not messagebox.askyesno(
            t("confirmer"), t("fact_nouvelle_confirmation")
        ):
            return
        self._quitter_mode_edition_facture()
        self._reinitialiser_panier()

    def _effacer_facture(self) -> None:
        """Vide uniquement les lignes du panier — contrairement à « Nouvelle
        facture », ne touche ni au numéro, ni à la date, ni au client/
        destination, ni à un éventuel mode d'édition (facture ou brouillon)
        en cours."""
        if not self._lignes:
            return
        if not messagebox.askyesno(t("confirmer"), t("fact_effacer_confirmation")):
            return
        self._lignes.clear()
        self._quitter_mode_edition()
        self._redessiner_panier()
        self._facture_enregistree_id = None
        self._maj_total()

    def _reinitialiser_panier(self) -> None:
        """Vide le panier et propose le numéro suivant, instantanément (voir
        `_definir_numero_suggere`)."""
        self._lignes.clear()
        self._quantites_originales_facture = {}
        self._quitter_mode_edition()
        self._redessiner_panier()
        self.var_client.set("")
        self.var_destination.set("")
        self.var_telephone.set("")
        self.var_matricule.set("")
        self.var_quantite.set("")
        self.var_date.set(format_date(date.today()))
        self.var_numero.set(self._definir_numero_suggere())
        self.var_remise_active.set(False)
        self.var_remise_taux.set("")
        self._facture_enregistree_id = None
        self._maj_total()
