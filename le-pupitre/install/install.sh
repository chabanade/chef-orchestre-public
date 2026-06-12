#!/usr/bin/env bash
# Installation du Pupitre sur macOS / Linux. A lancer sur la machine CIBLE.
set -e
cd "$(dirname "$0")/.."

echo "[Le Pupitre] Creation de l'environnement Python (.venv)..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[Le Pupitre] Installation des dependances (dont SQLCipher)..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[Le Pupitre] Termine. Lancer ensuite : ./start.sh"
