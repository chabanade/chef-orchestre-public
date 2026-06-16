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

import vigie
try:
    import arbitre_desaccord
except ImportError:            # arbitre absent (deploiement partiel ou ancien) :
    arbitre_desaccord = None   # le routage marche sans lui (juste pas d'observabilite
                               # ni d'escalade). Degradation sure, jamais un crash.
from detection import (
    detecter_avec_detail,
    detecter_complexite,
    detecter_sensibilite_complete,
    est_couverture,
    est_technique,
    extraire_texte,
    journaliser,
)
from greffier import SESSION_ACTIVE, Greffier, jetons_restants, obtenir_armoire_session

CONSIGNE_JETONS = (
    "Des jetons de pseudonymisation au format <NOM_N> (par exemple <IBAN_1>) "
    "figurent dans cette conversation. Recopie-les EXACTEMENT tels quels dans ta "
    "reponse, sans les modifier, les reformuler ni les completer."
)

ROUTE_LOCALE = os.environ.get("CHEF_ROUTE_LOCALE", "local-sensible")
ROUTE_CLOUD = os.environ.get("CHEF_ROUTE_CLOUD", "cloud-lourd")
ROUTE_AUTO = os.environ.get("CHEF_ROUTE_AUTO", "chef-auto")
# Route "methode de l'armoire" (opt-in) : pseudonymiser puis cloud,
# re-personnalisation au retour. Voir greffier.py.
ROUTE_PSEUDO = os.environ.get("CHEF_ROUTE_PSEUDO", "cloud-pseudo")
# Route LOCALE FORTE : l'arbitre l'utilise sur fort doute (desaccord reel) pour
# reveiller un modele local plus puissant. VIDE -> on retombe sur ROUTE_LOCALE :
# aucune escalade, aucun changement de comportement (defaut sur). Reste local.
ROUTE_LOCALE_FORTE = os.environ.get("CHEF_ROUTE_LOCALE_FORTE", "").strip() or ROUTE_LOCALE

