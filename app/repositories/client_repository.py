"""Repository des clients."""
from __future__ import annotations

import sqlite3

from app.models import Client
from app.repositories.base_repository import BaseRepository
from app.utils.formatting import horodatage_sql
from app.utils.recherche import decouper_termes


def _vers_client(row: sqlite3.Row) -> Client:
    return Client(
        id=row["id"],
        nom=row["nom"],
        adresse=row["adresse"],
        telephone=row["telephone"],
        modifie_le=row["modifie_le"],
    )


class ClientRepository(BaseRepository):
    """CRUD clients. Unicité sur (nom, adresse) normalisés : des homonymes
    sont autorisés s'ils ont une adresse différente. Le téléphone, quand il
    est renseigné, est en plus globalement unique (index partiel) — c'est,
    avec l'adresse, l'élément essentiel d'identification d'un client."""

    @staticmethod
    def normaliser_nom(nom: str) -> str:
        """Normalise un nom client : majuscules, espaces multiples réduits."""
        return " ".join(str(nom).upper().split())

    @staticmethod
    def normaliser_adresse(adresse: str) -> str:
        """Normalise une adresse : majuscules, espaces multiples réduits."""
        return " ".join(str(adresse or "").upper().split())

    @staticmethod
    def normaliser_telephone(telephone: str) -> str:
        """Normalise un numéro de téléphone : ne garde que les chiffres —
        deux saisies du même numéro avec un formatage différent (espaces,
        tirets, points) sont ainsi reconnues comme identiques. Condition
        nécessaire à la fusion automatique de doublons détectés par numéro
        (voir `ClientMaintenanceService.fusionner_doublon_telephone`) et à la
        contrainte d'unicité `idx_clients_telephone_unique`. Un numéro vide
        reste vide (pas de notion de doublon sans téléphone connu). Ne
        s'applique qu'aux nouvelles écritures — les numéros déjà stockés
        avant ce changement gardent leur formatage d'origine."""
        return "".join(caractere for caractere in str(telephone or "")
                       if caractere.isdigit())

    def lister(self) -> list[Client]:
        """Tous les clients, triés par nom."""
        rows = self.conn.execute("SELECT * FROM clients ORDER BY nom").fetchall()
        return [_vers_client(r) for r in rows]

    def obtenir(self, client_id: int) -> Client | None:
        row = self.conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return _vers_client(row) if row else None

    def chercher_par_nom(self, nom: str) -> Client | None:
        """Premier client portant ce nom (peu utile si des homonymes existent —
        préférer lister_par_nom ou chercher_par_nom_et_adresse)."""
        row = self.conn.execute(
            "SELECT * FROM clients WHERE nom = ? ORDER BY id", (self.normaliser_nom(nom),)
        ).fetchone()
        return _vers_client(row) if row else None

    def chercher_par_telephone(self, telephone: str) -> Client | None:
        """Client correspondant exactement à ce téléphone (unique quand renseigné)."""
        telephone_norm = self.normaliser_telephone(telephone)
        if not telephone_norm:
            return None
        row = self.conn.execute(
            "SELECT * FROM clients WHERE telephone = ?", (telephone_norm,)
        ).fetchone()
        return _vers_client(row) if row else None

    def lister_par_nom(self, nom: str) -> list[Client]:
        """Tous les clients homonymes (nom identique), triés par adresse."""
        rows = self.conn.execute(
            "SELECT * FROM clients WHERE nom = ? ORDER BY adresse",
            (self.normaliser_nom(nom),),
        ).fetchall()
        return [_vers_client(r) for r in rows]

    def chercher_par_nom_et_adresse(self, nom: str, adresse: str) -> Client | None:
        """Client correspondant exactement à ce nom ET cette adresse."""
        row = self.conn.execute(
            "SELECT * FROM clients WHERE nom = ? AND adresse = ?",
            (self.normaliser_nom(nom), self.normaliser_adresse(adresse)),
        ).fetchone()
        return _vers_client(row) if row else None

    def creer(self, client: Client) -> Client:
        """Insère un client (nom/adresse normalisés). Lève sqlite3.IntegrityError
        si un client identique (même nom, même adresse, ou même téléphone déjà
        utilisé) existe déjà."""
        client.nom = self.normaliser_nom(client.nom)
        client.adresse = self.normaliser_adresse(client.adresse)
        client.telephone = self.normaliser_telephone(client.telephone)
        horodatage = horodatage_sql()
        cur = self.conn.execute(
            "INSERT INTO clients (nom, adresse, telephone, modifie_le)"
            " VALUES (?,?,?,?)",
            (client.nom, client.adresse, client.telephone, horodatage),
        )
        client.id = cur.lastrowid
        client.modifie_le = horodatage
        self.conn.commit()
        return client

    def obtenir_ou_creer(self, nom: str, telephone: str = "", adresse: str = "") -> Client:
        """Retourne le client correspondant, créé au besoin.

        - Si un `telephone` est fourni et correspond à un client existant,
          cette fiche est réutilisée en priorité (le téléphone est le signal
          d'identification le plus fiable, quand il est connu).
        - Sinon, une correspondance exacte (nom, adresse) est réutilisée.
        - Si un seul homonyme existe et que sa fiche n'a **pas encore
          d'adresse renseignée**, on la complète avec celle fournie plutôt
          que de dupliquer (cas d'un client connu sans destination précisée
          jusque-là).
        - Sinon : une nouvelle fiche distincte est créée — deux personnes
          différentes portant le même nom (ex. deux « CHEIKH OUMAR ») ne sont
          jamais fusionnées sous prétexte qu'elles partagent un nom.
        """
        telephone_norm = self.normaliser_telephone(telephone)
        if telephone_norm:
            par_telephone = self.chercher_par_telephone(telephone_norm)
            if par_telephone:
                return par_telephone
        adresse_normalisee = self.normaliser_adresse(adresse)
        homonymes = self.lister_par_nom(nom)
        correspondance = next(
            (c for c in homonymes if c.adresse == adresse_normalisee), None)
        if correspondance:
            return correspondance
        if len(homonymes) == 1 and not homonymes[0].adresse and adresse_normalisee:
            client = homonymes[0]
            client.adresse = adresse_normalisee
            self.modifier(client)
            return client
        return self.creer(Client(nom=nom, telephone=telephone, adresse=adresse))

    def correspond_deja(self, nom: str, adresse: str = "") -> bool:
        """Vrai si obtenir_ou_creer(nom, adresse=adresse) retournerait un client
        existant (utile pour compter les créations réelles)."""
        adresse_normalisee = self.normaliser_adresse(adresse)
        homonymes = self.lister_par_nom(nom)
        if any(c.adresse == adresse_normalisee for c in homonymes):
            return True
        return len(homonymes) == 1 and not homonymes[0].adresse and bool(
            adresse_normalisee)

    def modifier(self, client: Client) -> None:
        client.nom = self.normaliser_nom(client.nom)
        client.adresse = self.normaliser_adresse(client.adresse)
        client.telephone = self.normaliser_telephone(client.telephone)
        horodatage = horodatage_sql()
        self.conn.execute(
            "UPDATE clients SET nom=?, adresse=?, telephone=?, modifie_le=? WHERE id=?",
            (client.nom, client.adresse, client.telephone, horodatage, client.id),
        )
        client.modifie_le = horodatage
        self.conn.commit()

    def supprimer(self, client_id: int) -> None:
        self.conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        self.conn.commit()

    def rechercher(self, q: str, limite: int = 30) -> list[Client]:
        """Recherche par nom, adresse OU téléphone (LIKE insensible à la
        casse, nom/adresse déjà normalisés en majuscules en base). Utilisée
        par l'endpoint API `GET /clients/recherche` et la vue UI « Vue
        client ». Supporte la recherche multi-termes (voir
        `app.utils.recherche.decouper_termes`, un seul terme suffit à matcher)."""
        termes = decouper_termes(q)
        if not termes:
            return []
        conditions = []
        params: list = []
        for terme in termes:
            motif_nom = f"%{self.normaliser_nom(terme)}%"
            motif_tel = f"%{terme.strip()}%"
            conditions.append("(nom LIKE ? OR adresse LIKE ? OR telephone LIKE ?)")
            params.extend([motif_nom, motif_nom, motif_tel])
        params.append(limite)
        rows = self.conn.execute(
            f"SELECT * FROM clients WHERE {' OR '.join(conditions)}"
            f" ORDER BY nom LIMIT ?",
            params,
        ).fetchall()
        return [_vers_client(r) for r in rows]

    def upsert_depuis_referentiel(
        self, nom: str, adresse: str, telephone: str, modifie_le: str,
    ) -> Client:
        """Upsert (nom, adresse) depuis la synchro descendante du référentiel
        (machine de facturation, `app.sync.referentiel_worker`) — préserve
        tel quel le `modifie_le` fourni par le serveur (jamais régénéré
        localement via `datetime('now')`, contrairement à `creer`/`modifier`) :
        la détection de conflit de fusion compare ce timestamp à sa valeur
        serveur au moment du rejeu, une valeur régénérée localement fausserait
        systématiquement cette comparaison."""
        nom_norm = self.normaliser_nom(nom)
        adresse_norm = self.normaliser_adresse(adresse)
        existant = self.chercher_par_nom_et_adresse(nom_norm, adresse_norm)
        if existant is not None:
            self.conn.execute(
                "UPDATE clients SET telephone = ?, modifie_le = ? WHERE id = ?",
                (telephone, modifie_le, existant.id),
            )
            self.conn.commit()
            existant.telephone = telephone
            existant.modifie_le = modifie_le
            return existant
        cur = self.conn.execute(
            "INSERT INTO clients (nom, adresse, telephone, modifie_le)"
            " VALUES (?,?,?,?)",
            (nom_norm, adresse_norm, telephone, modifie_le),
        )
        self.conn.commit()
        return Client(id=cur.lastrowid, nom=nom_norm, adresse=adresse_norm,
                      telephone=telephone, modifie_le=modifie_le)
