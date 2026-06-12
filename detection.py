# -*- coding: utf-8 -*-
"""
Le cerveau de la serrure : detection de sensibilite et de complexite.

Fichier en Python PUR (aucune dependance) : testable sur n'importe quelle
machine avec `python test_detection.py`, sans rien installer.
La plomberie LiteLLM, elle, vit dans chef_orchestre_hook.py.
"""

import json
import os
import re
import time


def _env_int(nom, defaut):
    """Lit un entier dans l'environnement ; valeur malformee -> defaut (jamais de crash)."""
    try:
        return int(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


def _env_float(nom, defaut):
    try:
        return float(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


SEUIL_COMPLEXITE_CARACTERES = _env_int("CHEF_SEUIL_LOURD", 4000)
JOURNAL = os.environ.get("CHEF_JOURNAL", os.path.join(os.path.dirname(__file__), "journal-routage.jsonl"))

# Codes "techniques" : ils forcent la prudence (local) sans signifier qu'une
# donnee sensible a ete VUE. Le hook s'en sert pour adapter son message.
CODES_TECHNIQUES = {
    "loupe-en-panne",
    "detection-en-panne",
    "contenu-non-inspectable",
}

# ------------------------------------------------------------------
# Detection de SENSIBILITE (v1 : regles lisibles et auditables)
# Chaque motif a un code court : c'est le code qui va au journal,
# JAMAIS la valeur detectee.
# ------------------------------------------------------------------
MOTIFS_REGEX = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    "telephone_fr": re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}\b"),
    # IGNORECASE : un IBAN tape en minuscules reste un IBAN (trou trouve en revue)
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){4,7}(?:[ ]?[A-Z0-9]{1,3})?\b", re.IGNORECASE),
    "numero_securite_sociale": re.compile(r"\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2]|62|63)\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}(?:\s?\d{2})?\b"),
    "siret": re.compile(r"\b\d{3}[ ]?\d{3}[ ]?\d{3}[ ]?\d{5}\b"),
    # Volontairement large (toute suite 4x4 chiffres) : un faux positif coute
    # quelques secondes de local, un faux negatif coute une fuite.
    "carte_bancaire": re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
}

# Vocabulaire du secret professionnel (avocat, sante, comptable).
# En cas de doute, on prefere un faux positif (reste en local, ca coute
# quelques secondes) a un faux negatif (fuite vers le cloud, irreversible).
MOTS_CLES_SENSIBLES = [
    "patient", "diagnostic", "medical", "médical", "ordonnance", "mutuelle",
    "dossier client", "n° de dossier", "numero de dossier", "confidentiel",
    "secret professionnel", "salaire", "fiche de paie", "rib", "iban", "bic",
    "coordonnees bancaires", "coordonnées bancaires", "succession",
    "divorce", "plainte", "garde a vue", "garde à vue", "piece d'identite",
    "pièce d'identité", "passeport", "carte vitale", "adresse personnelle",
]

MOTS_CLES_LOURDS = [
    "redige un rapport", "rédige un rapport", "analyse approfondie",
    "synthese complete", "synthèse complète", "strategie", "stratégie",
    "business plan", "plan detaille", "plan détaillé", "compare en detail",
    "etude de marche", "étude de marché", "argumentaire complet",
]

# Mots courts ou ambigus : detectes en mot entier pour eviter les faux
# positifs dans un mot plus long (ex. "rib" dans "courrier ou ruban").
_MOTS_ENTIERS = {"rib", "iban", "bic", "patient", "salaire", "passeport", "succession", "divorce", "plainte", "confidentiel"}


def _present(mot, texte_minuscule):
    if mot in _MOTS_ENTIERS:
        return re.search(r"\b" + re.escape(mot) + r"\b", texte_minuscule) is not None
    return mot in texte_minuscule


