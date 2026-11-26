#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent de dérushage pour DaVinci Resolve (18 -> 21).

Ce que fait l'agent :
  1. Scanne le dossier « Montage vidéo » : chaque sous-dossier = une catégorie de rushs.
  2. Crée automatiquement un projet Resolve + des bins « Rushs/<catégorie> » et importe tout.
  3. Détecte les silences (ffmpeg) et ne garde que les passages avec de la voix,
     avec des marges avant/après pour ne jamais couper un début ou une fin de phrase.
  4. Crée une timeline « <catégorie> - Dérushé » par catégorie + une timeline globale.

Usage :
  # Depuis Resolve (Studio ou gratuit) : Espace de travail > Scripts > derush_agent
  # Depuis un terminal (Resolve Studio ouvert) :
  python derush_agent.py "D:/Montage vidéo"
  # Test sans Resolve (affiche seulement les coupes prévues) :
  python derush_agent.py "D:/Montage vidéo" --analyse-seule
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

DEFAUTS = {
    "seuil_silence_db": -32,
    "duree_silence_min_s": 0.6,
    "marge_avant_s": 0.15,
    "marge_apres_s": 0.25,
    "segment_min_s": 0.4,
    "extensions": [".mp4", ".mov", ".mxf", ".mkv", ".avi", ".m4v", ".mts", ".mpg"],
    "sous_dossiers_sans_derush": ["B-roll", "BRoll", "Plans de coupe", "Ambiance", "Drone"],
    "nom_dossier_rushs_resolve": "Rushs",
    "fps_timeline": None,
    "creer_timeline_par_categorie": True,
    "creer_timeline_globale": True,
}


# --------------------------------------------------------------------------- #
#  Analyse audio (ffmpeg) - ne dépend pas de Resolve
# --------------------------------------------------------------------------- #
def ffprobe(chemin):
    """Retourne (durée_s, fps, a_audio, a_video)."""
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration:stream=codec_type,avg_frame_rate",
           "-of", "json", str(chemin)]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe a échoué sur {chemin}: {out.stderr.strip()}")
    data = json.loads(out.stdout or "{}")
    duree = float(data.get("format", {}).get("duration") or 0)
    a_audio = a_video = False
    fps = 25.0
    for s in data.get("streams", []):
        if s.get("codec_type") == "audio":
            a_audio = True
        elif s.get("codec_type") == "video" and not a_video:
            a_video = True
            num, _, den = (s.get("avg_frame_rate") or "25/1").partition("/")
            try:
                fps = float(num) / float(den or 1) or 25.0
            except (ValueError, ZeroDivisionError):
                fps = 25.0
    return duree, fps, a_audio, a_video


