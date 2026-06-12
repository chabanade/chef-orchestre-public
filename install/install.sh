#!/usr/bin/env bash
# ============================================================
# Installation du Chef d'Orchestre - machine cible Linux (GPU)
# A lancer LE JOUR J sur la machine dediee, PAS sur le PC de travail.
# ============================================================
set -euo pipefail

ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELE="${OLLAMA_MODEL:-qwen3:4b}"   # sur machine GPU : OLLAMA_MODEL=qwen3:14b (ou plus)

echo "== 1/4 Ollama =="
if command -v ollama >/dev/null 2>&1; then
  echo "Ollama deja present : $(ollama --version)"
else
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo "== 2/4 Modele local ${MODELE} (licence permissive) =="
ollama pull "${MODELE}"

echo "== 3/4 LiteLLM (le standardiste) =="
python3 -m pip install --upgrade "litellm[proxy]"

echo "== 4/4 Fichier .env =="
if [ ! -f "${ICI}/.env" ]; then
  cp "${ICI}/.env.example" "${ICI}/.env"
  echo "ATTENTION : ${ICI}/.env cree depuis l'exemple. Remplir les cles (tuyau ferme) avant start.sh."
fi

echo "Installation terminee. Demarrer avec : bash ${ICI}/start.sh"
