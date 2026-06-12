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


class TestGreffier(unittest.TestCase):
    """La methode de l'armoire : pseudonymiser a l'aller, re-personnaliser au
    retour, table jamais exposee. Toutes donnees FICTIVES."""

    def test_aller_retour_complet(self):
        from greffier import Greffier
        g = Greffier()
        original = "Reglement sur FR76 3000 6000 0112 3456 7890 189, contact jean@exemple.fr"
        pseudo = g.pseudonymiser_texte(original)
        self.assertNotIn("FR76", pseudo)
        self.assertNotIn("jean@exemple.fr", pseudo)
        self.assertIn("<IBAN_1>", pseudo)
        self.assertIn("<EMAIL_1>", pseudo)
        reponse_cloud = "Le virement vers <IBAN_1> est confirme, prevenez <EMAIL_1>."
        finale = g.repersonnaliser(reponse_cloud)
        self.assertIn("FR76 3000 6000 0112 3456 7890 189", finale)
        self.assertIn("jean@exemple.fr", finale)

    def test_meme_valeur_meme_jeton(self):
        from greffier import Greffier
        g = Greffier()
        pseudo = g.pseudonymiser_texte("IBAN FR7630006000011234567890189 puis encore FR7630006000011234567890189")
        self.assertEqual(1, len(g.table))  # une seule entree pour deux occurrences
        self.assertEqual(2, pseudo.count("<IBAN_1>"))

    def test_pseudonymise_la_demande_complete(self):
        from greffier import Greffier
        g = Greffier()
        data = {"messages": [
            {"role": "user", "content": "Appelle le 06 12 34 56 78"},
            {"role": "user", "content": [{"type": "text", "text": "et ecris a paul@exemple.fr"}]},
        ]}
        nb = g.pseudonymiser_demande(data)
        self.assertEqual(2, nb)
        self.assertNotIn("06 12 34 56 78", data["messages"][0]["content"])
        self.assertNotIn("paul@exemple.fr", data["messages"][1]["content"][0]["text"])

    def test_texte_pseudonymise_ne_declenche_plus_les_regex(self):
        # Le coeur de la contre-verification du hook : apres greffier, plus
        # aucun motif regex ne doit rester.
        from greffier import Greffier
        g = Greffier()
        pseudo = g.pseudonymiser_texte("NIR 1 80 02 75 123 456 78, tel 06 12 34 56 78, iban FR7630006000011234567890189")
        codes_regex = [c for c in detecter_sensibilite(pseudo) if not c.startswith("mot-cle:")]
        self.assertEqual([], codes_regex)

    def test_mot_cle_contextuel_reste_apres_greffier(self):
        # Un mot-cle metier ("patient") n'est PAS une valeur remplacable :
        # il doit rester, et c'est lui qui fera refuser la route pseudo.
        from greffier import Greffier
        g = Greffier()
        pseudo = g.pseudonymiser_texte("Le patient est joignable au 06 12 34 56 78")
        self.assertIn("mot-cle:patient", detecter_sensibilite(pseudo))

    def test_destruction_armoire(self):
        from greffier import Greffier
        g = Greffier()
        g.pseudonymiser_texte("jean@exemple.fr")
        self.assertEqual(1, len(g.table))
        g.detruire()
        self.assertEqual(0, len(g.table))

    def test_jetons_restants_diagnostic(self):
        from greffier import jetons_restants
        self.assertEqual(["<IBAN_1>"], jetons_restants("Il reste <IBAN_1> ici"))
        self.assertEqual([], jetons_restants("rien"))

    def test_jeton_abime_par_le_modele_rattrape(self):
        # Risque n1 de l'etude 12/06 : le LLM abime parfois un jeton.
        # Le matching tolerant (idee LLM Guard) doit rattraper les variantes.
        from greffier import Greffier
        g = Greffier()
        g.pseudonymiser_texte("IBAN FR7630006000011234567890189")
        for variante in ("<iban 1>", "< IBAN_1 >", "<Iban-1>", "<IBAN  _ 1>"):
            restauree = g.repersonnaliser("Le compte %s est valide." % variante)
            self.assertIn("FR7630006000011234567890189", restauree, variante)

    def test_jeton_oprhelin_laisse_opaque(self):
        # Un jeton hallucine (absent de la table) reste tel quel : pas de
        # devinette, pas de fuite, et jetons_restants le rend visible.
        from greffier import Greffier, jetons_restants
        g = Greffier()
        g.pseudonymiser_texte("ecrire a jean@exemple.fr")
        reponse = g.repersonnaliser("Contact : <EMAIL_1> et aussi <IBAN_9>.")
        self.assertIn("jean@exemple.fr", reponse)
        self.assertEqual(["<IBAN_9>"], jetons_restants(reponse))

    def test_valeur_avec_caracteres_speciaux_regex(self):
        # La valeur restauree ne doit jamais etre interpretee par le moteur
        # de regex (anti-surprise backslash / dollar).
        from greffier import Greffier
        g = Greffier()
        g.table["<EMAIL_1>"] = r"jean\g<0>$1@exemple.fr"  # valeur piegee artificielle
        restauree = g.repersonnaliser("voir <email 1> svp")
        self.assertIn(r"jean\g<0>$1@exemple.fr", restauree)


