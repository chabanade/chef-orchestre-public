# -*- coding: utf-8 -*-
"""
Le Chef d'Orchestre - la serrure (hook LiteLLM).

Trois piliers, evalues dans CET ordre (la sensibilite gagne toujours) :
  1. SENSIBILITE : la demande contient-elle une donnee qui ne doit pas sortir ?
       OUI -> route locale obligatoire. Si la cible demandee n'etait pas une
       route locale -> REFUS net (fail-closed) : on ne "corrige" pas en douce
       une demande explicitement cloud, on la refuse en expliquant pourquoi.
  2. COMPLEXITE : tache lourde et anodine -> cloud (la puissance quand elle est utile).
  3. ECONOMIE   : tout le reste -> local (quasi gratuit sur notre materiel).

Doctrine default-deny (issue de la revue adversariale) :
  - Type d'appel inconnu (embeddings, generation d'image...) vers une route
    non locale -> REFUS : ce que la serrure ne sait pas inspecter ne sort pas.
  - Bloc non textuel (image, audio, fichier) -> traite comme sensible : une
    photo de carte vitale est invisible aux regex, donc elle reste en local.
  - Panne de la detection -> la demande part en LOCAL (jamais une 500, jamais
    le cloud) : une panne degrade la puissance, pas la confidentialite.

La logique de detection vit dans detection.py (pur Python, testable partout) ;
ce fichier-ci n'est que la plomberie LiteLLM (machine cible uniquement).
Journal : journal-routage.jsonl, metadonnees SEULEMENT (RGPD art. 32).
"""

import asyncio
import os

from fastapi import HTTPException
from litellm.integrations.custom_logger import CustomLogger

from detection import (
    CODES_TECHNIQUES,
    detecter_complexite,
    detecter_sensibilite_complete,
    extraire_texte,
    journaliser,
)

ROUTE_LOCALE = os.environ.get("CHEF_ROUTE_LOCALE", "local-sensible")
ROUTE_CLOUD = os.environ.get("CHEF_ROUTE_CLOUD", "cloud-lourd")
ROUTE_AUTO = os.environ.get("CHEF_ROUTE_AUTO", "chef-auto")
# Routes considerees comme locales (default-deny : tout le reste = sortie).
# ATTENTION : chaque nom liste ici doit pointer un backend local (ollama_*)
# dans config.yaml. C'est un engagement de configuration, verifie a la main.
ROUTES_LOCALES = {
    nom.strip()
    for nom in os.environ.get("CHEF_ROUTES_LOCALES", ROUTE_LOCALE + "," + ROUTE_AUTO).split(",")
    if nom.strip()
}

# Types d'appel dont on sait extraire et inspecter le contenu.
CALL_TYPES_INSPECTABLES = (
    "completion", "acompletion",
    "text_completion", "atext_completion",
    "anthropic_messages",
    "responses", "aresponses",
)


def _refus(motifs, message):
    return HTTPException(
        status_code=403,
        detail={
            "erreur": message,
            "motifs": motifs,
            "solution": "Renvoyer cette demande vers la route locale '%s'." % ROUTE_LOCALE,
        },
    )


class ChefOrchestre(CustomLogger):
    """Le hook appele par LiteLLM AVANT chaque appel de modele."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        modele_demande = data.get("model", "")
        cible_locale = modele_demande in ROUTES_LOCALES

        # ---- Type d'appel non inspectable : default-deny ----
        if call_type not in CALL_TYPES_INSPECTABLES:
            if cible_locale:
                journaliser("type-non-couvert-local", modele_demande, modele_demande,
                            ["call_type:" + str(call_type)], 0)
                return data
            journaliser("refus-type-non-couvert", modele_demande, None,
                        ["call_type:" + str(call_type)], 0)
            raise _refus(["call_type:" + str(call_type)],
                         "Demande refusee : type d'appel '%s' non inspectable par la serrure, "
                         "sortie vers une route non locale interdite (default-deny)." % call_type)

        # ---- Extraction du texte + detection (jamais une 500 : repli local) ----
        try:
            texte, non_inspectable = extraire_texte(data)
            # La loupe (GLiNER) peut prendre du temps CPU : on la sort de la boucle
            # asynchrone pour ne pas geler le standardiste pendant qu'elle travaille.
            boucle = asyncio.get_running_loop()
            motifs_sensibles = await boucle.run_in_executor(None, detecter_sensibilite_complete, texte)
            if non_inspectable:
                motifs_sensibles = motifs_sensibles + ["contenu-non-inspectable"]
        except Exception:
            texte = ""
            motifs_sensibles = ["detection-en-panne"]

        # ---- Pilier 1 : SENSIBILITE (gagne toujours) ----
        if motifs_sensibles:
            if not cible_locale:
                # FAIL-CLOSED : cible non locale + motif = refus net, message honnete.
                journaliser("refus-fail-closed", modele_demande, None, motifs_sensibles, len(texte))
                que_technique = all(m in CODES_TECHNIQUES for m in motifs_sensibles)
                if que_technique:
                    raise _refus(motifs_sensibles,
                                 "Demande refusee : contenu non verifiable par la serrure "
                                 "(detection indisponible ou bloc non textuel), "
                                 "sortie vers une route non locale interdite par prudence.")
                raise _refus(motifs_sensibles,
                             "Demande refusee : donnee sensible detectee, le cloud est "
                             "interdit pour cette classe de donnees (fail-closed).")
            # Cible locale (ou route auto) : on force le local, en le journalisant.
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
