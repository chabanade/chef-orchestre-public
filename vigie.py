# -*- coding: utf-8 -*-
"""
La vigie : diagnostiquer ce qui NE RENTRE PAS dans les cases connues.

Demande du 12/06/2026 au soir : quand un document sort de la couverture du
routeur (ecriture etrangere, langue inconnue, identifiant d'un format jamais
vu), le systeme doit LE SAVOIR, le dire, et demander sa mise a jour : au
lieu de se croire couvert en silence. C'est le maillon "amelioration
continue" : la vigie remplit un carnet local (alertes-couverture.jsonl,
metadonnees SEULEMENT), l'utilisateur renseigne l'origine du document,
active le pack pays correspondant (voir packs-pays/) sous son GO, et
continue son dossier.

Doctrine, sans exception : la vigie ALERTE et force la prudence (local),
elle ne modifie JAMAIS les regles toute seule. Un outil de securite qui
reecrit ses propres regles sans validation humaine est un trou de securite.

Trois detecteurs, pur Python (zero dependance) :
  1. ECRITURES NON COUVERTES : cyrillique, arabe, chinois... Les regex et
     la loupe (GLiNER : en/fr/de/es/it/pt) sont structurellement aveugles
     sur ces ecritures -> fiable a 100 %, base sur les plages Unicode.
  2. LANGUE NON IDENTIFIEE : texte latin long sans AUCUN mot-outil des
     6 langues couvertes (polonais, turc, neerlandais...). Heuristique
     assumee comme imparfaite : certains mots-outils se ressemblent d'une
     langue a l'autre, un texte peut passer entre les mailles.
  3. IDENTIFIANTS INCONNUS (route pseudo seulement) : une sequence
     chiffres+separateurs qui ressemble a un identifiant national mais ne
     correspond a AUCUNE classe connue. Appele sur le texte DEJA
     pseudonymise : tout ce qui est couvert est devenu jeton, ce qui
     reste de suspect est donc inconnu.
"""

import json
import os
import re
import time


def _env_int(nom, defaut):
    try:
        return int(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


# ------------------------------------------------------------------
# 1. Ecritures non couvertes (plages Unicode, detection certaine)
# ------------------------------------------------------------------
PLAGES_ECRITURES = (
    ("grec", 0x0370, 0x03FF),
    ("cyrillique", 0x0400, 0x04FF),
    ("hebreu", 0x0590, 0x05FF),
    ("arabe", 0x0600, 0x06FF),
    ("devanagari", 0x0900, 0x097F),
    ("thai", 0x0E00, 0x0E7F),
    ("kana", 0x3040, 0x30FF),
    ("cjk", 0x4E00, 0x9FFF),
    ("hangul", 0xAC00, 0xD7AF),
)

# En dessous de ce nombre de caracteres CUMULES d'une meme ecriture, on ne
# signale pas (un nom propre isole, un emoji range a cote). 12 caracteres,
# c'est environ deux mots : du texte reel, plus un accident.
SEUIL_ECRITURE = _env_int("CHEF_SEUIL_ECRITURE", 12)


def detecter_ecritures(texte):
    compteurs = {}
    for caractere in texte:
        point = ord(caractere)
        if point < 0x0370:  # latin, chiffres, ponctuation : sortie rapide
            continue
        for nom, debut, fin in PLAGES_ECRITURES:
            if debut <= point <= fin:
                compteurs[nom] = compteurs.get(nom, 0) + 1
                break
    return ["ecriture-non-couverte:" + nom
            for nom, total in sorted(compteurs.items()) if total >= SEUIL_ECRITURE]


# ------------------------------------------------------------------
# 2. Langue latine non identifiee (heuristique mots-outils)
# ------------------------------------------------------------------
# Mots-outils tres frequents des 6 langues que la loupe sait lire.
_STOPWORDS_COUVERTS = frozenset(
    # francais
    "le la les des une est dans pour avec sur pas vous nous cette sont".split()
    # anglais
    + "the and was are with this that have from not which been".split()
    # allemand
    + "der die das und ist nicht mit eine auf sich werden".split()
    # espagnol
    + "el los las una pero como para por con esta muy".split()
    # italien
    + "che di non per sono della questo anche piu gli".split()
    # portugais
    + "nao uma com mais como dos foi pelo isso ele".split()
)
_MOTS = re.compile(r"[a-zà-ÿ']+")
MOTS_MINIMUM = 30      # en dessous, trop court pour juger une langue
RATIO_MINIMUM = 0.02   # moins de 2 % de mots-outils connus = langue inconnue


def langue_couverte(texte):
    """[] si la langue semble couverte ; ["langue-non-identifiee"] sinon."""
    if not texte:
        return []
    lettres = sum(1 for c in texte if c.isalpha())
    if lettres < len(texte) * 0.5:
        return []  # donnees structurees (code, JSON, tableaux) : on ne juge pas
    mots = _MOTS.findall(texte.lower())
    if len(mots) < MOTS_MINIMUM:
        return []
    connus = sum(1 for m in mots if m in _STOPWORDS_COUVERTS)
    if connus / float(len(mots)) < RATIO_MINIMUM:
        return ["langue-non-identifiee"]
    return []


def detecter_couverture(texte):
    """Les signaux "hors cases connues" d'un texte (ecritures + langue)."""
    return detecter_ecritures(texte) + langue_couverte(texte)


# ------------------------------------------------------------------
# 3. Identifiants inconnus (a appeler sur le texte PSEUDONYMISE)
# ------------------------------------------------------------------
_CANDIDAT = re.compile(r"\b\d{1,4}(?:[.\-/]\d{1,4}){2,6}\b")
_DATE = re.compile(r"^(?:\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4}|\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2})$")
_MONTANT = re.compile(r"^\d{1,3}(?:[.]\d{3})+$")  # 1.234.567 = separateur de milliers


def identifiants_inconnus(texte):
    """Une sequence qui ressemble a un identifiant national (>= 8 chiffres,
    segmentee par . - ou /) et qui a SURVECU a la pseudonymisation = un
    format que le greffier ne connait pas. On ne devine jamais : on signale,
    et la route pseudo refuse tant que le pack n'est pas active."""
    for m in _CANDIDAT.finditer(texte or ""):
        sequence = m.group(0)
        if _DATE.match(sequence) or _MONTANT.match(sequence):
            continue
        if sum(1 for c in sequence if c.isdigit()) < 8:
            continue
        return ["identifiant-inconnu"]
    return []


# ------------------------------------------------------------------
# Le carnet de doleances : la memoire des manques (metadonnees seulement)
# ------------------------------------------------------------------
ALERTES = os.environ.get(
    "CHEF_ALERTES",
    os.path.join(os.path.dirname(__file__), "alertes-couverture.jsonl"))


def signaler(codes, taille):
    """Trace un manque de couverture, SANS le contenu. C'est ce carnet qui
    guide les mises a jour (quels packs creer en priorite). Non bloquant."""
    try:
        ligne = {
            "horodatage": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "codes": codes,
            "taille_caracteres": taille,
            "action": "renseigner l'origine du document puis activer ou "
                      "demander le pack pays correspondant (packs-pays/README.md)",
        }
        with open(ALERTES, "a", encoding="utf-8") as fichier:
            fichier.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    except OSError:
        pass
