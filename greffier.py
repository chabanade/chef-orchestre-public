# -*- coding: utf-8 -*-
"""
Le greffier : pseudonymisation aller-retour (la "methode de l'armoire").

Inspire d'une pratique hospitaliere reelle (CECOS, don de gametes) : le donneur
recoit un NUMERO ; tout le monde travaille avec le numero et les donnees utiles
(groupe sanguin, caracteristiques) ; l'IDENTITE reste dans une armoire fermee,
accessible a peu de personnes, sur demande motivee. C'est exactement la
pseudonymisation au sens du RGPD (art. 4.5) : les informations permettant la
re-identification sont conservees SEPAREMENT, sous mesures techniques.

Transposition numerique :
  1. ALLER : les valeurs sensibles FORMATEES (IBAN, NIR, email, telephone,
     SIRET, carte bancaire) sont remplacees par des jetons <IBAN_1>, <EMAIL_1>...
  2. L'ARMOIRE : la table jeton -> valeur reste EN MEMOIRE LOCALE le temps de
     l'aller-retour, puis est detruite. Elle ne part jamais nulle part, ne
     touche pas le disque, n'apparait jamais au journal.
  3. RETOUR : les jetons presents dans la reponse du cloud sont remplaces par
     les vraies valeurs, en local. Le cloud n'a jamais vu que des numeros.

Ce que le greffier NE FAIT PAS (v1, honnetete) :
  - Il ne remplace que les motifs FORMATES (regex). Les noms de personnes, les
    adresses, le contexte re-identifiant ne sont PAS couverts : c'est pourquoi
    la route pseudo REFUSE toute demande ou il reste un motif sensible apres
    pseudonymisation (mot-cle metier, entite vue par la loupe). Fail-closed.
  - Juridiquement (arret CJUE C-413/23 P, verifie) : pour NOUS qui detenons la
    table, la donnee pseudonymisee RESTE une donnee personnelle. La route
    pseudo REDUIT le risque (le destinataire ne peut pas re-identifier), elle
    ne remplace pas le local strict pour l'ultra-sensible.
"""

import os
import re
import threading
import time

from detection import MOTIFS_REGEX

# Les classes que le greffier sait remplacer : des VALEURS formatees,
# detectables avec leurs positions exactes. (Les mots-cles contextuels,
# eux, ne sont pas des valeurs remplacables.)
CLASSES_PSEUDONYMISABLES = [
    "email", "telephone_fr", "iban", "numero_securite_sociale",
    "siret", "carte_bancaire",
]

_JETON = re.compile(r"<[A-Z_]+_\d+>")


# ------------------------------------------------------------------
# L'armoire de SESSION (decision Mehdi du 12/06/2026) : pour pouvoir
# ITERER sur une meme conversation, la meme valeur doit garder le meme
# jeton d'un tour a l'autre, et un jeton du tour 1 doit rester
# restaurable au tour 5. Compromis assume et borne :
#   - l'armoire vit en MEMOIRE d'un seul processus (jamais disque/journal),
#   - elle est BRULEE apres CHEF_ARMOIRE_TTL_MINUTES d'inactivite (30 min
#     par defaut) et le nombre de sessions est plafonne,
#   - un redemarrage du routeur la perd : degradation SURE (les jetons
#     deviennent orphelins et restent opaques, aucune fuite),
#   - CHEF_ARMOIRE_SESSION=0 revient au brulage apres chaque aller-retour.
# ------------------------------------------------------------------
def _env_int(nom, defaut):
    try:
        return int(os.environ.get(nom, defaut))
    except (TypeError, ValueError):
        return defaut


SESSION_ACTIVE = os.environ.get("CHEF_ARMOIRE_SESSION", "1").strip() == "1"
TTL_MINUTES = _env_int("CHEF_ARMOIRE_TTL_MINUTES", 30)
MAX_SESSIONS = _env_int("CHEF_ARMOIRE_MAX_SESSIONS", 50)


class _ArmoireSession:
    """L'etat partage d'une conversation : table, inverse, compteurs."""

    def __init__(self):
        self.table = {}
        self.inverse = {}
        self.compteurs = {}
        self.verrou = threading.Lock()
        self.derniere_activite = time.monotonic()

    def bruler(self):
        self.table.clear()
        self.inverse.clear()
        self.compteurs.clear()


_sessions = {}
_verrou_sessions = threading.Lock()


def obtenir_armoire_session(cle):
    """Retourne l'armoire de la session (creee au besoin), apres avoir brule
    les sessions expirees et fait respecter le plafond."""
    maintenant = time.monotonic()
    with _verrou_sessions:
        for k in [k for k, a in _sessions.items()
                  if maintenant - a.derniere_activite > TTL_MINUTES * 60]:
            _sessions.pop(k).bruler()
        armoire = _sessions.get(cle)
        if armoire is None:
            while len(_sessions) >= MAX_SESSIONS:  # plafond : on brule la plus ancienne
                plus_ancienne = min(_sessions, key=lambda k: _sessions[k].derniere_activite)
                _sessions.pop(plus_ancienne).bruler()
            armoire = _ArmoireSession()
            _sessions[cle] = armoire
        armoire.derniere_activite = maintenant
        return armoire