def detecter_silences(chemin, duree, cfg):
    """Liste de (début, fin) des silences, via le filtre silencedetect."""
    filtre = (f"highpass=f=80,lowpass=f=8000,"
              f"silencedetect=noise={cfg['seuil_silence_db']}dB:d={cfg['duree_silence_min_s']}")
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(chemin),
           "-vn", "-af", filtre, "-f", "null", "-"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    silences, debut = [], None
    for ligne in out.stderr.splitlines():
        m = re.search(r"silence_start:\s*(-?[\d.]+)", ligne)
        if m:
            debut = max(0.0, float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*(-?[\d.]+)", ligne)
        if m and debut is not None:
            silences.append((debut, min(duree, float(m.group(1)))))
            debut = None
    if debut is not None:  # silence jusqu'à la fin du fichier
        silences.append((debut, duree))
    return silences


def segments_parole(duree, silences, cfg):
    """Complément des silences, élargi par les marges, fusionné, filtré."""
    bruts, curseur = [], 0.0
    for s, e in silences:
        if s > curseur:
            bruts.append((curseur, s))
        curseur = max(curseur, e)
    if curseur < duree:
        bruts.append((curseur, duree))

    elargis = [(max(0.0, s - cfg["marge_avant_s"]), min(duree, e + cfg["marge_apres_s"]))
               for s, e in bruts]
    fusion = []
    for s, e in elargis:
        if fusion and s <= fusion[-1][1]:
            fusion[-1] = (fusion[-1][0], max(fusion[-1][1], e))
        else:
            fusion.append((s, e))
    return [(s, e) for s, e in fusion if e - s >= cfg["segment_min_s"]]


def analyser_clip(chemin, cfg, derusher=True):
    duree, fps, a_audio, a_video = ffprobe(chemin)
    info = {"fichier": str(chemin), "duree_s": round(duree, 3), "fps": fps,
            "audio": a_audio, "video": a_video}
    if not derusher or not a_audio or duree <= 0:
        info["segments"] = [(0.0, duree)]
        info["mode"] = "gardé entier" + ("" if a_audio else " (pas d'audio)")
    else:
        sil = detecter_silences(chemin, duree, cfg)
        info["segments"] = segments_parole(duree, sil, cfg)
        info["mode"] = "dérushé"
    gardé = sum(e - s for s, e in info["segments"])
    info["gardé_s"] = round(gardé, 3)
    info["supprimé_s"] = round(max(0.0, duree - gardé), 3)
    return info


# --------------------------------------------------------------------------- #
#  Scan du dossier « Montage vidéo »
# --------------------------------------------------------------------------- #
def scanner(racine, cfg):
    """{catégorie: [fichiers]}  - les fichiers à la racine vont dans « Vrac »."""
    exts = {e.lower() for e in cfg["extensions"]}
    cats = {}
    for dossier, sous, fichiers in os.walk(racine):
        sous[:] = sorted(d for d in sous if not d.startswith("."))
        rel = Path(dossier).relative_to(racine)
        nom = rel.parts[0] if rel.parts else "Vrac"
        for f in sorted(fichiers):
            if Path(f).suffix.lower() in exts and not f.startswith("."):
                cats.setdefault(nom, []).append(Path(dossier) / f)
    return dict(sorted(cats.items()))


def doit_derusher(categorie, cfg):
    exclus = {c.lower() for c in cfg["sous_dossiers_sans_derush"]}
    return categorie.lower() not in exclus


# --------------------------------------------------------------------------- #
#  Connexion à Resolve
# --------------------------------------------------------------------------- #
def obtenir_resolve():
    try:  # lancé depuis Resolve : l'objet est injecté
        return resolve  # noqa: F821
    except NameError:
        pass
    if sys.platform.startswith("win"):
        base = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                            "Blackmagic Design", "DaVinci Resolve", "Support",
                            "Developer", "Scripting", "Modules")
    elif sys.platform == "darwin":
        base = ("/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
                "Developer/Scripting/Modules")
    else:
        base = "/opt/resolve/Developer/Scripting/Modules"
    base = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules") \
        if os.environ.get("RESOLVE_SCRIPT_API") else base
    sys.path.append(base)
    try:
        import DaVinciResolveScript as dvr
    except ImportError:
        sys.exit("Impossible de charger l'API Resolve. Ouvrez DaVinci Resolve (Studio "
                 "pour un lancement externe) ou lancez le script depuis "
                 "Espace de travail > Scripts.")
    r = dvr.scriptapp("Resolve")
    if r is None:
        sys.exit("DaVinci Resolve ne répond pas. Ouvrez-le, puis Préférences > Système > "
                 "Général > « Scripts externes » = Local.")
    return r


def creer_projet(resolve, nom):
    pm = resolve.GetProjectManager()
    projet = pm.CreateProject(nom)
    n = 2
    while projet is None and n < 100:  # le nom existe déjà
        projet = pm.CreateProject(f"{nom} ({n})")
        n += 1
    if projet is None:
        sys.exit("Création du projet impossible (fermez le projet ouvert non sauvegardé ?).")
    return projet


def vers_images(secondes, fps):
    return int(round(secondes * fps))


def construire_dans_resolve(racine, cats, analyses, cfg):
    resolve = obtenir_resolve()
    nom_projet = f"{racine.name} - {datetime.now():%Y-%m-%d %H%M}"
    projet = creer_projet(resolve, nom_projet)
    print(f"Projet créé : {nom_projet}")

    mp = projet.GetMediaPool()
    dossier_racine = mp.GetRootFolder()
    bin_rushs = mp.AddSubFolder(dossier_racine, cfg["nom_dossier_rushs_resolve"])

    # fps / résolution de la timeline d'après le premier clip vidéo
    premier = next((a for liste in analyses.values() for a in liste if a["video"]), None)
    fps_tl = cfg["fps_timeline"] or (premier["fps"] if premier else 25)
    projet.SetSetting("timelineFrameRate", str(fps_tl))
    projet.SetSetting("timelinePlaybackFrameRate", str(fps_tl))

    # import par catégorie dans des bins séparés
    items = {}  # chemin -> MediaPoolItem
    for cat, fichiers in cats.items():
        b = mp.AddSubFolder(bin_rushs, cat)
        mp.SetCurrentFolder(b)
        importes = mp.ImportMedia([str(f) for f in fichiers]) or []
        for it in importes:
            items[os.path.normcase(it.GetClipProperty("File Path"))] = it
        print(f"  Bin Rushs/{cat} : {len(importes)}/{len(fichiers)} clips importés")
    mp.SetCurrentFolder(dossier_racine)

    if premier and not cfg["fps_timeline"]:
        try:
            res = items[os.path.normcase(premier["fichier"])].GetClipProperty("Resolution")
            w, h = res.split("x")
            projet.SetSetting("timelineResolutionWidth", w)
            projet.SetSetting("timelineResolutionHeight", h)
        except Exception:
            pass

    def infos_timeline(cat_liste):
        out = []
        for a in cat_liste:
            it = items.get(os.path.normcase(a["fichier"]))
            if it is None:
                print(f"  ! non importé, ignoré : {a['fichier']}")
                continue
            fps = float(it.GetClipProperty("FPS") or a["fps"] or fps_tl)
            total = int(float(it.GetClipProperty("Frames") or 0)) or vers_images(a["duree_s"], fps)
            for s, e in a["segments"]:
                d = min(vers_images(s, fps), total - 1)
                f = min(vers_images(e, fps), total) - 1  # endFrame inclusif
                if f > d:
                    out.append({"mediaPoolItem": it, "startFrame": d, "endFrame": f})
        return out

    def timeline(nom, clips):
        if not clips:
            return
        tl = mp.CreateEmptyTimeline(nom)
        if tl is None:
            tl = mp.CreateEmptyTimeline(f"{nom} {datetime.now():%H%M%S}")
        projet.SetCurrentTimeline(tl)
        ok = mp.AppendToTimeline(clips)
        print(f"  Timeline « {nom} » : {len(clips)} coupes ({'ok' if ok else 'ÉCHEC'})")

    tout = []
    for cat, liste in analyses.items():
        clips = infos_timeline(liste)
        tout += clips
        if cfg["creer_timeline_par_categorie"]:
            timeline(f"{cat} - Dérushé", clips)
    if cfg["creer_timeline_globale"]:
        timeline(f"{racine.name} - Dérushage global", tout)

    resolve.OpenPage("edit")
    pm = resolve.GetProjectManager()
    pm.SaveProject()
    print("Projet sauvegardé.")


