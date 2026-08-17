"""Notification non intrusive (toast) affichée en bas de la fenêtre."""
from __future__ import annotations

import tkinter as tk

from app.ui import theme


def afficher_toast(root: tk.Misc, message: str, succes: bool = True,
                   duree_ms: int = 2500) -> None:
    """Affiche un bandeau temporaire en bas à droite de la fenêtre principale."""
    couleur = theme.COULEURS["succes"] if succes else theme.COULEURS["danger"]
    toast = tk.Toplevel(root)
    toast.overrideredirect(True)
    toast.attributes("-topmost", True)
    cadre = tk.Frame(toast, bg=couleur, padx=16, pady=10)
    cadre.pack()
    tk.Label(cadre, text=message, bg=couleur, fg="white",
             font=theme.POLICES["normal"]).pack()
    root.update_idletasks()
    fenetre = root.winfo_toplevel()
    x = fenetre.winfo_rootx() + fenetre.winfo_width() - toast.winfo_reqwidth() - 30
    y = fenetre.winfo_rooty() + fenetre.winfo_height() - toast.winfo_reqheight() - 30
    toast.geometry(f"+{x}+{y}")
    toast.after(duree_ms, toast.destroy)
