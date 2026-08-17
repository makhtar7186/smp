"""Génération PDF (reportlab) : facture et bordereau de livraison."""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app import config
from app.models import Facture, Proforma
from app.utils.formatting import format_date, format_fcfa, format_nombre
from app.utils.nombre_lettres import nombre_en_lettres_fr

_LARGEUR, _HAUTEUR = A4
_MARGE = 15 * mm
_ACCENT = colors.HexColor("#1D4ED8")
_ROUGE = colors.HexColor("#DC2626")
_GRIS = colors.HexColor("#6B7280")
_GRIS_CLAIR = colors.HexColor("#F3F4F6")
_TAILLE_LOGO = 40 * mm
_DIAMETRE_CACHET = 100 * mm  # espace réservé au cachet circulaire (~10 cm de diamètre)


class PdfService:
    """Produit les documents PDF dans le dossier d'exports."""

    def __init__(self, dossier_exports: Path | None = None) -> None:
        self._dossier = dossier_exports or config.DOSSIER_EXPORTS
        self._dossier.mkdir(parents=True, exist_ok=True)

    # API ---------------------------------------------------------------------
    def generer_facture(self, facture: Facture) -> Path:
        """Facture PDF avec prix et total général."""
        chemin = self._dossier / f"FACTURE_{facture.numero}.pdf"
        self._generer(facture, chemin, titre="FACTURE", avec_prix=True)
        return chemin

    def generer_bordereau(self, facture: Facture) -> Path:
        """Bordereau de livraison PDF : mêmes lignes, sans prix."""
        chemin = self._dossier / f"BORDEREAU_{facture.numero}.pdf"
        self._generer(facture, chemin, titre="BORDEREAU DE LIVRAISON", avec_prix=False)
        return chemin

    def generer_proforma(self, proforma: Proforma) -> Path:
        """Facture proforma PDF : mêmes lignes et prix qu'une facture, mais
        sans numéro (le brouillon n'en a pas tant qu'il n'est pas validé)."""
        chemin = self._dossier / f"PROFORMA_{proforma.id or 0}.pdf"
        self._generer(proforma, chemin, titre="FACTURE PROFORMA", avec_prix=True,
                      sans_numero=True)
        return chemin

    # Rendu -------------------------------------------------------------------
    def _generer(
        self, facture: Facture, chemin: Path, titre: str, avec_prix: bool,
        sans_numero: bool = False,
    ) -> None:
        canevas = Canvas(str(chemin), pagesize=A4)
        y = self._entete(canevas, facture, titre, sans_numero=sans_numero)
        y = self._tableau_lignes(canevas, facture, y, avec_prix)
        if avec_prix:
            # Toujours sur la même page que le tableau — jamais de saut de
            # page forcé pour ce bloc (total → mention en lettres → libellé
            # cachet/signature, enchaînés directement à la suite les uns des
            # autres, voir `_total`/`_mention_montant_lettres`/
            # `_bloc_signature`).
            y = self._total(canevas, facture, y)
            y = self._mention_montant_lettres(canevas, facture, y)
            self._bloc_signature(canevas, y)
        self._pied_de_page(canevas)
        canevas.save()

    def _entete(self, canevas: Canvas, facture: Facture, titre: str,
               sans_numero: bool = False) -> float:
        """Logo, coordonnées de l'entreprise, titre, numéro et infos client."""
        y = _HAUTEUR - _MARGE
        if config.CHEMIN_LOGO.exists():
            try:
                canevas.drawImage(
                    str(config.CHEMIN_LOGO), _MARGE, y - _TAILLE_LOGO,
                    width=_TAILLE_LOGO, height=_TAILLE_LOGO,
                    preserveAspectRatio=True, mask="auto",
                )
            except Exception:  # noqa: BLE001 - logo illisible : on continue sans
                pass
        x_texte = _MARGE + _TAILLE_LOGO + 6 * mm
        canevas.setFillColor(_ACCENT)
        self._texte_ajuste(
            canevas, config.ENTREPRISE["nom"], x_texte, y - 10 * mm,
            "Helvetica-Bold", taille_max=25, taille_min=10,
            largeur_max=(_LARGEUR - _MARGE) - x_texte,
        )
        canevas.setFillColor(colors.black)
        canevas.setFont("Helvetica", 10)
        # Adresse répartie sur deux lignes (texte long) pour ne jamais chevaucher
        # le bloc numéro/date aligné à droite
        segments_adresse = config.ENTREPRISE["adresse"].split(", ", 1)
        canevas.drawString(x_texte, y - 17 * mm, segments_adresse[0])
        if len(segments_adresse) > 1:
            canevas.drawString(x_texte, y - 22 * mm, segments_adresse[1])
        canevas.drawString(x_texte, y - 27 * mm, f"Tél : {config.ENTREPRISE['telephones']}")
        canevas.drawString(
            x_texte, y - 32 * mm,
            f"NINEA : {config.ENTREPRISE['ninea']}   RC : {config.ENTREPRISE['rc']}",
        )
        # Bloc titre/numéro/date à droite, sous les coordonnées de l'entreprise
        # (et non à côté) : le titre du bordereau est long et chevaucherait le
        # nom de l'entreprise si les deux blocs partageaient la même ligne.
        # Numéro de facture en rouge, bien visible.
        canevas.setFont("Helvetica-Bold", 18)
        canevas.setFillColor(_ACCENT)
        canevas.drawRightString(_LARGEUR - _MARGE, y - 39 * mm, titre)
        if not sans_numero:
            # Un brouillon (proforma) n'a pas de numéro tant qu'il n'est pas
            # validé : cette ligne est simplement omise, sans texte de repli.
            canevas.setFont("Helvetica-Bold", 13)
            canevas.setFillColor(_ROUGE)
            canevas.drawRightString(_LARGEUR - _MARGE, y - 47 * mm,
                                    f"N° : {facture.numero}")
        canevas.setFillColor(colors.black)
        canevas.setFont("Helvetica", 10)
        date_facture = getattr(facture, "date_facture", None) or facture.date_creation
        canevas.drawRightString(
            _LARGEUR - _MARGE, y - 53 * mm,
            f"Date : {format_date(date_facture)}",
        )
        # Séparateur
        y -= max(_TAILLE_LOGO, 53 * mm) + 4 * mm
        canevas.setStrokeColor(_ACCENT)
        canevas.setLineWidth(1.2)
        canevas.line(_MARGE, y, _LARGEUR - _MARGE, y)
        # Client / destination
        y -= 8 * mm
        canevas.setFont("Helvetica-Bold", 10)
        canevas.drawString(_MARGE, y, "Client :")
        canevas.setFont("Helvetica", 10)
        canevas.drawString(_MARGE + 22 * mm, y, facture.client_nom)
        y -= 5.5 * mm
        canevas.setFont("Helvetica-Bold", 10)
        canevas.drawString(_MARGE, y, "Destination :")
        canevas.setFont("Helvetica", 10)
        canevas.drawString(_MARGE + 28 * mm, y, facture.destination)
        y -= 5.5 * mm
        canevas.setFont("Helvetica-Bold", 10)
        canevas.drawString(_MARGE, y, "Téléphone :")
        canevas.setFont("Helvetica", 10)
        canevas.drawString(_MARGE + 28 * mm, y, getattr(facture, "telephone", ""))
        matricule = getattr(facture, "matricule", "")
        if matricule:
            y -= 5.5 * mm
            canevas.setFont("Helvetica-Bold", 10)
            canevas.drawString(_MARGE, y, "Matricule :")
            canevas.setFont("Helvetica", 10)
            canevas.drawString(_MARGE + 28 * mm, y, matricule)
        return y - 8 * mm

    def _colonnes(self, avec_prix: bool) -> list[tuple[str, float]]:
        """Définition (titre, largeur) des colonnes du tableau."""
        if avec_prix:
            return [
                ("QUANTITÉ", 30 * mm),
                ("DÉSIGNATION", 90 * mm),
                ("P. UNITAIRE", 30 * mm),
                ("P. TOTAL", 30 * mm),
            ]
        return [
            ("QUANTITÉ", 40 * mm),
            ("DÉSIGNATION", 140 * mm),
        ]

    def _tableau_lignes(
        self, canevas: Canvas, facture: Facture, y: float, avec_prix: bool
    ) -> float:
        colonnes = self._colonnes(avec_prix)
        hauteur_ligne = 7 * mm
        # En-tête du tableau
        canevas.setFillColor(_ACCENT)
        canevas.rect(_MARGE, y - hauteur_ligne, sum(l for _, l in colonnes),
                     hauteur_ligne, fill=1, stroke=0)
        canevas.setFillColor(colors.white)
        canevas.setFont("Helvetica-Bold", 9)
        x = _MARGE
        for titre, largeur in colonnes:
            canevas.drawCentredString(x + largeur / 2, y - hauteur_ligne + 2 * mm, titre)
            x += largeur
        y -= hauteur_ligne
        # Lignes
        canevas.setFont("Helvetica", 9)
        # Marge minimale pour éviter qu'une ligne soit coupée en deux entre
        # deux pages. Le total/la mention en lettres/le bloc cachet-signature
        # (avec_prix=True) ne provoquent, eux, jamais de saut de page : ils
        # s'impriment toujours à la suite du tableau sur la même page, quitte
        # à se retrouver serrés contre la marge basse sur une facture à
        # beaucoup de lignes (voir `_generer`).
        seuil_bas = _MARGE + 30 * mm
        for indice, ligne in enumerate(facture.lignes):
            if y < seuil_bas:  # saut de page
                self._pied_de_page(canevas)
                canevas.showPage()
                y = _HAUTEUR - _MARGE
                canevas.setFont("Helvetica", 9)
            if indice % 2 == 1:
                canevas.setFillColor(_GRIS_CLAIR)
                canevas.rect(_MARGE, y - hauteur_ligne, sum(l for _, l in colonnes),
                             hauteur_ligne, fill=1, stroke=0)
            canevas.setFillColor(colors.black)
            valeurs = [format_nombre(ligne.quantite), ligne.designation]
            if avec_prix:
                valeurs += [format_fcfa(ligne.prix_unitaire, avec_devise=False),
                            format_fcfa(ligne.total, avec_devise=False)]
            x = _MARGE
            for (titre_col, largeur), valeur in zip(colonnes, valeurs):
                if titre_col == "DÉSIGNATION":
                    canevas.drawString(x + 2 * mm, y - hauteur_ligne + 2 * mm,
                                       valeur[:52])
                elif titre_col in ("P. UNITAIRE", "P. TOTAL"):
                    canevas.drawRightString(x + largeur - 2 * mm,
                                            y - hauteur_ligne + 2 * mm, valeur)
                else:
                    canevas.drawCentredString(x + largeur / 2,
                                              y - hauteur_ligne + 2 * mm, valeur)
                x += largeur
            y -= hauteur_ligne
        # Cadre extérieur
        canevas.setStrokeColor(_GRIS)
        canevas.setLineWidth(0.5)
        return y - 4 * mm

    def _total(self, canevas: Canvas, facture: Facture, y: float) -> float:
        # Bloc élargi (85mm, au lieu de 70mm) : les libellés du détail
        # HT/TVA sont plus longs que "Marchandise"/"TOTAL NET" et se
        # superposaient sinon au montant aligné à droite sur la même ligne.
        largeur_bloc = 85 * mm
        x_gauche = _LARGEUR - _MARGE - largeur_bloc
        # `tva_taux`/`tva_montant`/`total_ht`/`total_ttc` n'existent que sur
        # `Facture` (pas sur `Proforma`, qui réutilise ce même rendu) - accès
        # défensif.
        tva_taux = getattr(facture, "tva_taux", 0)
        canevas.setFont("Helvetica", 9.5)

        if facture.remise_taux:
            # Remise propre à cette facture : marchandise et remise détaillées
            # avant le total net (montant réellement dû, TVA comprise le cas
            # échéant - voir plus bas, jamais un supplément pour le client).
            canevas.setFillColor(colors.black)
            canevas.drawString(x_gauche, y - 5 * mm, "Marchandise")
            canevas.drawRightString(_LARGEUR - _MARGE, y - 5 * mm,
                                    format_fcfa(facture.total, False))
            canevas.setFillColor(_ROUGE)
            canevas.drawString(x_gauche, y - 10 * mm,
                               f"Remise ({facture.remise_taux:g}%)")
            canevas.drawRightString(_LARGEUR - _MARGE, y - 10 * mm,
                                    f"-{format_fcfa(facture.remise_montant, False)}")
            y -= 13 * mm

        if tva_taux:
            # La TVA est prélevée SUR le total net (déjà après remise) -
            # jamais ajoutée en plus : le client paie exactement `total_net`
            # que la TVA soit activée ou non, seule sa décomposition
            # HT/TVA affichée ci-dessous change. Voir Facture.total_ht.
            canevas.setFillColor(colors.black)
            canevas.drawString(x_gauche, y - 5 * mm, "Total HT (hors taxe)")
            canevas.drawRightString(_LARGEUR - _MARGE, y - 5 * mm,
                                    format_fcfa(facture.total_ht, False))
            canevas.drawString(x_gauche, y - 10 * mm, f"TVA ({tva_taux:g}%)")
            canevas.drawRightString(_LARGEUR - _MARGE, y - 10 * mm,
                                    format_fcfa(facture.tva_montant, False))
            y -= 13 * mm
            total_affiche = facture.total_ttc
            libelle_total = "TOTAL TTC"
        elif facture.remise_taux:
            total_affiche = facture.total_net
            libelle_total = "TOTAL NET"
        else:
            total_affiche = facture.total
            libelle_total = "TOTAL"

        canevas.setFillColor(_ACCENT)
        canevas.rect(x_gauche, y - 9 * mm, largeur_bloc, 9 * mm, fill=1, stroke=0)
        canevas.setFillColor(colors.white)
        canevas.setFont("Helvetica-Bold", 11)
        canevas.drawString(x_gauche + 4 * mm, y - 6.5 * mm, libelle_total)
        canevas.drawRightString(_LARGEUR - _MARGE - 3 * mm, y - 6.5 * mm,
                                format_fcfa(total_affiche))
        return y - 9 * mm  # bas du bloc total (bord inférieur du rectangle)

    def _mention_montant_lettres(self, canevas: Canvas, facture: Facture, y: float) -> float:
        """Mention légale juste sous le bloc total (jamais sur le bordereau,
        voir `_generer`) : le montant en toutes lettres est celui réellement
        dû (`total_ttc`, identique au bloc total). Enchaînée directement à
        la suite de `_total()` (plutôt qu'à une position fixe indépendante)
        pour ne jamais laisser un grand vide entre le total et cette
        mention — voir `_garantir_espace_bas_page`, qui garantit en amont
        que tout l'enchaînement (total + mention + cachet/signature) tient
        dans l'espace restant."""
        texte_montant = nombre_en_lettres_fr(facture.total_ttc)
        texte_montant = texte_montant[0].upper() + texte_montant[1:]
        mention = (
            f"Cette présente facture est arrêtée à la somme de : "
            f"{texte_montant} francs CFA."
        )
        canevas.setFillColor(colors.black)
        police, taille = "Helvetica-Oblique", 9
        largeur_max = _LARGEUR - 2 * _MARGE
        y -= 10 * mm
        for ligne_texte in self._decouper_texte(canevas, mention, police, taille,
                                                largeur_max)[:2]:
            canevas.setFont(police, taille)
            canevas.drawString(_MARGE, y, ligne_texte)
            y -= 4.5 * mm
        return y

    def _bloc_signature(self, canevas: Canvas, y: float) -> None:
        """Libellé « Cachet et signature » (gras, souligné, sans cadre),
        enchaîné juste sous la mention en lettres (jamais sur le bordereau,
        voir `_generer`) — volontairement pas de rectangle : l'espace en
        dessous doit rester totalement libre, suffisant pour un cachet
        circulaire d'environ 10 cm de diamètre (`_DIAMETRE_CACHET`), déjà
        garanti disponible par `_garantir_espace_bas_page`."""
        police, taille = "Helvetica-Bold", 10
        y -= 8 * mm
        texte = "Cachet et signature"
        canevas.setFillColor(colors.black)
        canevas.setFont(police, taille)
        canevas.drawString(_MARGE, y, texte)
        largeur_texte = canevas.stringWidth(texte, police, taille)
        canevas.setLineWidth(0.6)
        canevas.line(_MARGE, y - 1.3 * mm, _MARGE + largeur_texte, y - 1.3 * mm)

    def _decouper_texte(
        self, canevas: Canvas, texte: str, police: str, taille: float,
        largeur_max: float,
    ) -> list[str]:
        """Découpe `texte` en lignes qui tiennent chacune dans `largeur_max`,
        mot par mot (retour à la ligne simple, sans césure)."""
        mots = texte.split(" ")
        lignes: list[str] = []
        ligne_courante = ""
        for mot in mots:
            essai = f"{ligne_courante} {mot}".strip()
            if canevas.stringWidth(essai, police, taille) <= largeur_max:
                ligne_courante = essai
            else:
                if ligne_courante:
                    lignes.append(ligne_courante)
                ligne_courante = mot
        if ligne_courante:
            lignes.append(ligne_courante)
        return lignes

    def _pied_de_page(self, canevas: Canvas) -> None:
        canevas.setFillColor(_GRIS)
        texte = (
            f"{config.ENTREPRISE['nom']} - NINEA {config.ENTREPRISE['ninea']}"
            f" - RC {config.ENTREPRISE['rc']}"
        )
        taille = 7.5
        largeur_max = _LARGEUR - 2 * _MARGE
        while taille > 5.5 and canevas.stringWidth(texte, "Helvetica", taille) > largeur_max:
            taille -= 0.5
        canevas.setFont("Helvetica", taille)
        canevas.drawCentredString(_LARGEUR / 2, _MARGE / 2, texte)

    def _texte_ajuste(
        self, canevas: Canvas, texte: str, x: float, y: float, police: str,
        taille_max: float, taille_min: float, largeur_max: float,
    ) -> float:
        """Dessine `texte` en réduisant automatiquement la taille de police
        (entre `taille_max` et `taille_min`) jusqu'à tenir dans `largeur_max` -
        évite qu'un nom d'entreprise long ne déborde de la page (voir en-tête).
        Retourne la taille de police effectivement utilisée."""
        taille = taille_max
        while taille > taille_min and canevas.stringWidth(texte, police, taille) > largeur_max:
            taille -= 1
        canevas.setFont(police, taille)
        canevas.drawString(x, y, texte)
        return taille
