# Lancement du Pupitre (Windows).
# La passphrase du coffre est demandee au terminal si CHEF_PUPITRE_PASSPHRASE
# n'est pas deja dans l'environnement. Elle n'est jamais ecrite sur le disque.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:CHEF_PUPITRE_BASE_URL) { $env:CHEF_PUPITRE_BASE_URL = "http://localhost:4000" }
if (-not $env:CHEF_PUPITRE_MODELE)   { $env:CHEF_PUPITRE_MODELE   = "chef-auto" }

& ".\.venv\Scripts\python.exe" serveur.py
