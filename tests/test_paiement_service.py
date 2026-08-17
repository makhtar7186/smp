"""Tests de PaiementService : solde (payé/partiel/impayé/sur-payé), append-only
strict des versements, remises tracées."""
from __future__ import annotations

from datetime import date

import pytest

from app.models import LigneVente
from app.repositories.base_repository import creer_connexion
from app.services.facturation_service import FacturationService
from app.services.paiement_service import PaiementService
from app.utils.validation import ErreurValidation


@pytest.fixture()
def services(tmp_path):
    conn = creer_connexion(tmp_path / "test.db")
    return FacturationService(conn), PaiementService(conn)


def _facture(facturation: FacturationService, numero: int, prix: int = 10000,
            quantite: int = 2, remise_taux: float = 0.0):
    return facturation.enregistrer_facture(
        numero=numero, date_facture=date(2026, 7, 1), nom_client="TEST",
        destination="DAKAR", remise_taux=remise_taux,
        lignes=[LigneVente(designation="SM TAPISSIER 140X190X", 
                           quantite=quantite, prix_unitaire=prix)],
    )


class TestSoldeFacture:
    def test_impayee(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260101)
        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.total == 20000
        assert solde.verse == 0
        assert solde.restant == 20000

    def test_partielle(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260102)
        paiements.enregistrer_versement(facture.id, 5000, date(2026, 7, 2))
        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.verse == 5000
        assert solde.restant == 15000

    def test_payee_integralement(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260103)
        paiements.enregistrer_versement(facture.id, 20000, date(2026, 7, 2))
        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.restant == 0

    def test_sur_payee(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260104)
        paiements.enregistrer_versement(facture.id, 25000, date(2026, 7, 2))
        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.restant == -5000  # trop-perçu autorisé librement

    def test_solde_tient_compte_de_la_remise(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260105, remise_taux=10.0)
        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.total == 18000  # 20000 - 10%

    def test_facture_introuvable(self, services):
        _, paiements = services
        with pytest.raises(ErreurValidation):
            paiements.calculer_solde_facture(9999)


class TestVersementAppendOnly:
    def test_correction_par_versement_negatif(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260106)
        paiements.enregistrer_versement(facture.id, 10000, date(2026, 7, 2))
        paiements.enregistrer_versement(facture.id, -3000, date(2026, 7, 3))
        historique = paiements.historique_versements(facture.id)
        assert len(historique) == 2
        assert [v.montant for v in historique] == [10000, -3000]
        solde = paiements.calculer_solde_facture(facture.id)
        assert solde.verse == 7000

    def test_montant_nul_refuse(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260107)
        with pytest.raises(ErreurValidation):
            paiements.enregistrer_versement(facture.id, 0, date(2026, 7, 2))

    def test_versement_facture_introuvable(self, services):
        _, paiements = services
        with pytest.raises(ErreurValidation):
            paiements.enregistrer_versement(9999, 1000, date(2026, 7, 2))


class TestRemiseTracee:
    def test_appliquer_remise_facture_trace_le_role(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260108)
        paiements.appliquer_remise_facture(facture.id, 15.0, "role_principal")
        maj = facturation.obtenir_facture(facture.id)
        assert maj.remise_taux == 15.0
        assert maj.remise_modifiee_par == "role_principal"
        assert maj.remise_modifiee_le

    def test_appliquer_remise_facture_taux_invalide(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260109)
        with pytest.raises(ErreurValidation):
            paiements.appliquer_remise_facture(facture.id, 150.0, "role_client")

    def test_appliquer_remise_annuelle_trace_le_role(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260110)
        client_id = facturation.obtenir_facture(facture.id).client_id
        remise = paiements.appliquer_remise_annuelle(
            client_id, 2026, 100000, 5.0, "note", "role_client")
        assert remise.modifie_par == "role_client"
        assert remise.montant == 5000


