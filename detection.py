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

SEUIL_COMPLEXITE_CARACTERES = int(os.environ.get("CHEF_SEUIL_LOURD", "4000"))
JOURNAL = os.environ.get("CHEF_JOURNAL", os.path.join(os.path.dirname(__file__), "journal-routage.jsonl"))

# ------------------------------------------------------------------
# Detection de SENSIBILITE (v1 : regles lisibles et auditables)
# Chaque motif a un code court : c'est le code qui va au journal,
# JAMAIS la valeur detectee.
# ------------------------------------------------------------------
MOTIFS_REGEX = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    "telephone_fr": re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){4,7}(?:[ ]?[A-Z0-9]{1,3})?\b"),
    "numero_securite_sociale": re.compile(r"\b[12]\s?\d{2}\s?(?:0[1-9]|1[0-2]|62|63)\s?(?:\d{2}|2A|2B)\s?\d{3}\s?\d{3}(?:\s?\d{2})?\b"),
    "siret": re.compile(r"\b\d{3}[ ]?\d{3}[ ]?\d{3}[ ]?\d{5}\b"),
    "carte_bancaire": re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b"),
}

# Vocabulaire du secret professionnel (avocat, sante, comptable).
# En cas de doute, on prefere un faux positif (reste en local, ca coute
# quelques secondes) a un faux negatif (fuite vers le cloud, irreversible).
MOTS_CLES_SENSIBLES = [
    "patient", "diagnostic", "medical", "médical", "ordonnance", "mutuelle",
    "dossier client", "n° de dossier", "numero de dossier", "confidentiel",
    "secret professionnel", "salaire", "fiche de paie", "rib", "succession",
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
_MOTS_ENTIERS = {"rib", "patient", "salaire", "passeport", "succession", "divorce", "plainte", "confidentiel"}


def _present(mot, texte_minuscule):
    if mot in _MOTS_ENTIERS:
        return re.search(r"\b" + re.escape(mot) + r"\b", texte_minuscule) is not None
    return mot in texte_minuscule


def detecter_sensibilite(texte):
    """Retourne la liste des CODES de motifs sensibles trouves (jamais les valeurs)."""
    codes = [code for code, regex in MOTIFS_REGEX.items() if regex.search(texte)]
    texte_minuscule = texte.lower()
    codes += ["mot-cle:" + mot for mot in MOTS_CLES_SENSIBLES if _present(mot, texte_minuscule)]
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
