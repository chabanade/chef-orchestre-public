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

import re

from detection import MOTIFS_REGEX

# Les classes que le greffier sait remplacer : des VALEURS formatees,
# detectables avec leurs positions exactes. (Les mots-cles contextuels,
# eux, ne sont pas des valeurs remplacables.)
CLASSES_PSEUDONYMISABLES = [
    "email", "telephone_fr", "iban", "numero_securite_sociale",
    "siret", "carte_bancaire",
]

_JETON = re.compile(r"<[A-Z_]+_\d+>")


class Greffier:
    """Une instance par demande : tient la table et garantit la coherence
    (la meme valeur recoit toujours le meme jeton dans la demande)."""

    def __init__(self):
        self.table = {}        # jeton -> valeur reelle (l'armoire)
        self._inverse = {}     # valeur reelle -> jeton (coherence)
        self._compteurs = {}

    def _jeton_pour(self, code, valeur):
        if valeur in self._inverse:
            return self._inverse[valeur]
        self._compteurs[code] = self._compteurs.get(code, 0) + 1
        jeton = "<%s_%d>" % (code.upper(), self._compteurs[code])
        self.table[jeton] = valeur
        self._inverse[valeur] = jeton
        return jeton

    def pseudonymiser_texte(self, texte):
        """Remplace toutes les valeurs formatees par des jetons."""
        for code in CLASSES_PSEUDONYMISABLES:
            regex = MOTIFS_REGEX[code]
            texte = regex.sub(lambda m, c=code: self._jeton_pour(c, m.group(0)), texte)
        return texte

    def pseudonymiser_demande(self, data):
        """Pseudonymise EN PLACE tous les champs textuels d'une demande
        (messages, prompt legacy, input). Retourne le nombre de jetons poses."""
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

        return len(self.table)

    def repersonnaliser(self, texte):
        """RETOUR : remet les vraies valeurs a la place des jetons (en local)."""
        if not isinstance(texte, str) or not self.table:
            return texte
        for jeton, valeur in self.table.items():
            texte = texte.replace(jeton, valeur)
        return texte

    def detruire(self):
        """Brule l'armoire : la table n'existe que le temps de l'aller-retour."""
        self.table.clear()
        self._inverse.clear()
        self._compteurs.clear()


def jetons_restants(texte):
    """Diagnostic : des jetons non re-personnalises trainent-ils encore ?"""
    return _JETON.findall(texte or "")
