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

# Option --fine : installe la loupe (detection fine PII, GLiNER ~1-2 Go au 1er lancement)
# Option --fine-double : GLiNER + Presidio + modele spaCy francais (double verification,
# pour donnees ultra-sensibles ; mettre CHEF_DETECTION_FINE=gliner,presidio dans .env)
if [ "${1:-}" = "--fine" ] || [ "${1:-}" = "--fine-double" ]; then
  echo "== 3bis/4 Detection fine (la loupe, GLiNER) =="
  python3 -m pip install -r "${ICI}/requirements-fine.txt"
fi
if [ "${1:-}" = "--fine-double" ]; then
  echo "== 3ter/4 Double verification (Presidio + spaCy francais) =="
  python3 -m pip install presidio-analyzer spacy
  python3 -m spacy download fr_core_news_md
fi

echo "== 4/4 Fichier .env =="
if [ ! -f "${ICI}/.env" ]; then
  cp "${ICI}/.env.example" "${ICI}/.env"
  echo "ATTENTION : ${ICI}/.env cree depuis l'exemple. Remplir les cles (tuyau ferme) avant start.sh."
fi

echo "Installation terminee. Demarrer avec : bash ${ICI}/start.sh"
