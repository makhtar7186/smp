"""Thème centralisé : palette, polices et styles ttk de toute l'application."""
from __future__ import annotations

from tkinter import ttk

# Palette — une couleur d'accent forte + neutres
COULEURS = {
    "accent": "#1D4ED8",        # bleu principal
    "accent_sombre": "#1E40AF",
    "accent_clair": "#DBEAFE",
    "sidebar": "#111827",       # gris très sombre
    "sidebar_actif": "#1F2937",
    "sidebar_texte": "#D1D5DB",
    "fond": "#F3F4F6",          # fond de l'application
    "carte": "#FFFFFF",         # fond des cartes
    "bordure": "#E5E7EB",
    "texte": "#111827",
    "texte_secondaire": "#6B7280",
    "succes": "#059669",
    "danger": "#DC2626",
    "info": "#D97706",   # trop-perçu sur un versement (restant < 0) : ni dû ni soldé
    "ligne_alternee": "#F9FAFB",
}

# Typographie hiérarchisée (Segoe UI couvre le chinois via le fallback Windows)
POLICES = {
    "titre": ("Segoe UI", 18, "bold"),
    "sous_titre": ("Segoe UI", 12, "bold"),
    "normal": ("Segoe UI", 10),
    "petit": ("Segoe UI", 9),
    "kpi_valeur": ("Segoe UI", 17, "bold"),
    "kpi_titre": ("Segoe UI", 9),
    "nav": ("Segoe UI", 11),
    "total_gros": ("Segoe UI", 14, "bold"),  # totaux mis en avant (bien visibles)
}

# Espacements constants
PAD = 12
PAD_S = 6
PAD_L = 20

# Palette des graphiques matplotlib (cohérente avec le thème)
PALETTE_GRAPHIQUES = ["#1D4ED8", "#059669", "#D97706", "#DC2626", "#7C3AED",
                      "#0891B2", "#DB2777", "#65A30D", "#9333EA", "#EA580C"]


def appliquer_theme(root) -> None:
    """Configure les styles ttk globaux. À appeler une fois au démarrage."""
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=COULEURS["fond"], foreground=COULEURS["texte"],
                    font=POLICES["normal"])
    style.configure("TFrame", background=COULEURS["fond"])
    style.configure("Carte.TFrame", background=COULEURS["carte"], relief="flat")
    style.configure("TLabel", background=COULEURS["fond"], foreground=COULEURS["texte"])
    style.configure("Carte.TLabel", background=COULEURS["carte"])
    style.configure("Titre.TLabel", font=POLICES["titre"],
                    background=COULEURS["fond"], foreground=COULEURS["texte"])
    style.configure("SousTitre.TLabel", font=POLICES["sous_titre"],
                    background=COULEURS["carte"], foreground=COULEURS["texte"])
    style.configure("Secondaire.TLabel", background=COULEURS["carte"],
                    foreground=COULEURS["texte_secondaire"], font=POLICES["petit"])
    style.configure("KpiTitre.TLabel", background=COULEURS["carte"],
                    foreground=COULEURS["texte_secondaire"], font=POLICES["kpi_titre"])
    style.configure("KpiValeur.TLabel", background=COULEURS["carte"],
                    foreground=COULEURS["texte"], font=POLICES["kpi_valeur"])
    style.configure("KpiHausse.TLabel", background=COULEURS["carte"],
                    foreground=COULEURS["succes"], font=POLICES["petit"])
    style.configure("KpiBaisse.TLabel", background=COULEURS["carte"],
                    foreground=COULEURS["danger"], font=POLICES["petit"])

    # Boutons
    style.configure("Accent.TButton", background=COULEURS["accent"],
                    foreground="white", font=POLICES["normal"], padding=(14, 7),
                    borderwidth=0)
    style.map("Accent.TButton",
              background=[("active", COULEURS["accent_sombre"]),
                          ("disabled", COULEURS["bordure"])])
    style.configure("TButton", padding=(12, 6), background=COULEURS["carte"],
                    borderwidth=1)
    style.map("TButton", background=[("active", COULEURS["accent_clair"])])
    style.configure("Danger.TButton", background=COULEURS["danger"],
                    foreground="white", padding=(12, 6), borderwidth=0)
    style.map("Danger.TButton", background=[("active", "#B91C1C")])

    # Champs de saisie
    style.configure("TEntry", fieldbackground="white", padding=5)
    style.configure("TCombobox", fieldbackground="white", padding=5)

    # Tableaux
    style.configure("Treeview", background="white", fieldbackground="white",
                    rowheight=28, font=POLICES["normal"], borderwidth=0)
    style.configure("Treeview.Heading", background=COULEURS["accent"],
                    foreground="white", font=POLICES["normal"], padding=6)
    style.map("Treeview.Heading", background=[("active", COULEURS["accent_sombre"])])
    style.map("Treeview",
              background=[("selected", COULEURS["accent_clair"])],
              foreground=[("selected", COULEURS["texte"])])

    # Onglets / notebook éventuels
    style.configure("TNotebook", background=COULEURS["fond"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 7))


def configurer_lignes_alternees(treeview) -> None:
    """Active les tags de lignes alternées sur un Treeview."""
    treeview.tag_configure("pair", background="white")
    treeview.tag_configure("impair", background=COULEURS["ligne_alternee"])


def tag_alternance(indice: int) -> str:
    """Tag de style pour la ligne d'indice donné."""
    return "impair" if indice % 2 else "pair"
