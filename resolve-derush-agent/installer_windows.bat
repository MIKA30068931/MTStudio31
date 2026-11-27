@echo off
chcp 65001 >nul
echo === Installation de l'agent de derushage (Windows) ===
echo.

where winget >nul 2>nul
if errorlevel 1 (
  echo winget est introuvable. Mets Windows a jour ou installe "App Installer" depuis le Microsoft Store.
  pause & exit /b 1
)

echo [1/4] Python 3...
py -3 --version >nul 2>nul || winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements

echo [2/4] ffmpeg...
where ffmpeg >nul 2>nul || winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements

echo [3/4] Whisper (transcription locale) et bibliotheques...
py -3 -m pip install --upgrade pip
py -3 -m pip install faster-whisper anthropic
if errorlevel 1 (
  echo.
  echo Python vient peut-etre d'etre installe : FERME cette fenetre, rouvre-la et relance ce fichier.
  pause & exit /b 1
)

echo [4/4] Copie des scripts dans DaVinci Resolve...
set "DEST=%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"
if not exist "%DEST%" mkdir "%DEST%"
copy /Y "%~dp0derush_agent.py" "%DEST%" >nul
copy /Y "%~dp0illustrations.py" "%DEST%" >nul
copy /Y "%~dp0music.py" "%DEST%" >nul
copy /Y "%~dp0subtitles.py" "%DEST%" >nul
copy /Y "%~dp0habillage.py" "%DEST%" >nul
copy /Y "%~dp0export_timeline.py" "%DEST%" >nul
copy /Y "%~dp0config.json" "%DEST%" >nul
echo Scripts copies dans : %DEST%

echo.
echo Verification...
py -3 "%~dp0verifier_installation.py"
echo.
echo Reste a faire a la main : dans Resolve, Preferences ^> Systeme ^> General ^> Scripts externes = Local.
pause
