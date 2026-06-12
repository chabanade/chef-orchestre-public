# -*- coding: utf-8 -*-
"""
La loupe : detection fine des donnees personnelles (etape 2 de la serrure).

MULTI-MOTEURS (defense en profondeur) : CHEF_DETECTION_FINE accepte une liste,
par exemple "gliner" (defaut), "gliner,presidio" (double verification pour les
donnees ultra-sensibles : sante, avocat), "presidio", ou "off".
Chaque moteur liste analyse le texte, on fait l'UNION des trouvailles : il
suffit qu'UN moteur voie une donnee pour qu'elle soit traitee comme sensible.

Moteurs disponibles :
  - "gliner"   : modele urchade/gliner_multi_pii-v1 (Apache 2.0), optimise
                 donnees personnelles, 6 langues dont le francais, CPU.
                 Telechargement ~1-2 Go au premier lancement.
  - "presidio" : Microsoft Presidio (MIT) + modele spaCy francais
                 (necessite : python -m spacy download fr_core_news_md ;
                 couverture francaise partielle seul, utile en 2e couche).
  - "off"      : loupe desactivee, la serrure v1 (regles) travaille seule.
  - nom inconnu (faute de frappe) : ignore avec statut explicite, pas de
    telechargement surprise.

Mode strict (CHEF_LOUPE_STRICTE=1) : si UN des moteurs demandes n'a pas pu
se charger, TOUTE demande est traitee avec prudence (reste en local) tant
que la double verification promise n'est pas effective. A activer pour les
configurations ultra-sensibles.

Regles de securite (les memes que partout) :
  - La loupe COMPLETE la serrure v1 (regex), elle ne la remplace jamais.
  - Moteur en panne pendant une analyse -> code "loupe-en-panne" -> la
    demande reste en local. Une panne degrade la puissance, jamais la
    confidentialite.
  - GLiNER ne lit qu'une fenetre limitee (~384 jetons) : on DECOUPE le texte
    en fenetres qui se chevauchent et on fait l'union des trouvailles.
  - Un seul calcul d'inference a la fois (verrou) : les moteurs sous-jacents
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


MOTEURS_CONNUS = ("gliner", "presidio")
DEMANDES = [
    nom.strip().lower()
    for nom in os.environ.get("CHEF_DETECTION_FINE", "gliner").split(",")
    if nom.strip()
]
STRICTE = os.environ.get("CHEF_LOUPE_STRICTE", "0").strip() == "1"
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

# Etat interne, rempli au premier appel (sous verrou) :
#   _initialise : True une fois la tentative de chargement faite
#   _moteurs : liste de (nom, fonction_analyser)
#   _indisponibles : liste de "nom : raison" pour les moteurs demandes en echec
_initialise = False
_moteurs = []
_indisponibles = []
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


_CHARGEURS = {"gliner": _charger_gliner, "presidio": _charger_presidio}


def _initialiser():
    """Charge les moteurs demandes au premier appel (une seule fois, sous verrou)."""
    global _initialise
    if _initialise:
        return
    with _verrou:
        if _initialise:
            return
        if DEMANDES == ["off"]:
            _indisponibles.append("desactivee (CHEF_DETECTION_FINE=off)")
        else:
            for nom in DEMANDES:
                if nom == "off":
                    continue
                if nom not in MOTEURS_CONNUS:
                    _indisponibles.append("'%s' inconnu (valeurs : gliner, presidio, off)" % nom)
                    continue
                try:
                    _moteurs.append((nom, _CHARGEURS[nom]()))
                except Exception as erreur:  # lib absente, modele introuvable...
                    _indisponibles.append("%s indisponible : %s" % (nom, erreur.__class__.__name__))
        _initialise = True


def statut():
    """Pour le diagnostic et le journal : moteurs actifs + indisponibilites."""
    _initialiser()
    actifs = "+".join(nom for nom, _ in _moteurs) or "aucun moteur actif"
    if _indisponibles:
        return "%s (%s)" % (actifs, " ; ".join(_indisponibles))
    return actifs


def detecter_sensibilite_fine(texte):
    """Union des codes PII trouves par TOUS les moteurs actifs.

    Toujours sans danger d'appel : ne leve jamais, ne retourne jamais None.
    - Panne d'un moteur pendant l'analyse -> ajoute "loupe-en-panne" (prudence).
    - Mode strict : un moteur demande mais non charge -> "loupe-en-panne"
      systematique tant que la defense promise n'est pas complete.
    """
    _initialiser()
    codes = set()
    if STRICTE and _indisponibles and DEMANDES != ["off"]:
        codes.add("loupe-en-panne")
    for _nom, analyser in _moteurs:
        try:
            with _verrou_inference:
                codes.update(analyser(texte))
        except Exception:  # panne en cours de route : les regles v1 restent le filet
            codes.add("loupe-en-panne")
    return sorted(codes)