class TestArmoireSession(unittest.TestCase):
    """L'armoire de session (decision 12/06) : pouvoir ITERER sur une
    conversation sans perdre la correspondance, TTL et plafond respectes."""

    def setUp(self):
        import greffier
        greffier._sessions.clear()

    def tearDown(self):
        import greffier
        greffier._sessions.clear()

    def test_meme_valeur_meme_jeton_entre_deux_tours(self):
        from greffier import Greffier, obtenir_armoire_session
        armoire = obtenir_armoire_session("conv-1")
        tour1 = Greffier(armoire=armoire)
        p1 = tour1.pseudonymiser_texte("IBAN FR7630006000011234567890189")
        tour1.detruire()  # fin du tour 1 : l'armoire de session survit
        tour2 = Greffier(armoire=obtenir_armoire_session("conv-1"))
        p2 = tour2.pseudonymiser_texte("verifie encore FR7630006000011234567890189")
        self.assertIn("<IBAN_1>", p1)
        self.assertIn("<IBAN_1>", p2)  # MEME jeton au tour 2

    def test_jeton_du_tour_1_restaurable_au_tour_5(self):
        from greffier import Greffier, obtenir_armoire_session
        tour1 = Greffier(armoire=obtenir_armoire_session("conv-2"))
        tour1.pseudonymiser_texte("paiement vers FR7630006000011234567890189")
        tour1.detruire()
        tour5 = Greffier(armoire=obtenir_armoire_session("conv-2"))
        reponse = tour5.repersonnaliser("Le compte <IBAN_1> mentionne plus tot est valide.")
        self.assertIn("FR7630006000011234567890189", reponse)

    def test_sessions_isolees(self):
        from greffier import Greffier, obtenir_armoire_session
        a = Greffier(armoire=obtenir_armoire_session("conv-a"))
        a.pseudonymiser_texte("a@exemple.fr")
        b = Greffier(armoire=obtenir_armoire_session("conv-b"))
        # la session B ne connait pas le jeton de la session A
        self.assertEqual("contact <EMAIL_1>", b.repersonnaliser("contact <EMAIL_1>"))

    def test_ttl_brule_l_armoire(self):
        import greffier
        from greffier import Greffier, obtenir_armoire_session
        armoire = obtenir_armoire_session("conv-ttl")
        g = Greffier(armoire=armoire)
        g.pseudonymiser_texte("jean@exemple.fr")
        # on vieillit artificiellement la session au-dela du TTL
        armoire.derniere_activite -= (greffier.TTL_MINUTES * 60 + 1)
        obtenir_armoire_session("autre-conv")  # tout acces declenche la purge
        self.assertNotIn("conv-ttl", greffier._sessions)
        self.assertEqual({}, armoire.table)  # brulee, pas seulement oubliee

    def test_plafond_de_sessions(self):
        import greffier
        from greffier import obtenir_armoire_session
        ancien = greffier.MAX_SESSIONS
        try:
            greffier.MAX_SESSIONS = 3
            for i in range(5):
                obtenir_armoire_session("conv-%d" % i)
            self.assertLessEqual(len(greffier._sessions), 3)
        finally:
            greffier.MAX_SESSIONS = ancien

    def test_compteur_compte_la_demande_pas_la_session(self):
        from greffier import Greffier, obtenir_armoire_session
        armoire = obtenir_armoire_session("conv-3")
        t1 = Greffier(armoire=armoire)
        data1 = {"messages": [{"role": "user", "content": "IBAN FR7630006000011234567890189"}]}
        self.assertEqual(1, t1.pseudonymiser_demande(data1))
        t2 = Greffier(armoire=armoire)
        data2 = {"messages": [{"role": "user", "content": "question sans rien de sensible"}]}
        self.assertEqual(0, t2.pseudonymiser_demande(data2))  # 0 pour CE tour

    def test_mode_autonome_brule_toujours(self):
        from greffier import Greffier
        g = Greffier()  # sans armoire : comportement historique
        g.pseudonymiser_texte("jean@exemple.fr")
        g.detruire()
        self.assertEqual({}, g.table)


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
