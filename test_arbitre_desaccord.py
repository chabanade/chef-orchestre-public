# -*- coding: utf-8 -*-
"""
Tests de l'arbitre de desaccord - stdlib uniquement, donnees FICTIVES.
Lancer : python test_arbitre_desaccord.py

L'arbitre est une fonction PURE : on lui injecte ce que chaque detecteur a vu
(des CODES), sans charger le moindre modele. On peut donc tout tester sans
installer GLiNER ni Presidio.
"""

import unittest

import arbitre_desaccord as arb


class TestNormalisation(unittest.TestCase):
    def test_regex_et_loupe_meme_categorie(self):
        # "iban" (regex) et "pii:iban" (loupe) doivent tomber sur le meme type.
        cats_regex, _ = arb.normaliser(["iban"])
        cats_loupe, _ = arb.normaliser(["pii:iban"])
        self.assertEqual({"IBAN"}, cats_regex)
        self.assertEqual({"IBAN"}, cats_loupe)

    def test_personne_loupe(self):
        cats, _ = arb.normaliser(["pii:person"])
        self.assertEqual({"PERSONNE"}, cats)

    def test_code_technique_mis_a_part(self):
        cats, tech = arb.normaliser(["loupe-en-panne", "iban"])
        self.assertEqual({"IBAN"}, cats)
        self.assertIn("loupe-en-panne", tech)

    def test_mot_cle_simple_indice_ignore_comme_type(self):
        # "mot-cle:patient" n'est pas un type d'entite ferme -> pas de categorie.
        cats, _ = arb.normaliser(["mot-cle:patient"])
        self.assertEqual(set(), cats)

    def test_mot_cle_parlant_mappe(self):
        cats, _ = arb.normaliser(["mot-cle:iban"])
        self.assertEqual({"IBAN"}, cats)

    def test_nouveaux_codes_date_et_compte(self):
        # Trous combles au banc 15/06 : la serrure produit ces codes, l'arbitre
        # doit les comprendre.
        cats, _ = arb.normaliser(["date_naissance", "compte_bancaire"])
        self.assertEqual({"DATE_NAISSANCE", "COMPTE"}, cats)


class TestConsensus(unittest.TestCase):
    def test_deux_capables_d_accord_sur_iban(self):
        # regex et gliner couvrent tous deux l'IBAN et le voient : consensus.
        d = arb.arbitrer({"regex": ["iban"], "gliner": ["pii:iban"]})
        self.assertTrue(d.sensible)
        self.assertEqual("faible", d.niveau_doute)
        self.assertEqual("ok", d.action)
        self.assertIn("IBAN", d.consensus)
        self.assertEqual([], d.desaccord)


class TestDesaccordReel(unittest.TestCase):
    def test_iban_vu_par_un_seul_de_deux_capables(self):
        # regex ET gliner savent voir un IBAN, mais seule la regex le voit :
        # desaccord REEL -> doute eleve -> escalade.
        d = arb.arbitrer({"regex": ["iban"], "gliner": []})
        self.assertTrue(d.sensible)
        self.assertEqual("eleve", d.niveau_doute)
        self.assertEqual("escalade", d.action)
        self.assertIn("IBAN", d.desaccord)

    def test_action_sur_masquage_configurable(self):
        d = arb.arbitrer({"regex": ["iban"], "gliner": []},
                         action_doute="sur-masquage")
        self.assertEqual("eleve", d.niveau_doute)
        self.assertEqual("sur-masquage", d.action)

    def test_union_jamais_reduite_par_le_desaccord(self):
        # Meme en cas de desaccord, l'IBAN reste dans l'union (rappel maximal :
        # on ne "vote" jamais pour laisser passer).
        d = arb.arbitrer({"regex": ["iban"], "gliner": []})
        self.assertIn("IBAN", d.union)