class TestRechercheEtSynthese:
    def test_rechercher_clients_par_nom(self, services):
        facturation, paiements = services
        _facture(facturation, 260111)
        resultats = paiements.rechercher_clients("TEST")
        assert any(c.nom == "TEST" for c in resultats)

    def test_total_depense_par_client(self, services):
        facturation, paiements = services
        facture = _facture(facturation, 260112, remise_taux=10.0)
        client_id = facturation.obtenir_facture(facture.id).client_id
        paiements.enregistrer_versement(facture.id, 5000, date(2026, 7, 2))
        synthese = paiements.total_depense_par_client(client_id)
        assert synthese.total_facture == 18000
        assert synthese.total_verse == 5000
        assert synthese.total_restant == 13000
        assert synthese.total_remises == 2000


class TestRechercheMultiTermesEtDestination:
    """La recherche des factures (page Paiements) doit matcher le nom client
    OU la destination, avec plusieurs termes séparés par une virgule
    (logique OU) — voir CLAUDE.md, section « Paiements »."""

    def _facture_a(self, facturation, numero, nom_client, destination):
        return facturation.enregistrer_facture(
            numero=numero, date_facture=date(2026, 7, 1), nom_client=nom_client,
            destination=destination,
            lignes=[LigneVente(designation="X", quantite=1,
                               prix_unitaire=1000)],
        )

    def test_recherche_par_destination(self, services):
        facturation, paiements = services
        self._facture_a(facturation, 260401, "ALPHA", "DAKAR")
        self._facture_a(facturation, 260402, "BETA", "RUFISQUE")
        resultat = paiements.lister_avec_solde(recherche="rufisque")
        assert [f.numero for f, _ in resultat] == [260402]

    def test_recherche_multi_termes(self, services):
        facturation, paiements = services
        self._facture_a(facturation, 260403, "ALPHA", "DAKAR")
        self._facture_a(facturation, 260404, "BETA", "THIES")
        self._facture_a(facturation, 260405, "GAMMA", "RUFISQUE")
        resultat = paiements.lister_avec_solde(recherche="ALPHA, THIES")
        assert sorted(f.numero for f, _ in resultat) == [260403, 260404]

    def test_rechercher_clients_multi_termes(self, services):
        facturation, paiements = services
        self._facture_a(facturation, 260406, "DELTA", "DAKAR")
        self._facture_a(facturation, 260407, "EPSILON", "DAKAR")
        resultats = paiements.rechercher_clients("DELTA, EPSILON")
        assert sorted(c.nom for c in resultats) == ["DELTA", "EPSILON"]

    def test_recherche_par_telephone_client(self, services):
        """Le téléphone est dénormalisé sur `Facture` (voir CLAUDE.md, section
        « Téléphone et matricule ») — la recherche des factures doit aussi
        matcher dessus, pas seulement nom/destination/numéro."""
        facturation, paiements = services
        facturation.enregistrer_facture(
            numero=260408, date_facture=date(2026, 7, 1), nom_client="ZETA",
            destination="DAKAR", telephone="77 111 22 33",
            lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)])
        facturation.enregistrer_facture(
            numero=260409, date_facture=date(2026, 7, 1), nom_client="ETA",
            destination="DAKAR", telephone="78 999 88 77",
            lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=1000)])
        resultat = paiements.lister_avec_solde(recherche="77 111 22 33")
        assert [f.numero for f, _ in resultat] == [260408]


