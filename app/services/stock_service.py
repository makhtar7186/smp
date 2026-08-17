"""Service de gestion de stock : visibilité du catalogue, entrées et
ajustements manuels. Les sorties liées à une vente sont gérées par
`FacturationService` (voir CLAUDE.md, section « Gestion de stock »)."""
from __future__ import annotations

import sqlite3

from app.models import MouvementStock, Produit
from app.models.mouvement_stock import TYPE_AJUSTEMENT, TYPE_ENTREE
from app.models.produit import TYPES_OPTION
from app.repositories.produit_repository import ProduitRepository
from app.repositories.stock_repository import StockRepository
from app.utils.validation import ErreurValidation


class StockService:
    """Suivi des quantités en stock (entrées, ajustements correctifs),
    création et modification (nom/option) des articles au catalogue. Le
    **prix** reste un réglage exclusif de l'app Facturation (`ProduitRepository`,
    page Produits), jamais exposé ni modifiable ici — de même que la fusion
    de doublons, réservée à cette même page — voir CLAUDE.md, section
    « Gestion de stock »."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._produits = ProduitRepository(conn)
        self._stock = StockRepository(conn)

    def lister_produits(self, actifs_seulement: bool = False) -> list[Produit]:
        """Catalogue avec la quantité en stock courante de chaque article."""
        return self._produits.lister(actifs_seulement)

    def creer_produit(
        self, nom: str, type_option: str = "", valeur_option: str = "", prix: int = 0,
    ) -> Produit:
        """Ajoute un nouvel article au catalogue, stock initial à 0 (une
        entrée de stock distincte l'alimente ensuite). Seul point de création
        du catalogue — la facturation ne crée plus de produit à la volée."""
        nom = str(nom or "").strip().upper()
        if not nom:
            raise ErreurValidation("champ_obligatoire")
        if type_option not in ("", *TYPES_OPTION):
            raise ErreurValidation("stock_type_option_invalide")
        if prix < 0:
            raise ErreurValidation("fact_prix_positif")
        valeur_option = str(valeur_option or "").strip().upper()
        if self._produits.chercher(nom, type_option, valeur_option) is not None:
            raise ErreurValidation("prod_existe")
        return self._produits.creer(
            Produit(nom=nom, type_option=type_option,
                    valeur_option=valeur_option, prix=prix)
        )

    def modifier_produit(
        self, produit_id: int, nom: str, type_option: str = "", valeur_option: str = "",
    ) -> Produit:
        """Modifie le nom/l'option d'un article existant — jamais son prix
        (réglage exclusif de l'app Facturation) ni sa quantité en stock
        (mouvements dédiés, jamais une simple édition du catalogue)."""
        produit = self._produits.obtenir(produit_id)
        if produit is None:
            raise ErreurValidation("stock_produit_introuvable")
        nom = str(nom or "").strip().upper()
        if not nom:
            raise ErreurValidation("champ_obligatoire")
        if type_option not in ("", *TYPES_OPTION):
            raise ErreurValidation("stock_type_option_invalide")
        valeur_option = str(valeur_option or "").strip().upper()
        existant = self._produits.chercher(nom, type_option, valeur_option)
        if existant is not None and existant.id != produit_id:
            raise ErreurValidation("prod_existe")
        produit.nom = nom
        produit.type_option = type_option
        produit.valeur_option = valeur_option
        self._produits.modifier(produit)
        return produit

    def supprimer_produit(self, produit_id: int) -> None:
        """Supprime un article du catalogue. Refuse proprement (message
        clair plutôt qu'un crash) s'il est encore référencé par des lignes
        de vente déjà enregistrées (contrainte de clé étrangère)."""
        try:
            self._produits.supprimer(produit_id)
        except sqlite3.IntegrityError as exc:
            raise ErreurValidation("stock_produit_utilise") from exc

    def entrer_stock(
        self, produit_id: int, quantite: int, note: str = "", machine_id: str = "",
    ) -> MouvementStock:
        """Enregistre une entrée (approvisionnement) — quantité strictement
        positive."""
        if quantite <= 0:
            raise ErreurValidation("stock_quantite_positive")
        return self._stock.enregistrer_mouvement(
            produit_id, TYPE_ENTREE, quantite, reference=note,
            source="manuel", machine_id=machine_id)

    def ajuster_stock(
        self, produit_id: int, delta: int, motif: str = "", machine_id: str = "",
    ) -> MouvementStock:
        """Enregistre un ajustement correctif — `delta` signé (positif ou
        négatif), ex. après un inventaire physique. Le stock peut devenir
        négatif : jamais de blocage métier sur cette écriture."""
        if delta == 0:
            raise ErreurValidation("stock_ajustement_non_nul")
        return self._stock.enregistrer_mouvement(
            produit_id, TYPE_AJUSTEMENT, delta, reference=motif,
            source="manuel", machine_id=machine_id)

    def historique(self, produit_id: int, limite: int = 200) -> list[MouvementStock]:
        return self._stock.historique(produit_id, limite)

    def stock_actuel(self, produit_id: int) -> int:
        return self._stock.stock_actuel(produit_id)
