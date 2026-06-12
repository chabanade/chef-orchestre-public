# -*- coding: utf-8 -*-
"""
Tests de la serrure (detection.py + detection_fine.py) - stdlib uniquement.
Lancer : python test_detection.py
Toutes les donnees sont FICTIVES. Inclut les cas trouves par la revue
adversariale du 12/06/2026 (image non inspectable, IBAN minuscule, fenetres
GLiNER, valeur de configuration erronee).
"""

import unittest

import detection_fine
from detection import (
    _env_int,
    detecter_complexite,
    detecter_sensibilite,
    detecter_sensibilite_complete,
    extraire_texte,
)


class TestSensibilite(unittest.TestCase):
    def test_iban_detecte(self):
        codes = detecter_sensibilite("Le reglement arrive sur FR76 3000 6000 0112 3456 7890 189 merci.")
        self.assertIn("iban", codes)

    def test_iban_minuscule_detecte(self):
        # Trou trouve par la revue : un IBAN tape en minuscules doit etre vu.
        codes = detecter_sensibilite("vire sur fr7630006000011234567890189 stp")
        self.assertIn("iban", codes)

    def test_mot_iban_seul_detecte(self):
        self.assertIn("mot-cle:iban", detecter_sensibilite("Envoie-moi ton IBAN par retour."))

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


class TestExtraction(unittest.TestCase):
    """extraire_texte doit tout lire, et lever le drapeau sur ce qu'il ne lit pas."""

    def test_messages_simples(self):
        texte, drapeau = extraire_texte({"messages": [{"role": "user", "content": "bonjour"}]})
        self.assertEqual("bonjour", texte)
        self.assertFalse(drapeau)

    def test_blocs_textes(self):
        data = {"messages": [{"role": "user", "content": [{"type": "text", "text": "un"}, {"type": "text", "text": "deux"}]}]}
        texte, drapeau = extraire_texte(data)
        self.assertIn("un", texte)
        self.assertIn("deux", texte)
        self.assertFalse(drapeau)

    def test_image_leve_le_drapeau(self):
        # Trou BLOQUANT trouve par la revue : une image doit lever le drapeau.
        data = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": "analyse ce document"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxxx"}},
        ]}]}
        texte, drapeau = extraire_texte(data)
        self.assertIn("analyse", texte)
        self.assertTrue(drapeau)

    def test_prompt_legacy_str(self):
        # Trou BLOQUANT trouve par la revue : l'endpoint legacy /completions.
        texte, drapeau = extraire_texte({"prompt": "le patient revient lundi"})
        self.assertIn("patient", texte)
        self.assertFalse(drapeau)

    def test_prompt_legacy_liste(self):
        texte, _ = extraire_texte({"prompt": ["un", "deux"]})
        self.assertIn("un", texte)
        self.assertIn("deux", texte)

    def test_input_responses(self):
        texte, _ = extraire_texte({"input": "verifie cet iban fr7630006000011234567890189"})
        self.assertIn("iban", texte)

    def test_input_blocs(self):
        data = {"input": [{"role": "user", "content": [{"type": "input_text", "text": "?"}]}]}
        _, drapeau = extraire_texte(data)
        self.assertTrue(drapeau)  # type de bloc inconnu -> prudence