class TestInclureArchivees:
    """Chaque application gère son propre système d'archivage (voir
    CLAUDE.md, section « Archivage ») : par défaut, `lister_avec_solde`/
    `totaux_globaux` respectent l'archivage de l'application principale
    (comme le reste de ses vues) ; `inclure_archivees=True` (utilisé par
    l'API distante) l'ignore, pour que le poste distant gère le sien."""

    def _facture(self, facturation, numero):
        return facturation.enregistrer_facture(
            numero=numero, date_facture=date(2026, 7, 1), nom_client="TEST",
            destination="DAKAR",
            lignes=[LigneVente(designation="X", quantite=1,
                               prix_unitaire=1000)],
        )

    def test_par_defaut_masque_les_factures_archivees(self, services):
        facturation, paiements = services
        facture = self._facture(facturation, 260501)
        facturation.archiver_ids([facture.id])
        resultat = paiements.lister_avec_solde()
        assert facture.numero not in [f.numero for f, _ in resultat]

    def test_inclure_archivees_les_montre(self, services):
        facturation, paiements = services
        facture = self._facture(facturation, 260502)
        facturation.archiver_ids([facture.id])
        resultat = paiements.lister_avec_solde(inclure_archivees=True)
        assert facture.numero in [f.numero for f, _ in resultat]

    def test_totaux_globaux_respecte_le_meme_defaut(self, services):
        facturation, paiements = services
        facture = self._facture(facturation, 260503)
        facturation.archiver_ids([facture.id])
        totaux_masques = paiements.totaux_globaux()
        totaux_inclus = paiements.totaux_globaux(inclure_archivees=True)
        assert totaux_masques.total_facture == 0
        assert totaux_inclus.total_facture == 1000


class TestSyntheseClientPeriodePrecise:
    """Vue client : filtre par année OU par période précise (Du/Au,
    prioritaire) — voir CLAUDE.md, section « Paiements »."""

    def _facture_a_date(self, facturation, numero, jour, prix=10000):
        return facturation.enregistrer_facture(
            numero=numero, date_facture=jour, nom_client="TEST", destination="DAKAR",
            lignes=[LigneVente(designation="X", quantite=1, prix_unitaire=prix)],
        )

    def test_toutes_annees_par_defaut(self, services):
        facturation, paiements = services
        f1 = self._facture_a_date(facturation, 260601, date(2025, 1, 1))
        client_id = facturation.obtenir_facture(f1.id).client_id
        self._facture_a_date(facturation, 260602, date(2026, 6, 1))
        synthese = paiements.total_depense_par_client(client_id)
        assert synthese.total_facture == 20000

    def test_filtre_par_annee_entiere(self, services):
        facturation, paiements = services
        f1 = self._facture_a_date(facturation, 260603, date(2025, 1, 1))
        client_id = facturation.obtenir_facture(f1.id).client_id
        self._facture_a_date(facturation, 260604, date(2026, 6, 1))
        synthese = paiements.total_depense_par_client(client_id, annee=2026)
        assert synthese.total_facture == 10000

    def test_periode_precise_prioritaire_sur_annee(self, services):
        facturation, paiements = services
        f1 = self._facture_a_date(facturation, 260605, date(2026, 1, 15))
        client_id = facturation.obtenir_facture(f1.id).client_id
        self._facture_a_date(facturation, 260606, date(2026, 6, 15))
        # un seul mois précis, même si `annee` est aussi fourni (ignoré)
        synthese = paiements.total_depense_par_client(
            client_id, annee=2026, date_debut=date(2026, 6, 1), date_fin=date(2026, 6, 30))
        assert synthese.total_facture == 10000

    def test_periode_a_cheval_sur_deux_annees_cumule_les_remises(self, services):
        facturation, paiements = services
        f1 = self._facture_a_date(facturation, 260607, date(2025, 12, 20))
        client_id = facturation.obtenir_facture(f1.id).client_id
        self._facture_a_date(facturation, 260608, date(2026, 1, 10))
        paiements.appliquer_remise_annuelle(client_id, 2025, 100000, 2.0, "", "local")
        paiements.appliquer_remise_annuelle(client_id, 2026, 100000, 3.0, "", "local")
        synthese = paiements.total_depense_par_client(
            client_id, date_debut=date(2025, 12, 1), date_fin=date(2026, 1, 31))
        assert synthese.total_facture == 20000
        assert synthese.total_remises == 2000 + 3000
