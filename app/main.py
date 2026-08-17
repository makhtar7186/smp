"""Point d'entrée de SMP Gestion.

Deux modes de lancement, selon `config.lire_mode_machine()` (défaut
"principale", zéro changement de comportement pour les installations
existantes) — voir CLAUDE.md, section « Machine de facturation »."""
from app import config


def main() -> None:
    if config.lire_mode_machine() == "facturation_distante":
        from app.ui.app_facturation_etendue import lancer
    else:
        from app.ui.app import lancer
    lancer()


if __name__ == "__main__":
    main()
