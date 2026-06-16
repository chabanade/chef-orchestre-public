@echo off
REM Le Pupitre - lanceur Windows (double-clic).
REM Lance le script PowerShell d'installation/demarrage a cote de ce fichier.
title Le Pupitre
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lanceur.ps1"
echo.
echo (Cette fenetre peut etre fermee. Le Pupitre continue de tourner.)
pause
