#!/usr/bin/env bash
# Demarre le Chef d'Orchestre : Ollama (cuisine locale) + LiteLLM (standardiste).
set -euo pipefail
ICI="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Charge .env (cles et reglages) sans jamais les afficher
if [ -f "${ICI}/.env" ]; then set -a; . "${ICI}/.env"; set +a; fi
export OLLAMA_API_BASE="${OLLAMA_API_BASE:-http://localhost:11434}"

# 1. Ollama en service (s'il ne tourne pas deja)
if ! curl -s "${OLLAMA_API_BASE}/api/tags" >/dev/null 2>&1; then
  echo "Demarrage d'Ollama..."
  (ollama serve >/dev/null 2>&1 &)
  for _ in $(seq 1 30); do
    curl -s "${OLLAMA_API_BASE}/api/tags" >/dev/null 2>&1 && break
    sleep 1
  done
fi
echo "Ollama : OK (${OLLAMA_API_BASE})"

# 2. Le standardiste LiteLLM avec la serrure
cd "${ICI}"
exec litellm --config config.yaml --port "${CHEF_PORT:-4000}"
