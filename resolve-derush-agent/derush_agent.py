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

try:  # module voisin (dans Resolve, __file__ peut être absent)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
except NameError:
    for _p in (os.path.expandvars(r"%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility"),
               os.path.expanduser("~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility"),
               os.path.expanduser("~/.local/share/DaVinciResolve/Fusion/Scripts/Utility")):
        sys.path.insert(0, _p)

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
    "illustrations": False,
    "langue": "fr",
    "whisper_modele": "small",
    "modele_claude": "claude-haiku-5-5",
    "illustration_duree_min_s": 4,
    "illustration_duree_max_s": 9,
    "dossier_illustrations": "Illustrations",
    "marqueurs": True,
    "marqueur_coupe_longue_s": 3,
    "sous_titres": False,
    "sous_titres_max_car_ligne": 38,
    "sous_titres_max_lignes": 2,
    "sous_titres_duree_max_s": 6,
    "sous_titres_duree_min_s": 1.0,
    "dossier_sous_titres": "Sous-titres",
    "vocabulaire": [],
    "musique": None,
    "musique_dossier": "Musique",
    "musique_sources": ["local", "jamendo", "openverse"],
    "musique_lufs": -26,
    "musique_ducking": True,
    "musique_ducking_ratio": 10,
    "musique_fade_in_s": 1.5,
    "musique_fade_out_s": 3,
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


