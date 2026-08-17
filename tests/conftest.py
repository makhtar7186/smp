"""Fixtures partagées : base SQLite en mémoire et services."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.repositories.base_repository import creer_connexion  # noqa: E402


@pytest.fixture()
def conn():
    """Connexion SQLite en mémoire avec schéma créé."""
    connexion = creer_connexion(":memory:")
    yield connexion
    connexion.close()