class TestIncapaciteStructurelle(unittest.TestCase):
    def test_nom_vu_par_gliner_seul_n_est_pas_un_desaccord(self):
        # La regex ne COUVRE pas PERSONNE : son silence n'est pas un desaccord.
        # PERSONNE n'a qu'un seul juge capable -> non corrobore, pas escalade.
        d = arb.arbitrer({"regex": [], "gliner": ["pii:person"]})
        self.assertTrue(d.sensible)
        self.assertIn("PERSONNE", d.non_corrobore)
        self.assertEqual([], d.desaccord)
        self.assertEqual("moyen", d.niveau_doute)
        self.assertEqual("ok", d.action)

    def test_non_corrobore_peut_escalader_si_demande(self):
        d = arb.arbitrer({"regex": [], "gliner": ["pii:person"]},
                         escalader_non_corrobore=True)
        self.assertEqual("escalade", d.action)


class TestPrioriteDuDoute(unittest.TestCase):
    def test_desaccord_l_emporte_sur_le_consensus(self):
        # Consensus sur EMAIL, mais desaccord sur IBAN : c'est le doute qui mene.
        d = arb.arbitrer({
            "regex": ["email", "iban"],
            "gliner": ["pii:email"],   # voit l'email, pas l'iban
        })
        self.assertIn("EMAIL", d.consensus)
        self.assertIn("IBAN", d.desaccord)
        self.assertEqual("eleve", d.niveau_doute)
        self.assertEqual("escalade", d.action)


class TestSignauxTechniques(unittest.TestCase):
    def test_panne_force_la_prudence_sans_pii(self):
        # Aucune PII, mais la loupe est en panne : on ne dit jamais "sur".
        d = arb.arbitrer({"regex": [], "gliner": ["loupe-en-panne"]})
        self.assertTrue(d.sensible)
        self.assertEqual("faible", d.niveau_doute)
        self.assertIn("loupe-en-panne", d.techniques)


class TestAnodin(unittest.TestCase):
    def test_rien_vu_par_personne(self):
        d = arb.arbitrer({"regex": [], "gliner": []})
        self.assertFalse(d.sensible)
        self.assertEqual("aucun", d.niveau_doute)
        self.assertEqual("ok", d.action)
        self.assertEqual([], d.union)

    def test_un_seul_detecteur_present_pas_de_desaccord(self):
        # Avec la regex seule (loupe absente), aucun desaccord n'est possible.
        d = arb.arbitrer({"regex": ["iban"]})
        self.assertTrue(d.sensible)
        self.assertEqual([], d.desaccord)
        # IBAN n'a qu'un juge present -> non corrobore (a surveiller), pas escalade.
        self.assertIn("IBAN", d.non_corrobore)
        self.assertEqual("ok", d.action)


class TestDetailAudit(unittest.TestCase):
    def test_detail_par_detecteur_pour_banc_d_essai(self):
        d = arb.arbitrer({"regex": ["iban"], "gliner": ["pii:person"]})
        self.assertEqual({"IBAN"}, set(d.detail["regex"]))
        self.assertEqual({"PERSONNE"}, set(d.detail["gliner"]))
        # La vue journal ne contient que des codes, jamais de valeur.
        journal = d.pour_journal()
        self.assertIn("niveau_doute", journal)
        self.assertIn("desaccord", journal)


class TestRouteEscaladee(unittest.TestCase):
    """Le selecteur de route locale apres avis de l'arbitre : escalade vers le
    palier FORT seulement sur action 'escalade' ET si un palier distinct existe.
    Toujours local (jamais le cloud)."""

    def _decision(self, action):
        return arb.Decision(sensible=True, niveau_doute="eleve", action=action)

    def test_escalade_vers_palier_fort(self):
        self.assertEqual("local-14b",
                         arb.route_escaladee(self._decision("escalade"), "local-4b", "local-14b"))

    def test_pas_d_escalade_si_action_ok(self):
        self.assertEqual("local-4b",
                         arb.route_escaladee(self._decision("ok"), "local-4b", "local-14b"))

    def test_pas_d_escalade_si_palier_non_distinct(self):
        # Defaut sur : route_forte == route_locale -> jamais d'escalade.
        self.assertEqual("local-4b",
                         arb.route_escaladee(self._decision("escalade"), "local-4b", "local-4b"))

    def test_decision_absente_reste_local(self):
        self.assertEqual("local-4b", arb.route_escaladee(None, "local-4b", "local-14b"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
