# -*- coding: utf-8 -*-
"""
Tests du Pupitre - stdlib uniquement (aucune dependance a installer).
Lancer : python test_pupitre.py

Le coffre est teste en mode REPLI CLAIR (stdlib sqlite3) : ca prouve toute la
logique de stockage (creation, aller-retour, isolation, suppression). Le
chiffrement REEL (SQLCipher) se prouve au deploiement, par un test d'ouverture
avec mauvaise passphrase (voir README) : la dependance n'est pas installee ici
pour respecter "rien sur le PC". On teste tout de meme que le mode EXIGE
refuse de s'ouvrir en clair (fail-closed).
"""

import os
import tempfile
import unittest

import coffre as coffre_mod
import relais
from coffre import Coffre, CoffreNonChiffreError


class TestCoffre(unittest.TestCase):
    def setUp(self):
        fd, self.chemin = tempfile.mkstemp(suffix=".db", prefix="pupitre-test-")
        os.close(fd)
        os.remove(self.chemin)  # on veut un chemin neuf, pas un fichier vide
        # exiger_chiffrement=False : repli stdlib pour tester la LOGIQUE.
        self.coffre = Coffre(self.chemin, "passphrase-de-test", exiger_chiffrement=False)

    def tearDown(self):
        self.coffre.fermer()
        for p in (self.chemin,):
            if os.path.exists(p):
                os.remove(p)

    def test_aller_retour_message(self):
        cid = self.coffre.nouvelle_conversation("Dossier fictif")
        self.coffre.ajouter_message(cid, "user", "Bonjour, question anodine.")
        self.coffre.ajouter_message(cid, "assistant", "Bonjour, voici la reponse.")
        msgs = self.coffre.messages(cid)
        self.assertEqual(2, len(msgs))
        self.assertEqual("user", msgs[0]["role"])
        self.assertEqual("Bonjour, question anodine.", msgs[0]["contenu"])
        self.assertEqual("assistant", msgs[1]["role"])

    def test_liste_conversations_ordre_recent_dabord(self):
        a = self.coffre.nouvelle_conversation("Premiere")
        b = self.coffre.nouvelle_conversation("Seconde")
        convs = self.coffre.conversations()
        self.assertEqual(b, convs[0]["id"])  # la plus recente en tete
        self.assertEqual(a, convs[1]["id"])

    def test_isolation_entre_conversations(self):
        a = self.coffre.nouvelle_conversation("A")
        b = self.coffre.nouvelle_conversation("B")
        self.coffre.ajouter_message(a, "user", "secret de A")
        self.assertEqual(0, len(self.coffre.messages(b)))
        self.assertEqual(1, len(self.coffre.messages(a)))

    def test_role_invalide_refuse(self):
        cid = self.coffre.nouvelle_conversation("X")
        with self.assertRaises(ValueError):
            self.coffre.ajouter_message(cid, "robot", "?")

    def test_renommer_et_supprimer(self):
        cid = self.coffre.nouvelle_conversation("Brouillon")
        self.coffre.ajouter_message(cid, "user", "a")
        self.coffre.renommer_conversation(cid, "Dossier Martin")
        self.assertEqual("Dossier Martin", self.coffre.conversations()[0]["titre"])
        self.coffre.supprimer_conversation(cid)
        self.assertEqual(0, len(self.coffre.conversations()))
        self.assertEqual(0, len(self.coffre.messages(cid)))

    def test_persistance_apres_reouverture(self):
        cid = self.coffre.nouvelle_conversation("Persistante")
        self.coffre.ajouter_message(cid, "user", "je dois survivre")
        self.coffre.fermer()
        # On rouvre le MEME fichier : les donnees doivent etre la.
        rouvert = Coffre(self.chemin, "passphrase-de-test", exiger_chiffrement=False)
        try:
            msgs = rouvert.messages(cid)
            self.assertEqual(1, len(msgs))
            self.assertEqual("je dois survivre", msgs[0]["contenu"])
        finally:
            rouvert.fermer()


class TestFailClosed(unittest.TestCase):
    """En mode EXIGE, l'absence de SQLCipher doit REFUSER l'ouverture, jamais
    stocker en clair en silence."""

    def test_exige_sans_sqlcipher_refuse(self):
        # Sur cette machine SQLCipher n'est pas installe : exiger_chiffrement=True
        # doit lever, pas creer une base en clair.
        try:
            import sqlcipher3  # noqa: F401
            self.skipTest("SQLCipher present : ce test vise une machine sans.")
        except ImportError:
            pass
        with self.assertRaises(CoffreNonChiffreError):
            Coffre("ne-doit-pas-exister.db", "passphrase", exiger_chiffrement=True)
        self.assertFalse(os.path.exists("ne-doit-pas-exister.db"))

    def test_passphrase_vide_refusee(self):
        with self.assertRaises(CoffreNonChiffreError):
            Coffre("x.db", "   ", exiger_chiffrement=True)


class TestRelais(unittest.TestCase):
    def test_construire_requete_format_openai(self):
        msgs = [
            {"role": "user", "contenu": "Bonjour"},
            {"role": "assistant", "contenu": "Salut"},
        ]
        req = relais.construire_requete(msgs, "chef-auto")
        self.assertEqual("chef-auto", req["model"])
        self.assertFalse(req["stream"])  # v1 non-streamee
        self.assertEqual([{"role": "user", "content": "Bonjour"},
                          {"role": "assistant", "content": "Salut"}], req["messages"])

    def test_construire_requete_ignore_roles_inconnus(self):
        msgs = [{"role": "user", "contenu": "ok"}, {"role": "note", "contenu": "interne"}]
        req = relais.construire_requete(msgs, "m")
        self.assertEqual(1, len(req["messages"]))  # le role 'note' est filtre

    def test_extraire_reponse_standard(self):
        rep = {"choices": [{"message": {"role": "assistant", "content": "La reponse."}}]}
        self.assertEqual("La reponse.", relais.extraire_reponse(rep))

    def test_extraire_reponse_forme_inattendue_ne_crashe_pas(self):
        self.assertEqual("", relais.extraire_reponse({"oups": 1}))
        self.assertEqual("", relais.extraire_reponse(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
