"""Bandeau de statut de synchronisation (machine de facturation) : icône
en-ligne/hors-ligne, compteurs en attente/erreur, bouton « Synchroniser
maintenant » et « Réessayer » (repasse toutes les opérations en erreur à
`en_attente`). Voir CLAUDE.md, section « Machine de facturation »."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.i18n.translations import t
from app.sync.models import StatutSync
from app.sync.queue_repository import QueueSyncRepository
from app.sync.worker import SyncWorker
from app.ui import theme


class SyncStatusBadge(ttk.Frame):
    """Toujours visible en bas de la sidebar de `ApplicationFacturation` —
    mis à jour par callback push du `SyncWorker` (jamais de polling)."""

    def __init__(self, parent: tk.Misc, queue: QueueSyncRepository,
                 worker: SyncWorker) -> None:
        super().__init__(parent)
        self._queue = queue
        self._worker = worker

        self._label_statut = tk.Label(self, text="…", font=theme.POLICES["petit"],
                                      bg=theme.COULEURS["sidebar"],
                                      fg=theme.COULEURS["sidebar_texte"])
        self._label_statut.pack(anchor="w")
        self._label_compteurs = tk.Label(self, text="", font=theme.POLICES["petit"],
                                         bg=theme.COULEURS["sidebar"])
        self._label_compteurs.pack(anchor="w")

        boutons = tk.Frame(self, bg=theme.COULEURS["sidebar"])
        boutons.pack(fill="x", pady=(4, 0))
        ttk.Button(boutons, text="⟳ " + t("sync_badge_synchroniser"),
                  command=self._synchroniser_maintenant).pack(side="left")
        self._bouton_reessayer = ttk.Button(boutons, text=t("sync_badge_reessayer"),
                                           command=self._reessayer_tout, state="disabled")
        self._bouton_reessayer.pack(side="left", padx=(4, 0))

        self.rafraichir(worker.statut())

    def rafraichir(self, statut: StatutSync) -> None:
        """Appelé depuis le thread principal Tk uniquement — voir
        `ApplicationFacturation._sur_changement_statut_sync`, qui marshalle
        l'appel du thread worker vers le thread Tk via `after(0, ...)`."""
        icone = "🟢" if statut.en_ligne else "🔴"
        texte = t("sync_badge_en_ligne") if statut.en_ligne else t("sync_badge_hors_ligne")
        self._label_statut.configure(text=f"{icone} {texte}")

        morceaux = []
        if statut.en_attente:
            morceaux.append(f"{statut.en_attente} {t('sync_badge_en_attente')}")
        if statut.erreur:
            morceaux.append(f"{statut.erreur} {t('sync_badge_erreurs')}")
        if statut.derniere_synchro:
            morceaux.append(f"{t('sync_badge_derniere_synchro')} {statut.derniere_synchro}")
        self._label_compteurs.configure(
            text=" · ".join(morceaux),
            fg=theme.COULEURS["danger"] if statut.erreur
            else theme.COULEURS["sidebar_texte"],
        )
        self._bouton_reessayer.configure(state="normal" if statut.erreur else "disabled")

    def _synchroniser_maintenant(self) -> None:
        self._worker.declencher_immediat()

    def _reessayer_tout(self) -> None:
        for operation in self._queue.lister(["erreur"]):
            self._queue.reessayer(operation.id)
        self._worker.declencher_immediat()