class TestLoupe(unittest.TestCase):
    """La detection fine (loupe) testee avec des moteurs factices : pas besoin
    d'installer GLiNER/Presidio pour prouver le couplage, l'union multi-moteurs,
    le filet de panne et le mode strict."""

    def setUp(self):
        self._etat = (detection_fine._initialise, list(detection_fine._moteurs),
                      list(detection_fine._indisponibles), detection_fine.STRICTE)

    def tearDown(self):
        (detection_fine._initialise, moteurs, indispo, detection_fine.STRICTE) = self._etat
        detection_fine._moteurs[:] = moteurs
        detection_fine._indisponibles[:] = indispo

    def _installe(self, moteurs, indisponibles=(), stricte=False):
        detection_fine._initialise = True
        detection_fine._moteurs[:] = moteurs
        detection_fine._indisponibles[:] = list(indisponibles)
        detection_fine.STRICTE = stricte

    def test_loupe_absente_regles_seules(self):
        # Sur cette machine GLiNER n'est pas installe : la loupe doit se
        # declarer indisponible SANS casser, et les regles v1 continuent.
        detection_fine._initialise = False
        detection_fine._moteurs[:] = []
        detection_fine._indisponibles[:] = []
        self.assertEqual([], detection_fine.detecter_sensibilite_fine("texte anodin"))
        codes = detecter_sensibilite_complete("Le patient revient lundi.")
        self.assertIn("mot-cle:patient", codes)

    def test_union_regles_plus_loupe(self):
        # Moteur factice : la loupe voit un nom de personne que les regex ratent.
        self._installe([("factice", lambda texte: ["pii:person"])])
        codes = detecter_sensibilite_complete("Convoquer Jean Exemple au 06 12 34 56 78.")
        self.assertIn("telephone_fr", codes)   # serrure v1
        self.assertIn("pii:person", codes)     # loupe

    def test_double_verification_union_des_moteurs(self):
        # Deux moteurs en parallele : il suffit qu'UN voie pour que ce soit vu.
        self._installe([
            ("moteur-a", lambda texte: ["pii:person"]),
            ("moteur-b", lambda texte: ["pii:address"]),
        ])
        codes = detection_fine.detecter_sensibilite_fine("texte")
        self.assertIn("pii:person", codes)
        self.assertIn("pii:address", codes)

    def test_double_verification_un_moteur_en_panne(self):
        # Le moteur B crashe : on garde les trouvailles de A ET on force la prudence.
        def casse(texte):
            raise RuntimeError("oom")
        self._installe([("moteur-a", lambda texte: ["pii:person"]), ("moteur-b", casse)])
        codes = detection_fine.detecter_sensibilite_fine("texte")
        self.assertIn("pii:person", codes)
        self.assertIn("loupe-en-panne", codes)

    def test_mode_strict_moteur_manquant(self):
        # Mode strict : un moteur demande mais indisponible -> prudence permanente.
        self._installe([("moteur-a", lambda texte: [])],
                       indisponibles=["presidio indisponible : ImportError"], stricte=True)
        self.assertIn("loupe-en-panne", detection_fine.detecter_sensibilite_fine("texte"))

    def test_mode_normal_moteur_manquant_continue(self):
        # Mode normal : moteur manquant = signale dans statut(), pas de blocage.
        self._installe([("moteur-a", lambda texte: [])],
                       indisponibles=["presidio indisponible : ImportError"], stricte=False)
        self.assertEqual([], detection_fine.detecter_sensibilite_fine("texte"))
        self.assertIn("presidio indisponible", detection_fine.statut())

    def test_loupe_seule_detecte(self):
        # Un nom seul, sans aucun motif regex : seul la loupe le voit.
        self._installe([("factice", lambda texte: ["pii:person"])])
        codes = detecter_sensibilite_complete("Prepare une note sur Jean Exemple.")
        self.assertEqual(["pii:person"], codes)

    def test_panne_de_loupe_force_la_prudence(self):
        def moteur_casse(texte):
            raise RuntimeError("plus de memoire")
        self._installe([("factice", moteur_casse)])
        codes = detecter_sensibilite_complete("texte quelconque")
        self.assertIn("loupe-en-panne", codes)  # panne -> traite comme sensible -> local

    def test_valeur_moteur_inconnue_desactive_proprement(self):
        # Faute de frappe dans CHEF_DETECTION_FINE : pas de telechargement
        # surprise de 2 Go, moteur ignore, statut explicite.
        ancien = detection_fine.DEMANDES
        try:
            detection_fine.DEMANDES = ["gilner"]  # typo volontaire
            detection_fine._initialise = False
            detection_fine._moteurs[:] = []
            detection_fine._indisponibles[:] = []
            self.assertEqual([], detection_fine.detecter_sensibilite_fine("texte"))
            self.assertIn("inconnu", detection_fine.statut())
        finally:
            detection_fine.DEMANDES = ancien
            detection_fine._initialise = False
            detection_fine._moteurs[:] = []
            detection_fine._indisponibles[:] = []

    def test_fenetres_recouvrement(self):
        # Texte long : plusieurs fenetres, qui se chevauchent, couvrant TOUT
        # le texte (correctif de la troncature silencieuse de GLiNER).
        texte = "x" * 5000
        fenetres = detection_fine._fenetres(texte)
        self.assertGreater(len(fenetres), 1)
        self.assertTrue(all(len(f) <= detection_fine.FENETRE_CARACTERES for f in fenetres))
        total = sum(len(f) for f in fenetres)
        self.assertGreaterEqual(total, len(texte))  # tout est couvert (avec recouvrement)

    def test_fenetre_unique_texte_court(self):
        self.assertEqual(["abc"], detection_fine._fenetres("abc"))


class TestRobustesse(unittest.TestCase):
    def test_seuil_env_malforme_ne_crashe_pas(self):
        import os
        os.environ["TEST_SEUIL_CASSE"] = "abc"
        try:
            self.assertEqual(4000, _env_int("TEST_SEUIL_CASSE", 4000))
        finally:
            del os.environ["TEST_SEUIL_CASSE"]


class TestComplexite(unittest.TestCase):
    def test_question_courte_simple(self):
        self.assertEqual([], detecter_complexite("Quelle heure est-il a Tokyo ?"))

    def test_mot_cle_rapport(self):
        self.assertTrue(detecter_complexite("Redige un rapport complet sur les pompes a chaleur."))

    def test_longueur_declenche(self):
        self.assertTrue(detecter_complexite("x" * 5000))


if __name__ == "__main__":
    unittest.main(verbosity=2)
