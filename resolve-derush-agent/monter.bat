@echo off
chcp 65001 >nul
title Agent monteur video - montage automatique
echo.
echo === Montage automatique ===
echo Silences, hesitations, repetitions, sous-titres, bandeaux, logos, musique.
echo.
rem Glisse ton dossier "Montage video" sur ce fichier, ou double-clique pour le choisir.
if "%~1"=="" (
  py -3 "%~dp0derush_agent.py" --tout
) else (
  py -3 "%~dp0derush_agent.py" "%~1" --tout
)
echo.
echo Termine. Dans DaVinci Resolve : Fichier ^> Importer ^> Timeline, puis Fichier ^> Importer ^> Sous-titres.
pause