class Greffier:
    """Tient la table et garantit la coherence (la meme valeur recoit
    toujours le meme jeton). Deux modes :
      - autonome (armoire=None) : table propre a la demande, brulee par
        detruire() apres l'aller-retour (securite maximale) ;
      - session (armoire fournie) : table PARTAGEE par la conversation,
        detruire() ne brule rien, le TTL du registre s'en charge."""

    def __init__(self, armoire=None):
        self._armoire = armoire
        self.remplacements = 0  # occurrences remplacees dans LA demande en cours
        if armoire is None:
            self.table = {}        # jeton -> valeur reelle (l'armoire)
            self._inverse = {}     # valeur reelle -> jeton (coherence)
            self._compteurs = {}
            self._verrou = threading.Lock()
        else:
            self.table = armoire.table
            self._inverse = armoire.inverse
            self._compteurs = armoire.compteurs
            self._verrou = armoire.verrou

    def _jeton_pour(self, code, valeur):
        with self._verrou:
            if valeur in self._inverse:
                return self._inverse[valeur]
            self._compteurs[code] = self._compteurs.get(code, 0) + 1
            jeton = "<%s_%d>" % (code.upper(), self._compteurs[code])
            self.table[jeton] = valeur
            self._inverse[valeur] = jeton
            return jeton

    def _remplacer(self, code, match):
        self.remplacements += 1
        return self._jeton_pour(code, match.group(0))

    def pseudonymiser_texte(self, texte):
        """Remplace toutes les valeurs formatees par des jetons."""
        for code in CLASSES_PSEUDONYMISABLES:
            regex = MOTIFS_REGEX[code]
            texte = regex.sub(lambda m, c=code: self._remplacer(c, m), texte)
        return texte

    def pseudonymiser_demande(self, data):
        """Pseudonymise EN PLACE tous les champs textuels d'une demande
        (messages, prompt legacy, input). Retourne le nombre d'occurrences
        remplacees dans CETTE demande (pas la taille de l'armoire)."""
        self.remplacements = 0
        def _bloc(bloc):
            if isinstance(bloc, dict) and bloc.get("type") == "text" and isinstance(bloc.get("text"), str):
                bloc["text"] = self.pseudonymiser_texte(bloc["text"])

        for message in data.get("messages") or []:
            if not isinstance(message, dict):
                continue
            contenu = message.get("content")
            if isinstance(contenu, str):
                message["content"] = self.pseudonymiser_texte(contenu)
            elif isinstance(contenu, list):
                for bloc in contenu:
                    _bloc(bloc)

        if isinstance(data.get("prompt"), str):
            data["prompt"] = self.pseudonymiser_texte(data["prompt"])
        elif isinstance(data.get("prompt"), list):
            data["prompt"] = [
                self.pseudonymiser_texte(p) if isinstance(p, str) else p
                for p in data["prompt"]
            ]

        if isinstance(data.get("input"), str):
            data["input"] = self.pseudonymiser_texte(data["input"])

        return self.remplacements

    def repersonnaliser(self, texte):
        """RETOUR : remet les vraies valeurs a la place des jetons (en local).

        Matching en deux temps (idee reprise du scanner Deanonymize de LLM Guard) :
        1. exact : <IBAN_1> tel quel ;
        2. tolerant : le modele abime parfois un jeton (<iban 1>, < IBAN_1 >,
           <Iban-1>) ; une regex souple par jeton rattrape ces variantes.
        Un jeton irrecuperable est LAISSE TEL QUEL (opaque, donc aucune fuite)
        et signale par jetons_restants : on ne devine jamais une valeur.
        """
        if not isinstance(texte, str) or not self.table:
            return texte
        for jeton, valeur in self.table.items():
            if jeton in texte:
                texte = texte.replace(jeton, valeur)
                continue
            # variante abimee : espaces autour, _ devenu espace ou tiret, casse
            interieur = re.escape(jeton[1:-1]).replace("_", r"[\s_\-]+")
            texte = re.sub(r"<\s*" + interieur + r"\s*>",
                           lambda _m, v=valeur: v,  # lambda : la valeur n'est jamais interpretee
                           texte, flags=re.IGNORECASE)
        return texte

    def detruire(self):
        """Mode autonome : brule l'armoire (elle ne vit que l'aller-retour).
        Mode session : ne brule RIEN, l'armoire appartient a la conversation
        et c'est le TTL du registre qui la brulera."""
        if self._armoire is not None:
            return
        self.table.clear()
        self._inverse.clear()
        self._compteurs.clear()


def jetons_restants(texte):
    """Diagnostic : des jetons non re-personnalises trainent-ils encore ?"""
    return _JETON.findall(texte or "")
