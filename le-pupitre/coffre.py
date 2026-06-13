# -*- coding: utf-8 -*-
"""
Le coffre : le stockage CHIFFRE de l'historique de conversation.

C'est tout l'enjeu du Pupitre, et la raison de ne pas avoir forke un geant :
ici le chiffrement n'est pas une option rajoutee, c'est la PREMIERE note.

  - La base de donnees (conversations + messages) est chiffree au repos par
    SQLCipher (AES-256, le meme moteur que Signal). La passphrase est fournie
    AU LANCEMENT (terminal ou variable d'environnement), jamais stockee, jamais
    ecrite sur le disque. Sans elle, le fichier .db est un bloc illisible.
  - SQLCipher applique sa propre derivation forte (PBKDF2-HMAC-SHA512, 256 000
    iterations par defaut en v4) : une passphrase ne devient une cle qu'au prix
    d'un calcul couteux -> brute-force ralenti. (C'est exactement ce qui manquait
    a ConfiChat, ecarte a l'audit : il faisait un simple SHA-256 sans sel.)

Fail-closed (doctrine maison) : en production le chiffrement est EXIGE. Si le
moteur SQLCipher n'est pas installe, le coffre REFUSE de s'ouvrir plutot que de
stocker en clair en silence. Le repli clair (stdlib sqlite3) n'existe que pour
le DEVELOPPEMENT/les tests, et seulement si on le demande explicitement : il
hurle un avertissement.

Multi-plateforme : SQLCipher arrive via le paquet `sqlcipher3-wheels`, qui
fournit des binaires prets pour Windows, macOS et Linux (pip, sans compilation).
"""

import os
import sys
import time


class CoffreNonChiffreError(RuntimeError):
    """Leve quand le chiffrement est exige mais que SQLCipher est absent."""


def _charger_pilote(exiger_chiffrement):
    """Retourne (module_dbapi, chiffre: bool).

    Essaie SQLCipher d'abord. En son absence :
      - exiger_chiffrement=True  -> on REFUSE (fail-closed) ;
      - exiger_chiffrement=False -> repli stdlib sqlite3 EN CLAIR, avec un
        avertissement bruyant (dev/tests seulement).
    """
    try:
        from sqlcipher3 import dbapi2 as pilote  # paquet sqlcipher3-wheels
        return pilote, True
    except ImportError:
        if exiger_chiffrement:
            raise CoffreNonChiffreError(
                "SQLCipher (sqlcipher3-wheels) introuvable : le coffre refuse de "
                "s'ouvrir en clair. Installer la dependance (pip install "
                "sqlcipher3-wheels) ou, pour le DEV uniquement, passer "
                "exiger_chiffrement=False en connaissance de cause."
            )
        import sqlite3 as pilote
        sys.stderr.write(
            "[LE PUPITRE] AVERTISSEMENT : SQLCipher absent -> stockage EN CLAIR "
            "(mode developpement). NE JAMAIS utiliser ainsi avec de vraies "
            "donnees de client/patient.\n"
        )
        return pilote, False


