# -*- coding: utf-8 -*-
"""
L'arbitre de desaccord : transformer le DESACCORD entre detecteurs en PRUDENCE.

Pourquoi ce module existe (le differenciateur)
----------------------------------------------
Le ratissage du 15/06/2026 (~50 projets open source) l'a confirme : PERSONNE
ne fait, clef en main, "score + sur-masquage + routage du doute + arbitrage
multi-modeles". Les outils existants se contentent d'une UNION (un detecteur
voit -> on masque), ce que fait deja la serrure (detection.py + detection_fine).
L'union maximise le rappel, mais elle JETTE une information precieuse : QUI a
vu QUOI. Quand deux detecteurs qui SAVENT voir un IBAN ne sont pas d'accord sur
sa presence, c'est un signal de DOUTE. Ce doute doit declencher de la prudence
(escalade vers un modele plus puissant, ou sur-masquage), jamais l'inverse.

Le piege que ce module evite (vote majoritaire)
-----------------------------------------------
Notre etude detecteurs (section 36, Kim et al.) a deja tranche : le vote
majoritaire BAISSE le rappel (si 1 detecteur sur 3 voit une donnee sensible,
la majorite la laisse passer = fuite). Ici, le desaccord ne RETIRE jamais une
detection : l'union reste integralement masquee (rappel maximal, inchange).
Le desaccord ne fait qu'AJOUTER un cran de prudence par-dessus.

La finesse cle : desaccord REEL vs incapacite structurelle
----------------------------------------------------------
La serrure regex ne SAIT PAS voir un nom de personne (elle n'a aucun motif
pour ca). Si GLiNER voit "Jean Dupont" et que la regex ne le voit pas, ce
n'est PAS un desaccord : la regex ne couvre simplement pas ce type. Compter ce
cas comme un doute reviendrait a escalader sur presque chaque document (il y a
un nom partout) et ruinerait l'objectif "limiter la puissance machine".
L'arbitre ne parle donc de DESACCORD que pour un type d'entite COUVERT par au
moins deux detecteurs, dont certains le voient et d'autres non.

Ce module est en Python PUR (stdlib uniquement) : testable sans rien installer,
avec `python test_arbitre_desaccord.py`. Il ne manipule jamais les valeurs
detectees, seulement des CODES (comme le reste de la serrure).
"""

import os
from dataclasses import dataclass, field

import detection  # CODES_TECHNIQUES, est_technique (Python pur, deja la)


# ------------------------------------------------------------------
# 1. TAXONOMIE : ramener les codes des differents detecteurs a un
#    vocabulaire commun. La serrure regex dit "iban", la loupe GLiNER
#    dit "pii:iban" : pour comparer, il faut un nom canonique unique.
# ------------------------------------------------------------------
TAXONOMIE = {
    # --- regex (detection.py) ---
    "email": "EMAIL",
    "telephone_fr": "TELEPHONE",
    "telephone_international": "TELEPHONE",
    "iban": "IBAN",
    "numero_securite_sociale": "NIR",
    "siret": "ENTREPRISE",
    "tva_fr": "ENTREPRISE",
    "tva_ue": "ENTREPRISE",
    "carte_bancaire": "CARTE_BANCAIRE",
    "ssn_us": "NIR",
    "avs_suisse": "NIR",
    "codice_fiscale_it": "NIR",
    "cni_fr": "PIECE_IDENTITE",
    "passeport_fr": "PIECE_IDENTITE",
    "nino_uk": "NIR",
    "date_naissance": "DATE_NAISSANCE",
    "compte_bancaire": "COMPTE",
    # --- loupe (detection_fine.py : labels GLiNER/Presidio prefixes "pii:") ---
    "pii:email": "EMAIL",
    "pii:phone_number": "TELEPHONE",
    "pii:iban": "IBAN",
    "pii:credit_card_number": "CARTE_BANCAIRE",
    "pii:social_security_number": "NIR",
    "pii:person": "PERSONNE",
    "pii:organization": "ENTREPRISE",
    "pii:address": "ADRESSE",
    "pii:date_of_birth": "DATE_NAISSANCE",
    "pii:passport_number": "PIECE_IDENTITE",
    "pii:driver_licence": "PIECE_IDENTITE",
    "pii:medical_condition": "SANTE",
    "pii:bank_account_number": "IBAN",
}

