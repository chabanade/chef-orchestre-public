# -*- coding: utf-8 -*-
"""
La demonstration du Chef d'Orchestre en 4 actes.

Prerequis : le routeur tourne (start.sh / start.ps1), variable
LITELLM_MASTER_KEY presente dans l'environnement (chargee depuis .env).

  python demo.py            -> actes 1, 2 et 4
  python demo.py fail       -> acte 3 (a lancer APRES avoir coupe Ollama)
"""

import json
import os
import sys
import urllib.request
import urllib.error

ROUTEUR = os.environ.get("CHEF_ROUTEUR_URL", "http://localhost:4000")
CLE = os.environ.get("LITELLM_MASTER_KEY", "")

# Donnees FICTIVES pour la demo (aucun vrai client, aucune vraie donnee).
ACTES = {
    "1-anodin-simple": {
        "model": "chef-auto",
        "question": "Explique en deux phrases la difference entre un volt et un ampere.",
        "attendu": "part en LOCAL (tache simple, economie)",
    },
    "2-sensible": {
        "model": "chef-auto",
        "question": "Resume ce dossier : le client M. Exemple, IBAN FR76 3000 6000 0112 3456 7890 189, conteste la facture.",
        "attendu": "FORCE en LOCAL (IBAN + 'dossier client' detectes)",
    },
    "2bis-sensible-vers-cloud": {
        "model": "cloud-lourd",
        "question": "Analyse la fiche de paie de M. Exemple, salaire 2 800 euros.",
        "attendu": "REFUS 403 fail-closed (cloud explicitement demande + donnee sensible)",
    },
    "4-lourd-anodin": {
        "model": "chef-auto",
        "question": "Redige un rapport complet sur l'histoire de l'electrification rurale en France au 20e siecle, avec un plan detaille en cinq parties.",
        "attendu": "part vers le CLOUD (tache lourde, zero donnee sensible)",
    },
    "5-armoire-pseudo": {
        "model": "cloud-pseudo",
        "question": "Analyse ce paiement recurrent vers FR76 3000 6000 0112 3456 7890 189 et propose une formulation de relance.",
        "attendu": "IBAN remplace par <IBAN_1>, part au CLOUD pseudonymise, reponse re-personnalisee au retour (methode de l'armoire)",
    },
    "5bis-armoire-refus": {
        "model": "cloud-pseudo",
        "question": "Le patient Exemple est joignable au 06 12 34 56 78 pour son suivi.",
        "attendu": "REFUS 403 : le mot 'patient' (contexte metier) n'est pas remplacable, pseudonymisation incomplete",
    },
}

ACTE_FAIL_CLOSED = {
    "3-fail-closed": {
        "model": "chef-auto",
        "question": "Le patient M. Exemple, ne le 01/02/1980, presente un diagnostic a resumer.",
        "attendu": "ERREUR PROPRE (local coupe), AUCUNE bascule cloud : la porte casse fermee",
    },
}


def appeler(nom, acte):
    print("\n=== ACTE %s ===" % nom)
    print("Attendu : %s" % acte["attendu"])
    corps = json.dumps({
        "model": acte["model"],
        "messages": [{"role": "user", "content": acte["question"]}],
        "max_tokens": 120,
    }).encode("utf-8")
    requete = urllib.request.Request(
        ROUTEUR + "/v1/chat/completions",
        data=corps,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + CLE},
    )
    try:
        with urllib.request.urlopen(requete, timeout=180) as reponse:
            resultat = json.loads(reponse.read().decode("utf-8"))
        print("Resultat : OK, modele ayant repondu = %s" % resultat.get("model", "?"))
        contenu = resultat["choices"][0]["message"]["content"]
        print("Debut de reponse : %s..." % contenu[:160].replace("\n", " "))
    except urllib.error.HTTPError as erreur:
        detail = erreur.read().decode("utf-8", errors="replace")
        print("Resultat : HTTP %s -> %s" % (erreur.code, detail[:400]))
    except Exception as erreur:  # noqa: BLE001 - demo : on montre tout
        print("Resultat : ERREUR %s" % erreur)


if __name__ == "__main__":
    if not CLE:
        print("LITELLM_MASTER_KEY absente de l'environnement : charge .env d'abord.")
        sys.exit(1)
    series = ACTE_FAIL_CLOSED if (len(sys.argv) > 1 and sys.argv[1] == "fail") else ACTES
    for nom, acte in series.items():
        appeler(nom, acte)
    print("\nJournal des decisions : journal-routage.jsonl (aucun contenu, que des metadonnees).")
