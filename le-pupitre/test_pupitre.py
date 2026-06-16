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
import rag
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


class TestChiffrementReel(unittest.TestCase):
    """Quand SQLCipher EST present (machine de deploiement / venv), on prouve le
    chiffrement REEL. C'est le bug du 'PRAGMA key = ?' (qui empechait toute
    ouverture chiffree, corrige le 13/06/2026) transforme en loi : sans ce test,
    le mode chiffre n'etait jamais exerce et la regression passait inapercue."""

    def setUp(self):
        try:
            import sqlcipher3  # noqa: F401
        except ImportError:
            self.skipTest("SQLCipher absent : test du chiffrement reel ignore.")
        fd, self.chemin = tempfile.mkstemp(suffix=".db", prefix="pupitre-chiffre-")
        os.close(fd)
        os.remove(self.chemin)  # chemin neuf, pas un fichier vide

    def tearDown(self):
        if hasattr(self, "chemin") and os.path.exists(self.chemin):
            os.remove(self.chemin)

    def test_aller_retour_chiffre(self):
        c = Coffre(self.chemin, "bonne-cle-2026")  # exiger_chiffrement=True
        cid = c.nouvelle_conversation("Dossier")
        c.ajouter_message(cid, "user", "secret du client")
        c.fermer()
        c2 = Coffre(self.chemin, "bonne-cle-2026")
        self.assertEqual("secret du client", c2.messages(cid)[0]["contenu"])
        c2.fermer()

    def test_mauvaise_passphrase_refusee(self):
        c = Coffre(self.chemin, "bonne-cle-2026")
        c.ajouter_message(c.nouvelle_conversation("D"), "user", "secret")
        c.fermer()
        with self.assertRaises(CoffreNonChiffreError):
            Coffre(self.chemin, "mauvaise-cle")  # ne doit PAS s'ouvrir

    def test_fichier_illisible_en_clair(self):
        c = Coffre(self.chemin, "bonne-cle-2026")
        c.ajouter_message(c.nouvelle_conversation("D"), "user", "secret")
        c.fermer()
        with open(self.chemin, "rb") as f:
            entete = f.read(16)
        self.assertFalse(entete.startswith(b"SQLite format 3"))  # pas de SQLite en clair


class TestVersion(unittest.TestCase):
    """Ossature evolutive : version du produit + mode de MAJ (sans appel reseau)."""

    def test_version_non_vide(self):
        import version
        infos = version.infos_version()
        self.assertTrue(infos["version"])
        self.assertIn(infos["mode_maj"], version.MODES_MAJ)
        self.assertIn("canal_configure", infos)

    def test_mode_maj_par_defaut_prudent(self):
        import version
        ancien = os.environ.pop("CHEF_MAJ_MODE", None)
        try:
            self.assertEqual("manuel", version.mode_maj())  # defaut prudent
        finally:
            if ancien is not None:
                os.environ["CHEF_MAJ_MODE"] = ancien

    def test_mode_maj_invalide_retombe_sur_manuel(self):
        import version
        ancien = os.environ.get("CHEF_MAJ_MODE")
        os.environ["CHEF_MAJ_MODE"] = "n_importe_quoi"
        try:
            self.assertEqual("manuel", version.mode_maj())
        finally:
            if ancien is None:
                os.environ.pop("CHEF_MAJ_MODE", None)
            else:
                os.environ["CHEF_MAJ_MODE"] = ancien


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

    def test_raisonnement_champ_dedie(self):
        # Forme moderne : litellm/ollama mettent le raisonnement a part.
        rep = {"choices": [{"message": {
            "role": "assistant", "content": "4", "reasoning_content": "2+2 donne 4."}}]}
        self.assertEqual("4", relais.extraire_reponse(rep))
        self.assertEqual("2+2 donne 4.", relais.extraire_raisonnement(rep))

    def test_raisonnement_inline_think_est_retire_de_la_reponse(self):
        # Forme ancienne : raisonnement inscrit en <think>...</think> dans le texte.
        rep = {"choices": [{"message": {
            "role": "assistant", "content": "<think>je calcule</think>La reponse est 4."}}]}
        self.assertEqual("La reponse est 4.", relais.extraire_reponse(rep))
        self.assertEqual("je calcule", relais.extraire_raisonnement(rep))

    def test_aucun_raisonnement(self):
        rep = {"choices": [{"message": {"role": "assistant", "content": "Bonjour."}}]}
        self.assertEqual("", relais.extraire_raisonnement(rep))