# ------------------------------------------------------------------
# Extraction du texte d'une demande (tous formats connus de LiteLLM)
# Pur Python : testable sans LiteLLM.
# ------------------------------------------------------------------
def extraire_texte(data):
    """Concatene TOUT le texte d'une demande : messages, prompt (legacy), input.

    Retourne (texte, contenu_non_inspectable) : le second vaut True si la
    demande contient au moins un bloc que l'on ne sait pas lire (image,
    audio, fichier...). Ce qu'on ne peut pas inspecter, on ne le laisse
    pas sortir : le hook traite ce drapeau comme un motif sensible.
    """
    morceaux = []
    non_inspectable = False

    def _bloc(bloc):
        nonlocal non_inspectable
        if isinstance(bloc, str):
            morceaux.append(bloc)
        elif isinstance(bloc, dict):
            type_bloc = bloc.get("type", "")
            if type_bloc == "text" and isinstance(bloc.get("text"), str):
                morceaux.append(bloc["text"])
            else:  # image_url, image, input_audio, file, document...
                non_inspectable = True
        else:
            non_inspectable = True

    for message in data.get("messages") or []:
        if not isinstance(message, dict):
            non_inspectable = True
            continue
        contenu = message.get("content")
        if contenu is None:
            continue
        if isinstance(contenu, str):
            morceaux.append(contenu)
        elif isinstance(contenu, list):
            for bloc in contenu:
                _bloc(bloc)
        else:
            non_inspectable = True

    prompt = data.get("prompt")  # endpoint legacy /completions
    if isinstance(prompt, str):
        morceaux.append(prompt)
    elif isinstance(prompt, list):
        for element in prompt:
            _bloc(element)

    entree = data.get("input")  # endpoint /responses
    if isinstance(entree, str):
        morceaux.append(entree)
    elif isinstance(entree, list):
        for element in entree:
            if isinstance(element, dict) and isinstance(element.get("content"), list):
                for bloc in element["content"]:
                    _bloc(bloc)
            else:
                _bloc(element)

    return "\n".join(morceaux), non_inspectable


def detecter_sensibilite(texte):
    """Retourne la liste des CODES de motifs sensibles trouves (jamais les valeurs)."""
    codes = [code for code, regex in MOTIFS_REGEX.items() if regex.search(texte)]
    texte_minuscule = texte.lower()
    codes += ["mot-cle:" + mot for mot in MOTS_CLES_SENSIBLES if _present(mot, texte_minuscule)]
    return codes


_statut_loupe_journalise = False


def detecter_sensibilite_complete(texte):
    """Serrure v1 (regles) + loupe (detection fine PII) si elle est disponible.

    La loupe COMPLETE les regles, elle ne les remplace pas (union des codes).
    Doctrine des pannes, sans ambiguite :
      - loupe ABSENTE (pas installee, ou CHEF_DETECTION_FINE=off) : choix
        d'exploitation assume -> regles seules, statut journalise une fois ;
      - loupe EN PANNE (chargee mais qui crashe, ou module casse) : anomalie
        -> code technique "loupe-en-panne" -> la demande reste en local.
    """
    global _statut_loupe_journalise
    codes = detecter_sensibilite(texte)
    try:
        from detection_fine import detecter_sensibilite_fine, statut
        if not _statut_loupe_journalise:
            _statut_loupe_journalise = True
            journaliser("loupe-statut", None, None, [statut()], 0)
        codes += detecter_sensibilite_fine(texte)
    except ImportError:
        pass  # module fin absent du dossier : la serrure v1 suffit
    except Exception:  # module present mais casse : anomalie -> prudence
        codes += ["loupe-en-panne"]
    return codes


def detecter_complexite(texte):
    """Tache lourde ? (longueur ou vocabulaire de mission)."""
    if len(texte) > SEUIL_COMPLEXITE_CARACTERES:
        return ["longueur:" + str(len(texte))]
    texte_minuscule = texte.lower()
    return ["mot-cle:" + mot for mot in MOTS_CLES_LOURDS if _present(mot, texte_minuscule)]


def journaliser(decision, modele_demande, modele_final, motifs, taille):
    """Trace la decision SANS le contenu. Echec de journalisation = non bloquant."""
    try:
        ligne = {
            "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "decision": decision,
            "modele_demande": modele_demande,
            "modele_final": modele_final,
            "motifs": motifs,
            "taille_caracteres": taille,
        }
        with open(JOURNAL, "a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError:
        pass