# --------------------------------------------------------------------------- #
def charger_config(chemin_cfg):
    cfg = dict(DEFAUTS)
    if chemin_cfg:
        p = Path(chemin_cfg)
    elif "__file__" in globals():
        p = Path(__file__).with_name("config.json")
    else:
        p = None
    if p and p.exists():
        cfg.update(json.loads(p.read_text(encoding="utf-8")))
    return cfg


def choisir_dossier():
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        d = filedialog.askdirectory(title="Choisir le dossier « Montage vidéo »")
        r.destroy()
        if d:
            return d
    except Exception:
        pass
    return input("Chemin du dossier « Montage vidéo » : ").strip().strip('"')


def main():
    ap = argparse.ArgumentParser(description="Agent de dérushage DaVinci Resolve")
    ap.add_argument("dossier", nargs="?", help="Dossier « Montage vidéo » contenant les sous-dossiers de rushs")
    ap.add_argument("--config", help="Fichier config.json personnalisé")
    ap.add_argument("--analyse-seule", action="store_true",
                    help="N'ouvre pas Resolve : écrit seulement le rapport des coupes")
    ap.add_argument("--seuil", type=float, help="Seuil de silence en dB (ex: -35)")
    ap.add_argument("--silence-min", type=float, help="Durée mini d'un silence supprimé (s)")
    args = ap.parse_args(sys.argv[1:] if "resolve" not in globals() else [])

    cfg = charger_config(args.config)
    if args.seuil is not None:
        cfg["seuil_silence_db"] = args.seuil
    if args.silence_min is not None:
        cfg["duree_silence_min_s"] = args.silence_min

    racine = Path(args.dossier or choisir_dossier()).expanduser().resolve()
    if not racine.is_dir():
        sys.exit(f"Dossier introuvable : {racine}")
    for exe in ("ffmpeg", "ffprobe"):
        if subprocess.run([exe, "-version"], capture_output=True).returncode != 0:
            sys.exit(f"{exe} est requis (https://ffmpeg.org) et doit être dans le PATH.")

    cats = scanner(racine, cfg)
    if not cats:
        sys.exit("Aucun fichier vidéo trouvé dans ce dossier.")
    print(f"{sum(len(v) for v in cats.values())} rushs dans {len(cats)} catégorie(s) : "
          + ", ".join(cats))

    t0 = time.time()
    analyses = {}
    for cat, fichiers in cats.items():
        derush = doit_derusher(cat, cfg)
        analyses[cat] = []
        for f in fichiers:
            a = analyser_clip(f, cfg, derusher=derush)
            analyses[cat].append(a)
            print(f"  [{cat}] {f.name}: {a['mode']}, {len(a['segments'])} segment(s), "
                  f"-{a['supprimé_s']:.1f}s")
    tot_in = sum(a["duree_s"] for l in analyses.values() for a in l)
    tot_out = sum(a["gardé_s"] for l in analyses.values() for a in l)
    print(f"Analyse en {time.time() - t0:.0f}s : {tot_in / 60:.1f} min -> {tot_out / 60:.1f} min "
          f"({(1 - tot_out / tot_in) * 100 if tot_in else 0:.0f}% supprimé)")

    rapport = racine / "rapport_derush.json"
    rapport.write_text(json.dumps(analyses, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rapport : {rapport}")

    if not args.analyse_seule:
        construire_dans_resolve(racine, cats, analyses, cfg)


if __name__ == "__main__" or "resolve" in globals():  # 2e cas : lancé depuis Resolve
    main()