class FauxEmbedder:
    """Embedder deterministe pour les tests (aucun reseau, rien a installer) :
    un texte devient le compte de mots d'un petit vocabulaire fixe. Deux textes
    qui parlent de la meme chose ont des vecteurs proches -> le cosinus classe
    correctement, ce qui suffit a prouver la LOGIQUE du RAG."""

    VOCAB = ["chat", "chien", "facture", "patient", "iban"]

    def vecteur(self, texte):
        return self.vecteurs([texte])[0]

    def vecteurs(self, textes):
        out = []
        for t in textes:
            bas = (t or "").lower()
            out.append([float(bas.count(mot)) for mot in self.VOCAB])
        return out


class TestRagLogique(unittest.TestCase):
    def test_decouper_texte_court_un_seul_morceau(self):
        self.assertEqual(["bonjour"], rag.decouper("bonjour"))

    def test_decouper_couvre_tout_avec_chevauchement(self):
        texte = "mot " * 1000  # ~4000 caracteres
        morceaux = rag.decouper(texte, taille=1000, chevauchement=150)
        self.assertGreater(len(morceaux), 1)
        self.assertTrue(all(len(m) <= 1000 for m in morceaux))

    def test_cosinus_valeurs_connues(self):
        self.assertAlmostEqual(1.0, rag.cosinus([1, 0], [2, 0]))   # meme direction
        self.assertAlmostEqual(0.0, rag.cosinus([1, 0], [0, 1]))   # orthogonaux
        self.assertEqual(0.0, rag.cosinus([0, 0], [1, 1]))          # vecteur nul -> 0, pas de crash

    def test_construire_contexte_vide(self):
        self.assertIsNone(rag.construire_contexte([]))

    def test_construire_contexte_anti_invention(self):
        ctx = rag.construire_contexte([{"source": "dossier.pdf", "contenu": "extrait"}])
        self.assertIn("dossier.pdf", ctx)
        self.assertIn("extrait", ctx)
        self.assertIn("inventer", ctx.lower())  # consigne anti-hallucination presente


class TestBibliotheque(unittest.TestCase):
    def setUp(self):
        fd, self.chemin = tempfile.mkstemp(suffix=".db", prefix="pupitre-rag-")
        os.close(fd)
        os.remove(self.chemin)
        self.coffre = Coffre(self.chemin, "p", exiger_chiffrement=False)
        self.biblio = rag.Bibliotheque(self.coffre, FauxEmbedder())

    def tearDown(self):
        self.coffre.fermer()
        if os.path.exists(self.chemin):
            os.remove(self.chemin)

    def test_ingerer_compte_les_morceaux(self):
        n = self.biblio.ingerer("note.txt", "Le chat dort sur le canape.")
        self.assertEqual(1, n)
        self.assertEqual([{"source": "note.txt", "morceaux": 1}], self.coffre.sources())

    def test_interroger_retrouve_le_bon_extrait(self):
        self.biblio.ingerer("animaux.txt", "Le chat dort sur le canape.")
        self.biblio.ingerer("jardin.txt", "Le chien aboie dans le jardin.")
        self.biblio.ingerer("compta.txt", "La facture du patient est elevee.")
        res = self.biblio.interroger("ou est le chat", k=1)
        self.assertEqual(1, len(res))
        self.assertEqual("animaux.txt", res[0]["source"])

    def test_interroger_corpus_vide(self):
        self.assertEqual([], self.biblio.interroger("quoi que ce soit"))

    def test_supprimer_source(self):
        self.biblio.ingerer("a.txt", "Le chat.")
        self.biblio.ingerer("b.txt", "Le chien.")
        self.coffre.supprimer_source("a.txt")
        sources = [s["source"] for s in self.coffre.sources()]
        self.assertEqual(["b.txt"], sources)

    def test_corpus_range_dans_le_coffre(self):
        # Le corpus RAG doit vivre dans le MEME coffre (donc chiffre en prod).
        self.biblio.ingerer("secret.txt", "iban et facture du patient")
        chunks = self.coffre.chunks()
        self.assertEqual(1, len(chunks))
        self.assertIn("vecteur", chunks[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
