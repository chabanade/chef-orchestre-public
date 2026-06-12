# ============================================================
# Installation du Chef d'Orchestre - machine cible Windows
# A lancer LE JOUR J sur la machine dediee, PAS sur le PC de travail.
# ============================================================
$ErrorActionPreference = "Stop"
$Ici = Split-Path -Parent $PSScriptRoot
$Modele = if ($env:OLLAMA_MODEL) { $env:OLLAMA_MODEL } else { "qwen3:4b" }

Write-Host "== 1/4 Ollama =="
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    Write-Host "Ollama deja present : $(ollama --version)"
} else {
    winget install --id Ollama.Ollama --accept-source-agreements --accept-package-agreements --silent
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
}

Write-Host "== 2/4 Modele local $Modele (licence permissive) =="
ollama pull $Modele

Write-Host "== 3/4 LiteLLM (le standardiste) =="
python -m pip install --upgrade "litellm[proxy]"

# Parametre -Fine : installe la loupe (detection fine PII, GLiNER ~1-2 Go au 1er lancement)
if ($args -contains "-Fine") {
    Write-Host "== 3bis/4 Detection fine (la loupe, GLiNER) =="
    python -m pip install -r "$Ici\requirements-fine.txt"
}

Write-Host "== 4/4 Fichier .env =="
if (-not (Test-Path "$Ici\.env")) {
    Copy-Item "$Ici\.env.example" "$Ici\.env"
    Write-Host "ATTENTION : $Ici\.env cree depuis l'exemple. Remplir les cles (tuyau ferme) avant start.ps1."
}

Write-Host "Installation terminee. Demarrer avec : .\start.ps1"
