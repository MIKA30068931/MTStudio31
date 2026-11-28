#!/usr/bin/env bash
# Installation de l'agent de dérushage (macOS / Linux)
set -e
ICI="$(cd "$(dirname "$0")" && pwd)"
echo "=== Installation de l'agent de dérushage ==="

if [ "$(uname)" = "Darwin" ]; then
  command -v brew >/dev/null || { echo "Installe Homebrew d'abord : https://brew.sh"; exit 1; }
  command -v python3 >/dev/null || brew install python
  command -v ffmpeg  >/dev/null || brew install ffmpeg
  DEST="$HOME/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"
else
  command -v python3 >/dev/null || { sudo apt-get update && sudo apt-get install -y python3 python3-pip; }
  command -v ffmpeg  >/dev/null || sudo apt-get install -y ffmpeg
  DEST="$HOME/.local/share/DaVinciResolve/Fusion/Scripts/Utility"
fi

echo "[Whisper et bibliothèques]"
python3 -m pip install --user --upgrade faster-whisper anthropic \
  || python3 -m pip install --user --break-system-packages --upgrade faster-whisper anthropic

mkdir -p "$DEST"
cp "$ICI"/derush_agent.py "$ICI"/illustrations.py "$ICI"/music.py "$ICI"/subtitles.py "$ICI"/habillage.py "$ICI"/export_timeline.py "$ICI"/logos.py "$ICI"/config.json "$DEST"/
echo "Scripts copiés dans : $DEST"
python3 "$ICI/verifier_installation.py"
echo "Reste à faire à la main : Resolve > Préférences > Système > Général > Scripts externes = Local."
