# -*- coding: utf-8 -*-
"""
Le relais : la conversation du Pupitre vers le Chef d'Orchestre (LiteLLM).

Le Pupitre ne parle JAMAIS directement a un cloud. Il ne connait qu'une seule
adresse : celle du routeur local (le Chef d'Orchestre), qui expose une API au
format OpenAI standard. C'est le routeur qui decide ensuite (local, cloud,
methode de l'armoire) et qui caviarde/re-personnalise. Le Pupitre reste "bete"
par conception : c'est exactement ce qui rend l'ensemble sur.

Volontairement en pur stdlib (urllib) : aucune dependance reseau a auditer, et
la construction de la requete est testable sans serveur.
"""

import json
import urllib.error
import urllib.request


def construire_requete(messages, modele, stream=False):
    """Construit le corps JSON au format OpenAI a partir de l'historique du coffre.

    `messages` = liste de dicts {role, contenu} (tels que ranges par le coffre).
    On ne transmet que role + content : aucune metadonnee locale ne fuit.
    stream=False par defaut : la route 'methode de l'armoire' du routeur exige
    une reponse complete pour re-personnaliser les jetons. La v1 du Pupitre est
    non-streamee (simple et robuste) ; le streaming viendra plus tard.
    """
    return {
        "model": modele,
        "messages": [
            {"role": m["role"], "content": m["contenu"]}
            for m in messages
            if m.get("role") in ("user", "assistant", "system")
        ],
        "stream": bool(stream),
    }


def extraire_reponse(reponse_json):
    """Tire le texte de l'assistant d'une reponse OpenAI standard.

    Tolerant : si la forme est inattendue, retourne une chaine vide plutot que
    de crasher (le serveur saura afficher 'reponse vide' sans tomber)."""
    try:
        return reponse_json["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


class RelaisErreur(RuntimeError):
    """Le routeur a refuse ou est injoignable. Porte un message lisible."""

    def __init__(self, message, code=None, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def envoyer(requete, base_url, cle, timeout=120):
    """Envoie la requete au routeur et retourne le texte de l'assistant.

    base_url : l'adresse du Chef d'Orchestre (ex. http://localhost:4000).
    cle      : la master key du routeur (jamais une cle de fournisseur cloud).
    Un refus du routeur (403 fail-closed, 'document hors cases connues'...) est
    remonte tel quel dans RelaisErreur.detail : le Pupitre AFFICHE la raison du
    refus, il ne la masque pas.
    """
    url = base_url.rstrip("/") + "/v1/chat/completions"
    corps = json.dumps(requete).encode("utf-8")
    demande = urllib.request.Request(url, data=corps, method="POST")
    demande.add_header("Content-Type", "application/json")
    if cle:
        demande.add_header("Authorization", "Bearer " + cle)
    try:
        with urllib.request.urlopen(demande, timeout=timeout) as rep:
            charge = json.loads(rep.read().decode("utf-8"))
        return extraire_reponse(charge)
    except urllib.error.HTTPError as exc:
        detail = _lire_detail(exc)
        raise RelaisErreur(
            "Le Chef d'Orchestre a refuse la demande (code %s)." % exc.code,
            code=exc.code, detail=detail,
        ) from exc
    except urllib.error.URLError as exc:
        raise RelaisErreur(
            "Chef d'Orchestre injoignable a %s. Est-il demarre ?" % base_url,
            detail=str(exc.reason),
        ) from exc


def _lire_detail(http_error):
    try:
        charge = json.loads(http_error.read().decode("utf-8"))
        # LiteLLM emballe nos refus dans {"error": {"message": {...}}} ou {"detail": {...}}
        return charge.get("detail") or charge.get("error") or charge
    except Exception:
        return None