# L'armoire en transit : table de chaque demande pseudo en cours, par id
# d'appel. En memoire seulement, purgee au retour. Jamais journalisee.
_armoires_en_transit = {}
# Routes considerees comme locales (default-deny : tout le reste = sortie).
# ATTENTION : chaque nom liste ici doit pointer un backend local (ollama_*)
# dans config.yaml. C'est un engagement de configuration, verifie a la main.
ROUTES_LOCALES = {
    nom.strip()
    for nom in os.environ.get(
        "CHEF_ROUTES_LOCALES",
        ",".join([ROUTE_LOCALE, ROUTE_LOCALE_FORTE, ROUTE_AUTO])).split(",")
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
            # Une seule passe -> codes pour le routage ET detail par detecteur.
            boucle = asyncio.get_running_loop()
            motifs_sensibles, par_detecteurs = await boucle.run_in_executor(
                None, detecter_avec_detail, texte)
            if non_inspectable:
                motifs_sensibles = motifs_sensibles + ["contenu-non-inspectable"]
        except Exception:
            texte = ""
            motifs_sensibles = ["detection-en-panne"]
            par_detecteurs = {"regex": ["detection-en-panne"]}

        # Arbitre de desaccord : OBSERVABILITE seulement. Il ne change PAS le
        # routage (la sensibilite/fail-closed reste seule maitresse du local/cloud) ;
        # il journalise le niveau de DOUTE (desaccord reel entre detecteurs) pour
        # preparer l'escalade vers un modele plus puissant. Machine diagnostique,
        # humain decide. Non bloquant ; desactivable par CHEF_ARBITRE=0.
        decision_arbitre = None
        if arbitre_desaccord is not None and os.environ.get("CHEF_ARBITRE", "1") != "0":
            try:
                decision_arbitre = arbitre_desaccord.arbitrer(par_detecteurs)
                if decision_arbitre.niveau_doute in ("moyen", "eleve"):
                    journaliser("arbitre-doute", modele_demande, None,
                                ["doute:" + decision_arbitre.niveau_doute,
                                 "action:" + decision_arbitre.action]
                                + ["desaccord:" + c for c in decision_arbitre.desaccord], len(texte))
            except Exception:
                decision_arbitre = None

        # ---- Route PSEUDO (opt-in) : la methode de l'armoire ----
        if modele_demande == ROUTE_PSEUDO:
            if non_inspectable or "detection-en-panne" in motifs_sensibles:
                journaliser("refus-pseudo-non-inspectable", modele_demande, None, motifs_sensibles, len(texte))
                raise _refus(motifs_sensibles,
                             "Route pseudo refusee : contenu non inspectable ou detection en panne, "
                             "impossible de garantir une pseudonymisation complete.")
            # Armoire de session (decision 12/06) : meme conversation = meme
            # armoire, pour pouvoir iterer. Cle de session : metadata.session_id
            # (precis, conseille), sinon le champ standard "user", sinon une
            # armoire commune (suffisant pour un poste mono-utilisateur).
            armoire = None
            if SESSION_ACTIVE:
                cle_session = ((data.get("metadata") or {}).get("session_id")
                               or data.get("user") or "session-globale")
                armoire = obtenir_armoire_session(str(cle_session))
            greffier = Greffier(armoire=armoire)
            nb_jetons = greffier.pseudonymiser_demande(data)
            # Contre-verification sur le texte PSEUDONYMISE : s'il reste un
            # motif sensible (mot-cle metier, entite vue par la loupe), la
            # pseudonymisation est incomplete -> refus. Fail-closed.
            # La vigie scrute AUSSI le texte pseudo : un identifiant qui a
            # survecu au greffier (CPF bresilien sans pack actif...) est un
            # format INCONNU -> refus + alerte "demande de mise a jour".
            texte_pseudo, _ = extraire_texte(data)
            motifs_restants = await boucle.run_in_executor(None, detecter_sensibilite_complete, texte_pseudo)
            inconnus = vigie.identifiants_inconnus(texte_pseudo)
            if inconnus:
                vigie.signaler(inconnus, len(texte_pseudo))
                motifs_restants = motifs_restants + inconnus
            if motifs_restants:
                greffier.detruire()
                journaliser("refus-pseudo-incomplete", modele_demande, None, motifs_restants, len(texte))
                if any(est_couverture(m) for m in motifs_restants):
                    raise _refus(motifs_restants,
                                 "Route pseudo refusee : ce document sort des cases connues du "
                                 "routeur (identifiant ou origine non couverts). Renseignez le "
                                 "pays d'origine, activez le pack correspondant (CHEF_PACKS_PAYS, "
                                 "voir packs-pays/README.md) puis relancez. En attendant : route "
                                 "locale. Manque trace dans alertes-couverture.jsonl.")
                raise _refus(motifs_restants,
                             "Route pseudo refusee : il reste du sensible que le greffier ne sait pas "
                             "remplacer (noms, contexte metier). Utiliser la route locale.")
            if nb_jetons and isinstance(data.get("messages"), list):
                # Consigne anti-casse : le modele doit recopier les jetons
                # tels quels (risque n1 releve par l'etude du 12/06).
                data["messages"] = [{"role": "system", "content": CONSIGNE_JETONS}] + data["messages"]
            identifiant = data.get("litellm_call_id") or id(data)
            # Purge de securite : un appel qui a echoue en route ne doit pas
            # laisser son armoire s'accumuler en memoire.
            while len(_armoires_en_transit) > 100:
                _, orphelin = _armoires_en_transit.popitem()
                orphelin.detruire()
            _armoires_en_transit[identifiant] = greffier
            data["model"] = ROUTE_CLOUD
            data["stream"] = False  # la re-personnalisation au retour exige une reponse complete
            motifs_journal = ["jetons:" + str(nb_jetons)]
            if armoire is not None:
                motifs_journal.append("armoire-session")
            journaliser("pseudo-vers-cloud", modele_demande, ROUTE_CLOUD, motifs_journal, len(texte))
            return data

        # ---- Pilier 1 : SENSIBILITE (gagne toujours) ----
        if motifs_sensibles:
            if not cible_locale:
                # FAIL-CLOSED : cible non locale + motif = refus net, message honnete.
                journaliser("refus-fail-closed", modele_demande, None, motifs_sensibles, len(texte))
                if all(est_technique(m) for m in motifs_sensibles):
                    if any(est_couverture(m) for m in motifs_sensibles):
                        # La vigie : hors des cases connues -> demande de mise a jour.
                        raise _refus(motifs_sensibles,
                                     "Demande refusee : ce document sort des cases connues du "
                                     "routeur (ecriture, langue ou pack manquant). Renseignez "
                                     "l'origine du document et activez le pack pays correspondant "
                                     "(CHEF_PACKS_PAYS, voir packs-pays/README.md). En attendant : "
                                     "route locale. Manque trace dans alertes-couverture.jsonl.")
                    raise _refus(motifs_sensibles,
                                 "Demande refusee : contenu non verifiable par la serrure "
                                 "(detection indisponible ou bloc non textuel), "
                                 "sortie vers une route non locale interdite par prudence.")
                raise _refus(motifs_sensibles,
                             "Demande refusee : donnee sensible detectee, le cloud est "
                             "interdit pour cette classe de donnees (fail-closed).")
            # Cible locale (ou route auto) : on force le local. Si l'arbitre
            # signale une escalade (desaccord reel) ET qu'un palier fort distinct
            # est configure, on reveille le modele local plus puissant. Reste
            # local : le fail-closed n'est jamais affaibli.
            route = (arbitre_desaccord.route_escaladee(decision_arbitre, ROUTE_LOCALE, ROUTE_LOCALE_FORTE)
                     if arbitre_desaccord is not None else ROUTE_LOCALE)
            data["model"] = route
            etiquette = "escalade-local-fort" if route != ROUTE_LOCALE else "force-local-sensible"
            journaliser(etiquette, modele_demande, route, motifs_sensibles, len(texte))
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

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        """RETOUR de la route pseudo : re-personnalise la reponse en local,
        puis brule l'armoire. Si l'armoire est introuvable, la reponse part
        telle quelle (pseudonymisee) : sur, jamais bloquant."""
        identifiant = data.get("litellm_call_id") or id(data)
        greffier = _armoires_en_transit.pop(identifiant, None)
        if greffier is None:
            return response
        try:
            orphelins = []
            for choix in getattr(response, "choices", []) or []:
                message = getattr(choix, "message", None)
                if message is not None and isinstance(getattr(message, "content", None), str):
                    message.content = greffier.repersonnaliser(message.content)
                    orphelins += jetons_restants(message.content)
            # Controle d'integrite : un jeton non restaure (abime au-dela du
            # matching tolerant, ou hallucine par le modele) reste opaque dans
            # la reponse (aucune fuite) mais doit etre VISIBLE au journal.
            motifs = ["jetons:" + str(len(greffier.table))]
            if orphelins:
                motifs.append("jetons-non-restaures:" + str(len(orphelins)))
            journaliser("pseudo-retour-repersonnalise", None, None, motifs, 0)
        finally:
            greffier.detruire()
        return response


proxy_handler_instance = ChefOrchestre()