def construire_dans_resolve(racine, cats, analyses, cfg, musique=None, sous_titres=None):
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

    # bin des illustrations
    ills = {}
    chemins_ill = sorted({i["fichier"] for l in analyses.values() for a in l
                          for i in a.get("illustrations", [])})
    if chemins_ill:
        b = mp.AddSubFolder(dossier_racine, "Illustrations")
        mp.SetCurrentFolder(b)
        for it in mp.ImportMedia(chemins_ill) or []:
            ills[os.path.normcase(it.GetClipProperty("File Path"))] = it
        mp.SetCurrentFolder(dossier_racine)
        print(f"  Bin Illustrations : {len(ills)}/{len(chemins_ill)} clips importés")

    def infos_timeline(cat_liste):
        out, overlays, pos = [], [], 0  # pos = images déjà posées sur V1
        for a in cat_liste:
            it = items.get(os.path.normcase(a["fichier"]))
            if it is None:
                print(f"  ! non importé, ignoré : {a['fichier']}")
                continue
            fps = float(it.GetClipProperty("FPS") or a["fps"] or fps_tl)
            total = int(float(it.GetClipProperty("Frames") or 0)) or vers_images(a["duree_s"], fps)
            coupes = []  # (début_s, fin_s, position V1 en images)
            precedent = 0.0
            entier = a["mode"].startswith("gardé")
            nom_f = Path(a["fichier"]).name
            for s, e in a["segments"]:
                d = min(vers_images(s, fps), total - 1)
                f = min(vers_images(e, fps), total) - 1  # endFrame inclusif
                if f > d:
                    gap = s - precedent  # silence retiré juste avant ce passage
                    if entier:
                        meta = ("Purple", f"Gardé entier - {nom_f}", a["mode"])
                    elif gap >= cfg["marqueur_coupe_longue_s"]:
                        meta = ("Yellow", f"Grosse coupe : -{gap:.1f}s - {nom_f}",
                                "Silence long supprimé juste avant : vérifier que rien d'utile n'a sauté.")
                    else:
                        meta = ("Blue", f"Dérushé - {nom_f}",
                                f"Silence supprimé avant : {max(gap, 0):.1f}s. Source {s:.1f}s -> {e:.1f}s")
                    out.append({"mediaPoolItem": it, "startFrame": d, "endFrame": f, "_meta": meta})
                    precedent = e
                    coupes.append((s, e, pos))
                    pos += f - d + 1
            for ill in a.get("illustrations", []):  # même propos = même instant, silences retirés
                mi = ills.get(os.path.normcase(ill["fichier"]))
                c = next((c for c in coupes if c[0] <= ill["src_start"] + 0.01 < c[1]), None)
                if mi is None or c is None:
                    continue
                n = vers_images(min(ill["src_end"], c[1]) - ill["src_start"], fps)
                n = min(n, int(float(mi.GetClipProperty("Frames") or n)))
                if n > 1:
                    overlays.append(({"mediaPoolItem": mi, "startFrame": 0, "endFrame": n - 1,
                                      "mediaType": 1, "trackIndex": 2,
                                      "_meta": ("Green", f"Illustration : {ill['requete']}",
                                                ill.get("texte", "") + (f"\nCrédit : {ill['credit']}"
                                                                        if ill.get("credit") else ""))},
                                     c[2] + vers_images(ill["src_start"] - c[0], fps)))
        return out, overlays

    cache_st = {}

    def poser_srt(tl, chemin):
        """Importe le .srt dans le bin « Sous-titres » et le pose sur la piste de sous-titres."""
        if not chemin:
            return
        if "bin" not in cache_st:
            cache_st["bin"] = mp.AddSubFolder(dossier_racine, "Sous-titres")
        mp.SetCurrentFolder(cache_st["bin"])
        imp = mp.ImportMedia([chemin]) or []
        mp.SetCurrentFolder(dossier_racine)
        if not imp:
            print(f"    ! sous-titres non importés : {chemin}")
            return
        try:
            while tl.GetTrackCount("subtitle") < 1:
                tl.AddTrack("subtitle")
            mp.AppendToTimeline([{"mediaPoolItem": imp[0], "trackIndex": 1,
                                  "recordFrame": tl.GetStartFrame()}])
            pose = bool(tl.GetItemListInTrack("subtitle", 1))
        except Exception as e:
            print(f"    (pose automatique impossible : {e})")
            pose = False
        if pose:
            print("    + sous-titres posés sur la piste de sous-titres")
        else:
            print("    ! pose automatique non confirmée : glisse le fichier du bin « Sous-titres » "
                  "sur la timeline")

    def timeline(nom, clips, overlays=(), srt=None):
        if not clips:
            return
        tl = mp.CreateEmptyTimeline(nom)
        if tl is None:
            tl = mp.CreateEmptyTimeline(f"{nom} {datetime.now():%H%M%S}")
        projet.SetCurrentTimeline(tl)
        nu = lambda c: {k: v for k, v in c.items() if k != "_meta"}
        ok = mp.AppendToTimeline([nu(c) for c in clips])
        print(f"  Timeline « {nom} » : {len(clips)} coupes ({'ok' if ok else 'ÉCHEC'})")
        debut = tl.GetStartFrame()
        if overlays:
            pose = [dict(nu(c), recordFrame=debut + off) for c, off in overlays]
            ok = mp.AppendToTimeline(pose)
            print(f"    + {len(pose)} illustrations sur V2 ({'ok' if ok else 'ÉCHEC'})")
        if cfg["marqueurs"]:
            n = marquer(tl, clips, overlays, debut)
            print(f"    + {n} marqueurs de couleur")
        poser_srt(tl, srt)
        return tl

    def poser_musique(tl, musique, frames_tl):
        b = mp.AddSubFolder(dossier_racine, "Musique")
        mp.SetCurrentFolder(b)
        imp = mp.ImportMedia([musique["fichier"]]) or []
        mp.SetCurrentFolder(dossier_racine)
        if not imp:
            print("  ! musique non importée")
            return
        n = min(frames_tl, int(float(imp[0].GetClipProperty("Frames") or frames_tl)))
        while tl.GetTrackCount("audio") < 2:
            tl.AddTrack("audio", "stereo")
        debut = tl.GetStartFrame()
        ok = mp.AppendToTimeline([{"mediaPoolItem": imp[0], "startFrame": 0, "endFrame": n - 1,
                                   "mediaType": 2, "trackIndex": 2, "recordFrame": debut}])
        print(f"    + musique « {musique['titre']} » sur A2 ({'ok' if ok else 'ÉCHEC'})")
        tl.AddMarker(debut, "Pink", f"Musique : {musique['titre']}",
                     f"Ambiance : {', '.join(musique['tags'])}\nCrédit : {musique['credit']}", 1, "derush")

    def marquer(tl, clips, overlays, debut):
        """Bleu=dérushé, Jaune=grosse coupe, Violet=gardé entier, Vert=illustration."""
        n = 0
        def poser(item, meta):
            nonlocal n
            couleur, nom, note = meta
            if item.AddMarker(0, couleur, nom, note, 1, "derush"):
                n += 1
        v1 = tl.GetItemListInTrack("video", 1) or []
        if len(v1) == len(clips):
            for item, c in zip(v1, clips):
                poser(item, c["_meta"])
        else:
            print(f"    ! V1 : {len(v1)} éléments pour {len(clips)} coupes, marqueurs V1 ignorés")
        par_debut = {it.GetStart(): it for it in (tl.GetItemListInTrack("video", 2) or [])}
        for c, off in overlays:
            item = par_debut.get(debut + off)
            if item:
                poser(item, c["_meta"])
        return n

    tout, tout_ov = [], []
    for cat, liste in analyses.items():
        clips, ov = infos_timeline(liste)
        tout_ov += [(c, off + sum(x["endFrame"] - x["startFrame"] + 1 for x in tout)) for c, off in ov]
        tout += clips
        if cfg["creer_timeline_par_categorie"]:
            timeline(f"{cat} - Dérushé", clips, ov, (sous_titres or {}).get(cat))
    if cfg["creer_timeline_globale"]:
        tl = timeline(f"{racine.name} - Dérushage global", tout, tout_ov, (sous_titres or {}).get("__global__"))
        if musique and tl:
            poser_musique(tl, musique, sum(x["endFrame"] - x["startFrame"] + 1 for x in tout))
    elif musique:
        print("  ! musique ignorée : active creer_timeline_globale")

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
    ap.add_argument("--illustrations", action="store_true",
                    help="Transcrit le dialogue, cherche des illustrations sur internet et les pose sur V2")
    ap.add_argument("--sous-titres", action="store_true",
                    help="Génère les sous-titres français (.srt) et les pose sur la timeline")
    ap.add_argument("--musique", metavar="AMBIANCE",
                    help='Ajoute une musique de fond : "calme, inspirant" ou "auto" (déduit du dialogue)')
    ap.add_argument("--musique-choisir", action="store_true", help="Propose la liste de pistes à choisir")
    ap.add_argument("--musique-dossier", help="Dossier de tes pistes (ex. téléchargées sur Epidemic Sound)")
    ap.add_argument("--seuil", type=float, help="Seuil de silence en dB (ex: -35)")
    ap.add_argument("--silence-min", type=float, help="Durée mini d'un silence supprimé (s)")
    args = ap.parse_args(sys.argv[1:] if "resolve" not in globals() else [])

    cfg = charger_config(args.config)
    if args.sous_titres:
        cfg["sous_titres"] = True
    if args.musique:
        cfg["musique"] = args.musique
    if args.musique_dossier:
        cfg["musique_dossier"] = args.musique_dossier
    if args.illustrations:
        cfg["illustrations"] = True
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

    sous_titres = None
    if cfg["sous_titres"]:
        import subtitles
        print("Sous-titres : transcription locale puis découpage...")
        cats_st = [c for c in analyses if doit_derusher(c, cfg)]
        sous_titres = subtitles.generer(analyses, cats_st, cfg, racine / cfg["dossier_sous_titres"])

    if cfg["illustrations"]:
        import illustrations
        dossier_ill = racine / cfg["dossier_illustrations"]
        print("Illustrations : transcription locale puis recherche internet...")
        for cat, liste in analyses.items():
            if not doit_derusher(cat, cfg):
                continue  # B-roll/ambiance : pas de dialogue à illustrer
            for a in liste:
                print(f"  [{cat}] {Path(a['fichier']).name}")
                a["illustrations"] = illustrations.planifier_illustrations(a, cfg, dossier_ill)

    musique = None
    if cfg["musique"]:
        import music
        musique = music.preparer_musique(cfg["musique"], analyses, racine, cfg, args.musique_choisir)

    rapport = racine / "rapport_derush.json"
    rapport.write_text(json.dumps(analyses, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Rapport : {rapport}")

    if not args.analyse_seule:
        construire_dans_resolve(racine, cats, analyses, cfg, musique, sous_titres)


if __name__ == "__main__" or "resolve" in globals():  # 2e cas : lancé depuis Resolve
    main()
