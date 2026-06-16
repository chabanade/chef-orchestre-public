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
import re
import urllib.error
import urllib.request

# Bloc de raisonnement quand un modele l'inscrit DANS le texte (vieille forme).
# La forme moderne (litellm/ollama) le met dans un champ "reasoning_content".
_THINK = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)


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
    """Tire la REPONSE PROPRE de l'assistant (sans le raisonnement).

    Tolerant : si la forme est inattendue, retourne une chaine vide plutot que
    de crasher (le serveur saura afficher 'reponse vide' sans tomber)."""
    try:
        contenu = reponse_json["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""
    # Filet : si un modele a inscrit son raisonnement EN LIGNE (<think>...),
    # on le retire de la reponse affichee (le raisonnement va dans le repli).
    contenu = _THINK.sub("", contenu)
    coupe = contenu.lower().find("<think>")   # <think> ouvert mais jamais ferme
    if coupe != -1:
        contenu = contenu[:coupe]
    return contenu.strip()


def extraire_raisonnement(reponse_json):
    """Tire le RAISONNEMENT du modele, s'il y en a un, sinon une chaine vide.

    Deux formes possibles :
      - moderne : champ 'reasoning_content' (litellm/ollama, ex. qwen3) ;
      - ancienne : bloc <think>...</think> inscrit dans le contenu.
    Le Pupitre l'affiche dans un repli 'voir le raisonnement' : la reponse
    reste propre, mais le raisonnement reste consultable (choix de conception)."""
    try:
        message = reponse_json["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        return ""
    if not isinstance(message, dict):
        return ""
    direct = message.get("reasoning_content") or message.get("reasoning") or ""
    if direct:
        return direct.strip()
    blocs = _THINK.findall(message.get("content") or "")
    return "\n".join(b.strip() for b in blocs).strip()


class RelaisErreur(RuntimeError):
    """Le routeur a refuse ou est injoignable. Porte un message lisible."""

    def __init__(self, message, code=None, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail


def envoyer(requete, base_url, cle, timeout=120):
    """Envoie la requete au routeur et retourne {contenu, raisonnement}.

    base_url : l'adresse du Chef d'Orchestre (ex. http://localhost:4000).
    cle      : la master key du routeur (jamais une cle de fournisseur cloud).
    Un refus du routeur (403 fail-closed, 'document hors cases connues'...) est
    remonte tel quel dans RelaisErreur.detail : le Pupitre AFFICHE la raison du
    refus, il ne la masque pas.
    Retour : dict {"contenu": <reponse propre>, "raisonnement": <ou ''>}.
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
        return {"contenu": extraire_reponse(charge), "raisonnement": extraire_raisonnement(charge)}
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