# Couverture par defaut : quels types canoniques CHAQUE detecteur est CAPABLE
# de voir. Sert a distinguer un vrai desaccord d'une incapacite structurelle.
# Modifiable par l'appelant (l'ajout d'un moteur CamemBERT/Anonym-IA enrichit
# la couverture FR : NIR, IBAN, references de dossier...).
COUVERTURE_DEFAUT = {
    "regex": {"EMAIL", "TELEPHONE", "IBAN", "NIR", "ENTREPRISE",
              "CARTE_BANCAIRE", "PIECE_IDENTITE", "DATE_NAISSANCE", "COMPTE"},
    "gliner": {"PERSONNE", "ENTREPRISE", "ADRESSE", "EMAIL", "TELEPHONE",
               "IBAN", "CARTE_BANCAIRE", "NIR", "DATE_NAISSANCE",
               "PIECE_IDENTITE", "SANTE"},
    "presidio": {"PERSONNE", "EMAIL", "TELEPHONE", "IBAN", "CARTE_BANCAIRE"},
}


def _categorie(code):
    """Code brut -> type canonique, ou None si le code n'est pas une entite
    (mot-cle de contexte, code technique, code inconnu)."""
    if code in TAXONOMIE:
        return TAXONOMIE[code]
    # Un mot-cle parlant ("mot-cle:iban") porte le type dans son suffixe.
    if code.startswith("mot-cle:"):
        suffixe = code.split(":", 1)[1]
        return TAXONOMIE.get(suffixe)  # souvent None : c'est un simple indice
    return None


def normaliser(codes):
    """Liste de codes d'un detecteur -> (categories sensibles, codes techniques).

    Les codes techniques (panne, contenu non inspectable, hors couverture) ne
    sont PAS des types d'entite : ils signalent une prudence et sont remontes a
    part. Voir detection.est_technique.
    """
    categories, techniques = set(), set()
    for code in codes or []:
        if detection.est_technique(code):
            techniques.add(code)
            continue
        cat = _categorie(code)
        if cat:
            categories.add(cat)
    return categories, techniques


# ------------------------------------------------------------------
# 2. La decision rendue par l'arbitre.
#    Deux axes INDEPENDANTS, a ne jamais confondre :
#      - sensible       : y a-t-il de la donnee personnelle ? -> CONFIDENTIALITE
#                         (decision de routage local/cloud, inchangee : union OR).
#      - niveau_doute   : les juges sont-ils d'accord ? -> ECONOMIE MACHINE
#                         (faut-il reveiller un modele plus puissant ?).
# ------------------------------------------------------------------
NIVEAUX = ("aucun", "faible", "moyen", "eleve")


@dataclass
class Decision:
    sensible: bool                      # de la PII a ete vue (ou prudence technique)
    niveau_doute: str                   # aucun | faible | moyen | eleve
    action: str                         # "ok" | "escalade" | "sur-masquage"
    union: list = field(default_factory=list)          # tout ce qui doit etre masque
    consensus: list = field(default_factory=list)      # types vus par TOUS ceux qui couvrent
    desaccord: list = field(default_factory=list)      # types couverts par >=2, vus par certains seulement
    non_corrobore: list = field(default_factory=list)  # types vus par un seul detecteur capable
    techniques: list = field(default_factory=list)     # codes de prudence (panne...)
    detail: dict = field(default_factory=dict)         # {detecteur: [types vus]} pour l'audit/banc d'essai

    def pour_journal(self):
        """Vue serialisable SANS aucune valeur (codes/types seulement)."""
        return {
            "sensible": self.sensible,
            "niveau_doute": self.niveau_doute,
            "action": self.action,
            "union": sorted(self.union),
            "desaccord": sorted(self.desaccord),
            "non_corrobore": sorted(self.non_corrobore),
            "techniques": sorted(self.techniques),
        }


def _action_doute_defaut():
    """Que faire face a un desaccord reel ? Escalade (defaut) ou sur-masquage."""
    valeur = os.environ.get("CHEF_ARBITRE_ACTION_DOUTE", "escalade").strip().lower()
    return valeur if valeur in ("escalade", "sur-masquage") else "escalade"