class Coffre:
    """Le coffre chiffre. Ouvre/cree la base, tient le schema, lit/ecrit.

    Usage :
        coffre = Coffre("pupitre.db", passphrase)   # exige le chiffrement
        cid = coffre.nouvelle_conversation("Dossier Martin")
        coffre.ajouter_message(cid, "user", "Bonjour")
        coffre.messages(cid)
        coffre.fermer()
    """

    def __init__(self, chemin, passphrase, exiger_chiffrement=True):
        if exiger_chiffrement and not (passphrase or "").strip():
            raise CoffreNonChiffreError(
                "Passphrase vide : le coffre chiffre exige une passphrase non vide."
            )
        self.chemin = chemin
        self._pilote, self.chiffre = _charger_pilote(exiger_chiffrement)
        # isolation_level=None : autocommit, plus simple a raisonner pour un
        # historique append-only (on n'a pas de transactions multi-etapes).
        # check_same_thread=False : le serveur web sert les requetes depuis
        # plusieurs threads ; l'acces est serialise par un verrou cote serveur
        # (serveur.py). Sans ce verrou, ne PAS partager le coffre entre threads.
        self._cx = self._pilote.connect(chemin, isolation_level=None, check_same_thread=False)
        try:
            if self.chiffre:
                self._deverrouiller(passphrase)
            self._creer_schema()
        except Exception:
            # Mauvaise passphrase / fichier illisible : on REFERME le fichier
            # avant de propager, pour ne pas laisser un handle ouvert (sinon le
            # .db reste verrouille sur le disque sous Windows).
            self.fermer()
            raise

    # -- ouverture chiffree -------------------------------------------------
    def _deverrouiller(self, passphrase):
        """Donne la cle a SQLCipher PUIS verifie qu'elle est bonne.

        SQLCipher ne 'rejette' pas une mauvaise cle a la pose : il echoue a la
        PREMIERE lecture (le fichier dechiffre est alors du charabia). On force
        donc une lecture de controle : si elle echoue, la passphrase est fausse
        (ou le fichier corrompu) -> on leve une erreur claire, on ne cree
        SURTOUT pas une base parallele.
        """
        # SQLite n'autorise PAS de parametre lie (?) dans un PRAGMA : la forme
        # "PRAGMA key = ?" leve une erreur de syntaxe. On doit donc injecter la
        # passphrase en litteral -> on echappe les apostrophes (on les double)
        # pour qu'une passphrase contenant une ' ne casse pas la requete ni
        # n'ouvre d'injection. SQLCipher applique ensuite sa derivation forte
        # (PBKDF2-HMAC-SHA512) sur cette passphrase.
        pp = (passphrase or "").replace("'", "''")
        self._cx.execute("PRAGMA key = '%s'" % pp)
        try:
            self._cx.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except Exception as exc:  # mauvaise passphrase ou fichier non-SQLCipher
            raise CoffreNonChiffreError(
                "Impossible d'ouvrir le coffre : passphrase incorrecte ou "
                "fichier illisible. (Aucune base parallele n'a ete creee.)"
            ) from exc

    def _creer_schema(self):
        self._cx.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " titre TEXT NOT NULL,"
            " cree_le TEXT NOT NULL)"
        )
        self._cx.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " conversation_id INTEGER NOT NULL,"
            " role TEXT NOT NULL,"
            " contenu TEXT NOT NULL,"
            " cree_le TEXT NOT NULL,"
            " FOREIGN KEY (conversation_id) REFERENCES conversations(id))"
        )
        # Le corpus RAG (documents de l'utilisateur) vit DANS le coffre chiffre,
        # exactement comme les conversations : un PDF de client est aussi
        # sensible que la conversation a son sujet. 'vecteur' = l'embedding du
        # morceau, calcule en LOCAL (Ollama), stocke en JSON.
        self._cx.execute(
            "CREATE TABLE IF NOT EXISTS documents ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " source TEXT NOT NULL,"
            " position INTEGER NOT NULL,"
            " contenu TEXT NOT NULL,"
            " vecteur TEXT NOT NULL,"
            " cree_le TEXT NOT NULL)"
        )

    # -- ecriture -----------------------------------------------------------
    def nouvelle_conversation(self, titre):
        cur = self._cx.execute(
            "INSERT INTO conversations (titre, cree_le) VALUES (?, ?)",
            (titre or "Sans titre", _maintenant()),
        )
        return cur.lastrowid

    def ajouter_message(self, conversation_id, role, contenu):
        if role not in ("user", "assistant", "system"):
            raise ValueError("role inattendu : %r" % role)
        cur = self._cx.execute(
            "INSERT INTO messages (conversation_id, role, contenu, cree_le) "
            "VALUES (?, ?, ?, ?)",
            (conversation_id, role, contenu, _maintenant()),
        )
        return cur.lastrowid

    def renommer_conversation(self, conversation_id, titre):
        self._cx.execute(
            "UPDATE conversations SET titre = ? WHERE id = ?",
            (titre, conversation_id),
        )

    def supprimer_conversation(self, conversation_id):
        self._cx.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        self._cx.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))

    # -- lecture ------------------------------------------------------------
    def conversations(self):
        lignes = self._cx.execute(
            "SELECT id, titre, cree_le FROM conversations ORDER BY id DESC"
        ).fetchall()
        return [{"id": i, "titre": t, "cree_le": c} for (i, t, c) in lignes]

    def messages(self, conversation_id):
        lignes = self._cx.execute(
            "SELECT role, contenu, cree_le FROM messages "
            "WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
        return [{"role": r, "contenu": c, "cree_le": d} for (r, c, d) in lignes]

    # -- corpus RAG (documents) --------------------------------------------
    def ajouter_chunk(self, source, position, contenu, vecteur_json):
        self._cx.execute(
            "INSERT INTO documents (source, position, contenu, vecteur, cree_le) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, position, contenu, vecteur_json, _maintenant()),
        )

    def chunks(self):
        """Tous les morceaux du corpus, avec leur vecteur (JSON brut)."""
        lignes = self._cx.execute(
            "SELECT source, position, contenu, vecteur FROM documents"
        ).fetchall()
        return [{"source": s, "position": p, "contenu": c, "vecteur": v}
                for (s, p, c, v) in lignes]

    def sources(self):
        """Documents charges, avec le nombre de morceaux de chacun."""
        lignes = self._cx.execute(
            "SELECT source, COUNT(*) FROM documents GROUP BY source ORDER BY source"
        ).fetchall()
        return [{"source": s, "morceaux": n} for (s, n) in lignes]

    def supprimer_source(self, source):
        self._cx.execute("DELETE FROM documents WHERE source = ?", (source,))

    def fermer(self):
        try:
            self._cx.close()
        except Exception:
            pass


def _maintenant():
    return time.strftime("%Y-%m-%dT%H:%M:%S")
