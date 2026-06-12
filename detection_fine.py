# -*- coding: utf-8 -*-
"""
La loupe : detection fine des donnees personnelles (etape 2 de la serrure).

Deux moteurs possibles, choisis par la variable CHEF_DETECTION_FINE :
  - "gliner"   (defaut) : modele urchade/gliner_multi_pii-v1 (Apache 2.0),
                optimise donnees personnelles, 6 langues dont le francais,
                tourne sur CPU. Telechargement ~1-2 Go au premier lancement.
  - "presidio" : Microsoft Presidio (MIT) + modele spaCy francais
                (necessite : python -m spacy download fr_core_news_md ;
                couverture francaise partielle, GLiNER reste conseille).
  - "off"      : loupe desactivee, la serrure v1 (regles) travaille seule.
  - toute autre valeur = faute de frappe -> traite comme "off" (et dit dans
    statut()) plutot que de declencher un telechargement surprise de 2 Go.

Regles de securite (les memes que partout) :
  - La loupe COMPLETE la serrure v1, elle ne la remplace jamais.
  - Loupe absente -> regles seules (choix d'exploitation, journalise une fois).
  - Loupe en panne -> code "loupe-en-panne" -> la demande reste en local.
    Une panne degrade la puissance, jamais la confidentialite.
  - GLiNER ne lit qu'une fenetre limitee (~384 jetons) : on DECOUPE donc le
    texte en fenetres qui se chevauchent et on fait l'union des trouvailles,
    sinon les donnees enfouies dans un long document seraient invisibles.
  - Un seul appel d'inference a la fois (verrou) : les moteurs sous-jacents
    ne sont pas garantis surs en multi-thread.
  - On ne journalise que des CODES ("pii:person"), jamais les valeurs.
"""

import os
import threading


def _env_float(nom, defaut):
    try:
        return float(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


MOTEURS_CONNUS = ("gliner", "presidio", "off")
MOTEUR = os.environ.get("CHEF_DETECTION_FINE", "gliner").strip().lower()
SEUIL = _env_float("CHEF_SEUIL_FIN", 0.4)
MODELE_GLINER = os.environ.get("CHEF_MODELE_GLINER", "urchade/gliner_multi_pii-v1")
MODELE_SPACY_FR = os.environ.get("CHEF_MODELE_SPACY", "fr_core_news_md")

# Fenetre de lecture de GLiNER : ~384 jetons. On decoupe a 1200 caracteres
# (marge large) avec 150 caracteres de chevauchement pour ne pas couper une
# donnee a la frontiere de deux fenetres.
FENETRE_CARACTERES = 1200
CHEVAUCHEMENT = 150

# Ce que la loupe cherche (labels du modele PII, en anglais : c'est la langue
# des etiquettes du modele, le TEXTE analyse peut etre en francais).
LABELS_PII = [
    "person", "organization", "address", "email", "phone number",
    "iban", "credit card number", "social security number",
    "date of birth", "passport number", "driver licence",
    "medical condition", "bank account number",
]

# Etat interne : None = pas encore essaye ; False = indisponible ; sinon le moteur.
_moteur_charge = None
_erreur_chargement = None
_verrou = threading.Lock()            # empeche deux chargements simultanes
_verrou_inference = threading.Lock()  # une seule analyse a la fois


def _fenetres(texte):
    """Decoupe le texte en fenetres qui se chevauchent (au moins une fenetre)."""
    if len(texte) <= FENETRE_CARACTERES:
        return [texte]
    pas = FENETRE_CARACTERES - CHEVAUCHEMENT
    return [texte[i:i + FENETRE_CARACTERES] for i in range(0, len(texte), pas)]


def _charger_gliner():
    from gliner import GLiNER  # import paresseux : seulement si on s'en sert
    modele = GLiNER.from_pretrained(MODELE_GLINER)

    def analyser(texte):
        codes = set()
        for fenetre in _fenetres(texte):
            for entite in modele.predict_entities(fenetre, LABELS_PII, threshold=SEUIL):
                codes.add("pii:" + entite["label"].replace(" ", "_"))
        return sorted(codes)

    return analyser


def _charger_presidio():
    from presidio_analyzer import AnalyzerEngine  # import paresseux
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "fr", "model_name": MODELE_SPACY_FR}],
    }
    provider = NlpEngineProvider(nlp_configuration=configuration)
    analyzer = AnalyzerEngine(
        nlp_engine=provider.create_engine(), supported_languages=["fr"]
    )

    def analyser(texte):
        resultats = analyzer.analyze(text=texte, language="fr", score_threshold=SEUIL)
        return sorted({"pii:" + r.entity_type.lower() for r in resultats})

    return analyser


def _obtenir_moteur():
    """Charge le moteur au premier appel. False si indisponible (et on s'en souvient)."""
    global _moteur_charge, _erreur_chargement
    if _moteur_charge is not None:
        return _moteur_charge
    with _verrou:
        if _moteur_charge is not None:  # un autre thread vient de le charger
            return _moteur_charge
        if MOTEUR == "off":
            _erreur_chargement = "desactivee (CHEF_DETECTION_FINE=off)"
            _moteur_charge = False
            return False
        if MOTEUR not in MOTEURS_CONNUS:
            _erreur_chargement = "valeur inconnue '%s' -> loupe desactivee (valeurs : gliner, presidio, off)" % MOTEUR
            _moteur_charge = False
            return False
        try:
            _moteur_charge = _charger_presidio() if MOTEUR == "presidio" else _charger_gliner()
        except Exception as erreur:  # lib absente, modele introuvable, etc.
            _erreur_chargement = "%s indisponible : %s" % (MOTEUR, erreur.__class__.__name__)
            _moteur_charge = False
    return _moteur_charge


def statut():
    """Pour le diagnostic et le journal : 'gliner', 'presidio', ou la raison de l'absence."""
    moteur = _obtenir_moteur()
    return MOTEUR if moteur else (_erreur_chargement or "indisponible")


def detecter_sensibilite_fine(texte):
    """Retourne les codes PII trouves par la loupe ([] si loupe absente).

    Toujours sans danger d'appel : ne leve jamais, ne retourne jamais None.
    Panne en cours d'analyse -> ["loupe-en-panne"] (prudence : local).
    """
    moteur = _obtenir_moteur()
    if not moteur:
        return []
    try:
        with _verrou_inference:
            return moteur(texte)
    except Exception:  # panne en cours de route : les regles v1 restent le filet
        return ["loupe-en-panne"]
