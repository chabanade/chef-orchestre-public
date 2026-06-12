#!/usr/bin/env bash
# Lancement du Pupitre (macOS / Linux).
# La passphrase du coffre est demandee au terminal si CHEF_PUPITRE_PASSPHRASE
# n'est pas deja dans l'environnement. Elle n'est jamais ecrite sur le disque.
set -e
cd "$(dirname "$0")"
# shellcheck disable=SC1091
source .venv/bin/activate

# Adresse du Chef d'Orchestre (le routeur). A adapter si besoin.
export CHEF_PUPITRE_BASE_URL="${CHEF_PUPITRE_BASE_URL:-http://localhost:4000}"
export CHEF_PUPITRE_MODELE="${CHEF_PUPITRE_MODELE:-chef-auto}"

python serveur.py
