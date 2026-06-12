# -*- coding: utf-8 -*-
"""
Le Chef d'Orchestre - la serrure (hook LiteLLM).

Trois piliers, evalues dans CET ordre (la sensibilite gagne toujours) :
  1. SENSIBILITE : la demande contient-elle une donnee qui ne doit pas sortir ?
       OUI -> route locale obligatoire. Si la cible demandee etait le cloud -> REFUS net
       (fail-closed) : on ne "corrige" pas en douce une demande explicitement cloud,
       on la refuse en expliquant pourquoi. Zero fuite, zero ambiguite.
  2. COMPLEXITE : tache lourde et anodine -> cloud (la puissance quand elle est utile).
  3. ECONOMIE   : tout le reste -> local (quasi gratuit sur notre materiel).

La logique de detection vit dans detection.py (pur Python, testable partout) ;
ce fichier-ci n'est que la plomberie LiteLLM (machine cible uniquement).
Journal : journal-routage.jsonl, metadonnees SEULEMENT (RGPD art. 32).
"""

import os

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

from detection import detecter_complexite, detecter_sensibilite, journaliser

ROUTE_LOCALE = os.environ.get("CHEF_ROUTE_LOCALE", "local-sensible")
ROUTE_CLOUD = os.environ.get("CHEF_ROUTE_CLOUD", "cloud-lourd")
ROUTE_AUTO = os.environ.get("CHEF_ROUTE_AUTO", "chef-auto")


def _texte_des_messages(data):
    """Concatene le texte de tous les messages de la demande."""
    morceaux = []
    for message in data.get("messages") or []:
        contenu = message.get("content")
        if isinstance(contenu, str):
            morceaux.append(contenu)
        elif isinstance(contenu, list):  # format multimodal
            for bloc in contenu:
                if isinstance(bloc, dict) and bloc.get("type") == "text":
                    morceaux.append(bloc.get("text", ""))
    return "\n".join(morceaux)


class ChefOrchestre(CustomLogger):
    """Le hook appele par LiteLLM AVANT chaque appel de modele."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        if call_type not in ("completion", "acompletion", "text_completion"):
            return data

        modele_demande = data.get("model", "")
        texte = _texte_des_messages(data)
        motifs_sensibles = detecter_sensibilite(texte)

        # ---- Pilier 1 : SENSIBILITE (gagne toujours) ----
        if motifs_sensibles:
            if modele_demande == ROUTE_CLOUD:
                # FAIL-CLOSED : cible cloud explicite + donnee sensible = refus net.
                journaliser("refus-fail-closed", modele_demande, None, motifs_sensibles, len(texte))
                raise HTTPException(
                    status_code=403,
                    detail={
                        "erreur": "Demande refusee : donnee sensible detectee, le cloud est interdit pour cette classe de donnees (fail-closed).",
                        "motifs": motifs_sensibles,
                        "solution": "Renvoyer cette demande vers la route locale '%s'." % ROUTE_LOCALE,
                    },
                )
            # Route auto (ou locale) : on force le local, en le journalisant.
            data["model"] = ROUTE_LOCALE
            journaliser("force-local-sensible", modele_demande, ROUTE_LOCALE, motifs_sensibles, len(texte))
            return data

        # ---- Pilier 2 et 3 : COMPLEXITE puis ECONOMIE (route auto seulement) ----
        if modele_demande == ROUTE_AUTO:
            motifs_lourds = detecter_complexite(texte)
            if motifs_lourds:
                data["model"] = ROUTE_CLOUD
                journaliser("auto-vers-cloud", modele_demande, ROUTE_CLOUD, motifs_lourds, len(texte))
            else:
                data["model"] = ROUTE_LOCALE
                journaliser("auto-vers-local", modele_demande, ROUTE_LOCALE, ["tache-simple"], len(texte))
            return data

        # Route explicite sans donnee sensible : on respecte le choix de l'appelant.
        journaliser("route-explicite", modele_demande, modele_demande, [], len(texte))
        return data


proxy_handler_instance = ChefOrchestre()
