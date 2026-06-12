# Installation du Pupitre sur Windows. A lancer sur la machine CIBLE.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "[Le Pupitre] Creation de l'environnement Python (.venv)..."
python -m venv .venv
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip

Write-Host "[Le Pupitre] Installation des dependances (dont SQLCipher)..."
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Host "[Le Pupitre] Termine. Lancer ensuite : .\start.ps1"