def arbitrer(resultats_par_detecteur, couverture=None, action_doute=None,
             escalader_non_corrobore=None):
    """Coeur de l'arbitre. Fonction PURE (aucun modele charge) : on lui donne
    ce que CHAQUE detecteur a vu, elle rend une Decision.

    resultats_par_detecteur : {nom: [codes]} (un detecteur present avec une
        liste vide = "j'ai regarde, je n'ai rien vu" : c'est une opinion).
    couverture : {nom: set(categories)} ; defaut = COUVERTURE_DEFAUT, complete
        pour tout detecteur inconnu par l'ensemble des types qu'il a vus (on
        suppose alors qu'il couvre au moins ce qu'il rapporte).
    action_doute : "escalade" | "sur-masquage" pour un desaccord REEL.
    escalader_non_corrobore : si vrai, un type vu par un seul juge capable
        escalade aussi (defaut : env CHEF_ARBITRE_ESCALADE_SOLO=1, sinon non).
    """
    couverture = dict(COUVERTURE_DEFAUT if couverture is None else couverture)
    action_doute = action_doute or _action_doute_defaut()
    if escalader_non_corrobore is None:
        escalader_non_corrobore = os.environ.get("CHEF_ARBITRE_ESCALADE_SOLO", "0").strip() == "1"

    vues, techniques_tous = {}, set()
    for nom, codes in (resultats_par_detecteur or {}).items():
        cats, tech = normaliser(codes)
        vues[nom] = cats
        techniques_tous |= tech
        # Un detecteur qui voit un type est, par definition, capable de le voir.
        couverture.setdefault(nom, set())
        couverture[nom] = set(couverture[nom]) | cats

    union = set().union(*vues.values()) if vues else set()

    consensus, desaccord, non_corrobore = set(), set(), set()
    for cat in union:
        capables = [n for n in vues if cat in couverture.get(n, set())]
        voyant = [n for n in vues if cat in vues[n]]
        if len(capables) <= 1:
            # Un seul juge possible : aucune corroboration possible -> a surveiller.
            non_corrobore.add(cat)
        elif set(voyant) == set(capables):
            consensus.add(cat)        # tous ceux qui savent voir sont d'accord
        else:
            desaccord.add(cat)        # certains capables ne l'ont PAS vue -> doute reel

    # --- Synthese des deux axes ---
    sensible = bool(union) or bool(techniques_tous)

    if desaccord:
        niveau, action = "eleve", action_doute
    elif non_corrobore and escalader_non_corrobore:
        niveau, action = "moyen", "escalade"
    elif non_corrobore:
        niveau, action = "moyen", "ok"        # masque (union), mais on note le solo
    elif union:
        niveau, action = "faible", "ok"       # juges d'accord : sensible mais sans doute
    else:
        niveau, action = "aucun", "ok"

    # Un signal technique (panne, contenu non inspectable) impose au minimum la
    # prudence : on ne descend jamais sous "faible" tant qu'il est present.
    if techniques_tous and niveau == "aucun":
        niveau = "faible"

    return Decision(
        sensible=sensible,
        niveau_doute=niveau,
        action=action,
        union=sorted(union),
        consensus=sorted(consensus),
        desaccord=sorted(desaccord),
        non_corrobore=sorted(non_corrobore),
        techniques=sorted(techniques_tous),
        detail={n: sorted(c) for n, c in vues.items()},
    )


# ------------------------------------------------------------------
# 3. Adaptateur reel : rassembler ce que voit CHAQUE detecteur, separement.
#    La serrure regex est toujours la (Python pur). La loupe expose son
#    detail par moteur via detection_fine.detecter_par_moteur (ajout non
#    destructif). Si la loupe est absente, l'arbitre tourne avec la regex
#    seule : il ne peut alors pas constater de desaccord, ce qui est correct.
# ------------------------------------------------------------------
def collecter_resultats(texte):
    """{detecteur: [codes]} en interrogeant chaque detecteur disponible a part."""
    resultats = {"regex": detection.detecter_sensibilite(texte)}
    try:
        import detection_fine
        resultats.update(detection_fine.detecter_par_moteur(texte))
    except ImportError:
        pass          # loupe absente : regex seule, pas de desaccord possible
    except Exception:
        resultats["loupe"] = ["loupe-en-panne"]
    return resultats


def arbitrer_texte(texte, **kwargs):
    """Convenance : collecte les detecteurs reels puis arbitre."""
    return arbitrer(collecter_resultats(texte), **kwargs)


def route_escaladee(decision, route_locale, route_forte):
    """Route locale FINALE apres avis de l'arbitre.

    Retourne la route FORTE uniquement si l'arbitre signale une escalade
    (action == 'escalade', c-a-d un desaccord reel) ET qu'un palier fort
    DISTINCT est configure. Sinon la route locale standard. Le resultat est
    TOUJOURS local : l'escalade reveille un modele plus puissant, elle ne sort
    jamais au cloud (le fail-closed n'est jamais affaibli).
    """
    if (decision is not None and getattr(decision, "action", None) == "escalade"
            and route_forte and route_forte != route_locale):
        return route_forte
    return route_locale
