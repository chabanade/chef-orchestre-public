# -*- coding: utf-8 -*-
"""
Tests de la serrure (detection.py) - zero dependance, stdlib uniquement.
Lancer : python test_detection.py
Toutes les donnees sont FICTIVES.
"""

import unittest

from detection import detecter_complexite, detecter_sensibilite


class TestSensibilite(unittest.TestCase):
    def test_iban_detecte(self):
        codes = detecter_sensibilite("Le reglement arrive sur FR76 3000 6000 0112 3456 7890 189 merci.")
        self.assertIn("iban", codes)

    def test_email_detecte(self):
        self.assertIn("email", detecter_sensibilite("Contacter jean.exemple@cabinet-test.fr pour le dossier."))

    def test_telephone_fr_detecte(self):
        self.assertIn("telephone_fr", detecter_sensibilite("Rappeler le 06 12 34 56 78 demain."))

    def test_numero_securite_sociale_detecte(self):
        self.assertIn("numero_securite_sociale", detecter_sensibilite("NIR : 1 80 02 75 123 456 78"))

    def test_mot_cle_patient(self):
        self.assertIn("mot-cle:patient", detecter_sensibilite("Le patient revient lundi."))

    def test_mot_cle_dossier_client(self):
        self.assertIn("mot-cle:dossier client", detecter_sensibilite("Voir le DOSSIER CLIENT 4521."))

    def test_anodin_ne_declenche_rien(self):
        self.assertEqual([], detecter_sensibilite("Explique la difference entre un volt et un ampere."))

    def test_pas_de_faux_positif_mot_partiel(self):
        # "rib" ne doit pas matcher dans "courrier au tribunal"
        codes = detecter_sensibilite("Envoyer le courrier au tribunal administratif.")
        self.assertNotIn("mot-cle:rib", codes)

    def test_culture_generale_patiente_ok(self):
        # adjectif "patiente" != mot entier "patient"
        codes = detecter_sensibilite("Une approche patiente donne de meilleurs resultats.")
        self.assertNotIn("mot-cle:patient", codes)


class TestComplexite(unittest.TestCase):
    def test_question_courte_simple(self):
        self.assertEqual([], detecter_complexite("Quelle heure est-il a Tokyo ?"))

    def test_mot_cle_rapport(self):
        self.assertTrue(detecter_complexite("Redige un rapport complet sur les pompes a chaleur."))

    def test_longueur_declenche(self):
        self.assertTrue(detecter_complexite("x" * 5000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
