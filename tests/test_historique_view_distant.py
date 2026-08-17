"""Test de _AdaptateurHistoriqueAdmin : les factures archivées ne doivent
jamais apparaître dans la page « Historique complet » — voir CLAUDE.md,
section « Machine de facturation »."""
from __future__ import annotations

from app.ui.views.historique_view_distant import _AdaptateurHistoriqueAdmin


class _FauxApiAdmin:
    def __init__(self) -> None:
        self.derniers_kwargs: dict = {}

    def lister_factures_admin(self, **kwargs):
        self.derniers_kwargs = kwargs
        return []


def test_lister_factures_filtre_les_archivees() -> None:
    api = _FauxApiAdmin()
    adaptateur = _AdaptateurHistoriqueAdmin(api)
    adaptateur.lister_factures()
    assert api.derniers_kwargs["archivee"] is False
