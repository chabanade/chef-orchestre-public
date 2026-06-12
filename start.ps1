# Demarre le Chef d'Orchestre : Ollama (cuisine locale) + LiteLLM (standardiste).
$ErrorActionPreference = "Stop"
$Ici = $PSScriptRoot

# Charge .env (cles et reglages) sans jamais les afficher
if (Test-Path "$Ici\.env") {
    Get-Content "$Ici\.env" | Where-Object { $_ -match '^\s*[^#\s]' } | ForEach-Object {
        $nom, $valeur = $_ -split '=', 2
        [Environment]::SetEnvironmentVariable($nom.Trim(), $valeur.Trim(), "Process")
    }
}
if (-not $env:OLLAMA_API_BASE) { $env:OLLAMA_API_BASE = "http://localhost:11434" }

# 1. Ollama en service (s'il ne tourne pas deja)
try { Invoke-RestMethod "$env:OLLAMA_API_BASE/api/tags" | Out-Null; $ollamaOk = $true } catch { $ollamaOk = $false }
if (-not $ollamaOk) {
    Write-Host "Demarrage d'Ollama..."
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    foreach ($i in 1..30) {
        try { Invoke-RestMethod "$env:OLLAMA_API_BASE/api/tags" | Out-Null; break } catch { Start-Sleep 1 }
    }
}
Write-Host "Ollama : OK ($env:OLLAMA_API_BASE)"

# 2. Le standardiste LiteLLM avec la serrure
Set-Location $Ici
$port = if ($env:CHEF_PORT) { $env:CHEF_PORT } else { "4000" }
litellm --config config.yaml --port $port
