# -*- coding: utf-8 -*-
"""Vérifie que tout ce dont l'agent a besoin est installé."""
import importlib.util
import os
import shutil
import sys

def ok(b): return "OK     " if b else "MANQUE "
res = []
res.append((sys.version_info >= (3, 8), f"Python {sys.version.split()[0]}", "installer Python 3"))
for exe in ("ffmpeg", "ffprobe"):
    res.append((shutil.which(exe) is not None, exe, "installer ffmpeg et rouvrir le terminal"))
for mod, aide in (("faster_whisper", "pip install faster-whisper (illustrations)"),
                  ("anthropic", "pip install anthropic (facultatif, meilleures requêtes)")):
    res.append((importlib.util.find_spec(mod) is not None, mod, aide))
print()
for b, nom, aide in res:
    print(f"  {ok(b)} {nom}" + ("" if b else f"   -> {aide}"))
print("\nClés facultatives (variables d'environnement) :")
for k in ("ANTHROPIC_API_KEY", "PEXELS_API_KEY", "PIXABAY_API_KEY", "JAMENDO_CLIENT_ID"):
    print(f"  {'définie ' if os.environ.get(k) else 'absente '} {k}")
indispensables = all(b for b, n, _ in res if n in ("ffmpeg", "ffprobe") or n.startswith("Python"))
print("\nDérushage de base :", "PRÊT" if indispensables else "pas prêt")
print("Illustrations     :", "PRÊT" if res[3][0] else "installer faster-whisper")
