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
  # Dans Resolve Studio (ou Resolve gratuit <= 21.0) : Espace de travail > Scripts > derush_agent
  # Resolve gratuit 21.1+ (sans scripting) : mode export, voir ci-dessous (--export)
  # Depuis un terminal (Resolve Studio ouvert) :
  python derush_agent.py "D:/Montage vidéo"
  # Sans scripting (Resolve gratuit 21.1) : écrit un FCPXML à importer dans Resolve :
  python derush_agent.py "D:/Montage vidéo" --export --sous-titres
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
    "seuil_auto": True,
    "seuil_auto_marge_db": 2,
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
    "whisper_device": "auto",
    "modele_claude": "claude-haiku-5-5",
    "illustration_duree_min_s": 4,
    "illustration_duree_max_s": 9,
    "dossier_illustrations": "Illustrations",
    "marqueurs": True,
    "marqueur_coupe_longue_s": 3,
    "dossier_chutiers": "Chutiers",
    "chutiers_internet": True,
    "chutiers_ambiances": [],
    "chutiers_musiques_par_ambiance": 3,
    "chutiers_sfx_par_type": 3,
    "chutiers_seuil_dialogue": 0.25,
    "chutiers_copie_max_mo": 300,
    "chutiers_sfx_types": {"Whoosh": "whoosh", "Transition": "swoosh transition", "Impact": "impact hit",
                           "Clic et interface": "button click", "Notification": "notification chime",
                           "Riser": "riser build up", "Applaudissements": "applause", "Ambiance": "room tone ambience"},
    "nettoyage": False,
    "retirer_hesitations": True,
    "retirer_repetitions": True,
    "hesitations": ["euh", "heu", "hum", "hmm", "hm", "mmh", "mh", "hem"],
    "repetition_similarite": 0.85,
    "repetition_fenetre_s": 30,
    "demander_format": True,
    "format_video": None,
    "resolution_video": None,
    "resolution_timeline": None,
    "logos": False,
    "dossier_logos": "Logos",
    "logo_duree_s": 3.0,
    "logo_taille": 0.16,
    "logo_position": "haut-droite",
    "logo_repetition_min_s": 30,
    "habillage": False,
    "habillage_couleur_accent": "#F5A623",
    "habillage_couleur_fond": "#101820",
    "habillage_police": None,
    "habillage_resolution": None,
    "habillage_duree_bandeau_s": 5,
    "habillage_delai_bandeau_s": 1.0,
    "habillage_duree_titre_s": 3.5,
    "dossier_habillage": "Habillage",
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
    "musique_sections": True,
    "musique_j_cut_s": 1.5,
    "musique_l_cut_s": 2.5,
    "musique_categories": [],
    "musique_section_min_s": 3,
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


def niveaux_50ms(chemin):
    """
    Niveau de CRÊTE (dB) de chaque fenêtre de 50 ms, avec le même filtrage que la détection de silences.
    La crête et non la moyenne : silencedetect compare chaque échantillon au seuil, donc le bruit de fond n'est
    « silencieux » que si même ses pics restent sous le seuil.
    """
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(chemin), "-vn", "-af",
                          "highpass=f=80,lowpass=f=8000,aresample=16000,astats=metadata=1:reset=1:length=0.05,"
                          "ametadata=print:key=lavfi.astats.Overall.Peak_level:file=-",
                          "-f", "null", "-"], capture_output=True, text=True)
    niv = []
    for m in re.finditer(r"lavfi\.astats\.Overall\.Peak_level=(\S+)", out.stdout + out.stderr):
        try:
            v = float(m.group(1))
        except ValueError:
            continue
        niv.append(-90.0 if v != v or v < -90 else min(v, 0.0))  # silence numérique (-inf) = -90 dB
    return niv


def _otsu(niv):
    """Seuil (dB) qui sépare au mieux deux populations de niveaux : bruit de fond / parole."""
    cases = [0] * 91  # une case par dB, de -90 à 0
    for v in niv:
        cases[int(round(v)) + 90] += 1
    total, somme = len(niv), sum(i * c for i, c in enumerate(cases))
    w0 = s0 = 0
    meilleur, seuil = -1.0, None
    for t in range(91):
        w0 += cases[t]
        s0 += t * cases[t]
        if w0 == 0 or w0 == total:
            continue
        m0, m1 = s0 / w0, (somme - s0) / (total - w0)
        var = w0 * (total - w0) * (m0 - m1) ** 2
        if var > meilleur:
            meilleur, seuil, ecart = var, t - 90, m1 - m0
    return (seuil, ecart) if seuil is not None else (None, 0.0)


def seuil_auto(chemin, cfg):
    """
    Seuil de silence adapté à CE clip, quel que soit son volume ou son bruit de fond.
    On mesure le niveau toutes les 50 ms, puis on cherche la frontière entre deux populations (bruit de fond et
    parole). Si le clip est uniforme (pas deux populations nettes), repli sur le niveau de gating de loudnorm.
    Retourne le seuil en dB, ou None si impossible (clip sans signal).
    """
    niv = niveaux_50ms(chemin)
    if len(niv) < 20 or max(niv) <= -80:
        return None  # trop court ou sans signal : l'appelant gère (clip gardé entier)
    marge = cfg.get("seuil_auto_marge_db", 0)
    seuil, ecart = _otsu(niv)
    if seuil is not None and ecart >= 12:  # deux populations nettes (au moins 12 dB d'écart)
        return max(-75.0, min(-25.0, seuil + marge))
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(chemin), "-vn",
                          "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True)
    blocs = re.findall(r"\{[^{}]*\"input_thresh\"[^{}]*\}", out.stderr, re.S)
    try:
        t = float(json.loads(blocs[-1])["input_thresh"])
    except (IndexError, ValueError, KeyError):
        return None
    if t != t or t in (float("inf"), float("-inf")):
        return None
    return max(-75.0, min(-25.0, t + marge))


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


def niveaux(chemin):
    """(volume moyen, volume max) en dB, mesurés par ffmpeg ; None si indisponible."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(chemin), "-vn",
                          "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out.stderr)
    x = re.search(r"max_volume:\s*(-?[\d.]+) dB", out.stderr)
    return (float(m.group(1)), float(x.group(1))) if m and x else None


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
        cfg_clip = cfg
        if cfg.get("seuil_auto", True):
            s_auto = seuil_auto(chemin, cfg)
            if s_auto is not None:
                cfg_clip = dict(cfg, seuil_silence_db=round(s_auto, 1))
                info["seuil_db"] = cfg_clip["seuil_silence_db"]
        sil = detecter_silences(chemin, duree, cfg_clip)
        info["segments"] = segments_parole(duree, sil, cfg_clip)
        info["mode"] = "dérushé"
        if not info["segments"]:  # tout est « silence » : on ne supprime jamais un clip en entier
            niv = niveaux(chemin)
            info["segments"] = [(0.0, duree)]
            info["mode"] = "gardé entier (aucune parole détectée)"
            if niv and niv[1] <= -80:
                print(f"    ! {Path(chemin).name} : aucun son (niveau max {niv[1]:.0f} dB) : micro coupé ou "
                      "piste vide ? Le clip est gardé entier.")
            elif niv:
                sugg = int(niv[0] - 8)
                print(f"    ! {Path(chemin).name} : tout est sous le seuil ({cfg['seuil_silence_db']} dB). "
                      f"Volume moyen {niv[0]:.0f} dB, max {niv[1]:.0f} dB. Essaie --seuil {sugg}")
            else:
                print(f"    ! {Path(chemin).name} : aucune parole détectée, clip gardé entier")
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
    generes = {cfg[k].lower() for k in ("dossier_illustrations", "dossier_habillage",
                                        "dossier_sous_titres", "musique_dossier", "dossier_logos",
                                        "dossier_chutiers")} | {"sfx"} | {"export resolve"}
    cats = {}
    for dossier, sous, fichiers in os.walk(racine):
        sous[:] = sorted(d for d in sous if not d.startswith(".")
                         and not (Path(dossier) == Path(racine) and d.lower() in generes))
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
class ResolveIndisponible(Exception):
    """Resolve ne répond pas aux scripts (version gratuite 21.1, Resolve fermé, API absente...)."""


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
        raise ResolveIndisponible("Impossible de charger l'API Resolve (Studio requis hors de Resolve ; "
                                  "la version gratuite 21.1 n'a plus de scripting).")
    r = dvr.scriptapp("Resolve")
    if r is None:
        raise ResolveIndisponible("DaVinci Resolve ne répond pas aux scripts (fermé, ou scripting "
                                  "indisponible dans cette édition).")
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


def construire_dans_resolve(racine, cats, analyses, cfg, musique=None, sous_titres=None, habillage=None):
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

    if cfg.get("resolution_timeline"):
        w, h = cfg["resolution_timeline"]
        projet.SetSetting("timelineResolutionWidth", str(w))
        projet.SetSetting("timelineResolutionHeight", str(h))
    elif premier and not cfg["fps_timeline"]:
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

    hab_items = {}
    chemins_hab = sorted({i["fichier"] for l in (habillage or {}).values() for i in l})
    if chemins_hab:
        b = mp.AddSubFolder(dossier_racine, "Habillage")
        mp.SetCurrentFolder(b)
        for it in mp.ImportMedia(chemins_hab) or []:
            hab_items[os.path.normcase(it.GetClipProperty("File Path"))] = it
        mp.SetCurrentFolder(dossier_racine)
        print(f"  Bin Habillage : {len(hab_items)}/{len(chemins_hab)} clips importés")

    def hab_overlays(cle):
        out = []
        for i in (habillage or {}).get(cle, []):
            mi = hab_items.get(os.path.normcase(i["fichier"]))
            if mi is None:
                continue
            couleur = {"bandeau": "Cyan", "logo": "Fuchsia"}.get(i["type"], "Lavender")
            lib = {"bandeau": "Bandeau de nom", "logo": "Logo"}.get(i["type"], "Titre de section")
            out.append(({"mediaPoolItem": mi, "startFrame": 0, "endFrame": i["n"] - 1,
                         "mediaType": 1, "trackIndex": 4 if i["type"] == "logo" else 3,
                         "_meta": (couleur, f"{lib} : {i['texte']}",
                                   "Graphique animé généré par l'agent (piste V3). Pour changer le texte : "
                                   "modifier habillage.json puis relancer.")}, i["rec_frame"]))
        return out

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
        overlays = list(overlays)
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
            pistes = max(c["trackIndex"] for c, _ in overlays)
            while tl.GetTrackCount("video") < pistes:  # V2 (illustrations), V3 (habillage)
                tl.AddTrack("video")
            pose = [dict(nu(c), recordFrame=debut + off) for c, off in overlays]
            ok = mp.AppendToTimeline(pose)
            nb_ill = sum(1 for c, _ in overlays if c["trackIndex"] == 2)
            nb_hab = len(overlays) - nb_ill
            print(f"    + {nb_ill} illustrations (V2), {nb_hab} éléments d'habillage (V3) "
                  f"({'ok' if ok else 'ÉCHEC'})")
        if cfg["marqueurs"]:
            n = marquer(tl, clips, overlays, debut)
            print(f"    + {n} marqueurs de couleur")
        poser_srt(tl, srt)
        return tl

    def poser_musique(tl, musique, frames_tl):
        clips_m = musique.get("clips") or [{"fichier": musique["fichier"], "rec_frame": 0, "piste": 0,
                                            "n": frames_tl, "titre": musique["titre"]}]
        b = mp.AddSubFolder(dossier_racine, "Musique")
        mp.SetCurrentFolder(b)
        imp = mp.ImportMedia([c["fichier"] for c in clips_m]) or []
        mp.SetCurrentFolder(dossier_racine)
        par_chemin = {os.path.normcase(it.GetClipProperty("File Path")): it for it in imp}
        pistes = 1 + max(c["piste"] for c in clips_m) + 1
        while tl.GetTrackCount("audio") < pistes:  # A2 et A3 en alternance (chevauchements J/L-cut)
            tl.AddTrack("audio", "stereo")
        debut = tl.GetStartFrame()
        n_ok = 0
        for c in clips_m:
            it = par_chemin.get(os.path.normcase(c["fichier"]))
            if it is None:
                continue
            n = min(c["n"], int(float(it.GetClipProperty("Frames") or c["n"])))
            if mp.AppendToTimeline([{"mediaPoolItem": it, "startFrame": 0, "endFrame": n - 1, "mediaType": 2,
                                     "trackIndex": 2 + c["piste"], "recordFrame": debut + c["rec_frame"]}]):
                n_ok += 1
        print(f"    + musique « {musique['titre']} » : {n_ok}/{len(clips_m)} extraits sur A2/A3")
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
        par_debut = {(tr, it.GetStart()): it for tr in (2, 3, 4)
                     for it in (tl.GetItemListInTrack("video", tr) or [])}
        for c, off in overlays:
            item = par_debut.get((c["trackIndex"], debut + off))
            if item:
                poser(item, c["_meta"])
        return n

    tout, tout_ov = [], []
    for cat, liste in analyses.items():
        clips, ov = infos_timeline(liste)
        tout_ov += [(c, off + sum(x["endFrame"] - x["startFrame"] + 1 for x in tout)) for c, off in ov]
        tout += clips
        if cfg["creer_timeline_par_categorie"]:
            timeline(f"{cat} - Dérushé", clips, ov + hab_overlays(cat), (sous_titres or {}).get(cat))
    if cfg["creer_timeline_globale"]:
        tl = timeline(f"{racine.name} - Dérushage global", tout, tout_ov + hab_overlays("__global__"),
                      (sous_titres or {}).get("__global__"))
        if musique and tl:
            poser_musique(tl, musique, sum(x["endFrame"] - x["startFrame"] + 1 for x in tout))
    elif musique:
        print("  ! musique ignorée : active creer_timeline_globale")

    resolve.OpenPage("edit")
    pm = resolve.GetProjectManager()
    pm.SaveProject()
    print("Projet sauvegardé.")


# --------------------------------------------------------------------------- #
RESOLUTIONS = {("16:9", "1080p"): (1920, 1080), ("16:9", "4k"): (3840, 2160),
               ("9:16", "1080p"): (1080, 1920), ("9:16", "4k"): (2160, 3840)}


def _poser_question(texte, options, defaut):
    """Pose une question à choix ; Entrée ou une entrée non disponible = valeur par défaut."""
    print(texte)
    for i, (cle, lib) in enumerate(options, 1):
        print(f"  {i}) {lib}")
    try:
        rep = input(f"Ton choix [{defaut}] : ").strip().lower()
    except (EOFError, OSError):  # pas de clavier (lancement depuis Resolve) : valeur par défaut
        rep = ""
    if rep.isdigit() and 1 <= int(rep) <= len(options):
        return options[int(rep) - 1][0]
    for cle, _ in options:
        if rep and rep.replace(" ", "") == cle:
            return cle
    return options[defaut - 1][0]


def choisir_format(args, cfg):
    """Format (16:9 / 9:16) et qualité (1080p / 4K) : options, config, sinon questions."""
    fmt = (args.format or cfg.get("format_video") or "").lower() or None
    qual = (args.resolution or cfg.get("resolution_video") or "").lower() or None
    qual = {"fullhd": "1080p", "1080": "1080p", "uhd": "4k", "2160p": "4k"}.get(qual, qual)
    if fmt not in ("16:9", "9:16"):
        fmt = None
    if qual not in ("1080p", "4k"):
        qual = None
    if cfg.get("demander_format", True) and not args.sans_questions:
        print()
        if not fmt:
            fmt = _poser_question("Format du montage :", [("16:9", "16:9 - horizontal (YouTube, TV, site web)"),
                                  ("9:16", "9:16 - vertical (TikTok, Reels, Shorts)")], 1)
        if not qual:
            qual = _poser_question("Qualité du montage :", [("1080p", "1080p - Full HD (rapide, léger)"),
                                   ("4k", "4K - Ultra HD (plus lourd et plus long à rendre)")], 1)
        print()
    fmt, qual = fmt or "16:9", qual or "1080p"
    w, h = RESOLUTIONS[(fmt, qual)]
    cfg["format_video"], cfg["resolution_video"], cfg["resolution_timeline"] = fmt, qual, [w, h]
    if h > w and cfg["sous_titres_max_car_ligne"] == DEFAUTS["sous_titres_max_car_ligne"]:
        cfg["sous_titres_max_car_ligne"] = 26  # écran étroit : lignes de sous-titres plus courtes
    print(f"Montage : {fmt}, {qual} -> {w}x{h}")


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
    """Fenêtre de choix du dossier ; se souvient du dernier dossier utilisé."""
    memo = Path.home() / ".derush_agent_dernier_dossier.txt"
    dernier = ""
    try:
        dernier = memo.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    choix = ""
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk()
        r.withdraw()
        r.attributes("-topmost", True)
        choix = filedialog.askdirectory(title="Choisir le dossier « Montage vidéo »",
                                        initialdir=dernier if dernier and Path(dernier).is_dir() else None)
        r.destroy()
    except Exception:
        pass
    if not choix:
        choix = input(f"Chemin du dossier « Montage vidéo »{f' [{dernier}]' if dernier else ''} : ").strip().strip('"') \
            or dernier
    if choix:
        try:
            memo.write_text(choix, encoding="utf-8")
        except OSError:
            pass
    return choix


def main():
    ap = argparse.ArgumentParser(description="Agent de dérushage DaVinci Resolve")
    ap.add_argument("dossier", nargs="?", help="Dossier « Montage vidéo » contenant les sous-dossiers de rushs")
    ap.add_argument("--config", help="Fichier config.json personnalisé")
    ap.add_argument("--analyse-seule", action="store_true",
                    help="N'ouvre pas Resolve : écrit seulement le rapport des coupes")
    ap.add_argument("--illustrations", action="store_true",
                    help="Transcrit le dialogue, cherche des illustrations sur internet et les pose sur V2")
    ap.add_argument("--chutiers", action="store_true",
                    help="Prépare les chutiers (bins) AVANT le montage : rushs classés, musiques et SFX libres rangés")
    ap.add_argument("--ambiances", metavar="LISTE",
                    help='Ambiances de musique pour les chutiers, ex. "calme, dynamique, suspense"')
    ap.add_argument("--hors-ligne", action="store_true",
                    help="Chutiers : n'utilise aucun site internet, range seulement tes propres fichiers")
    ap.add_argument("--tout", action="store_true",
                    help="Montage complet automatique : silences, hésitations, répétitions, sous-titres, bandeaux, "
                         "logos (si dossier Logos) et musique (si dossier Musique)")
    ap.add_argument("--nettoyer", action="store_true",
                    help="Retire aussi les hésitations (euh) et les prises répétées (transcription Whisper)")
    ap.add_argument("--export", action="store_true",
                    help="N'utilise pas le scripting : écrit un fichier FCPXML à importer dans Resolve "
                         "(fonctionne avec la version gratuite)")
    ap.add_argument("--logos", action="store_true",
                    help="Affiche le logo animé d'une marque quand elle est citée (logos dans le dossier Logos/)")
    ap.add_argument("--habillage", action="store_true",
                    help="Ajoute bandeaux de nom et titres de sections animés (piste V3)")
    ap.add_argument("--sous-titres", action="store_true",
                    help="Génère les sous-titres français (.srt) et les pose sur la timeline")
    ap.add_argument("--musique", metavar="AMBIANCE",
                    help='Ajoute une musique de fond : "calme, inspirant" ou "auto" (déduit du dialogue)')
    ap.add_argument("--format", choices=["16:9", "9:16"], help="Format du montage (sinon l'agent te le demande)")
    ap.add_argument("--resolution", choices=["1080p", "4k"], help="Qualité du montage (sinon l'agent te la demande)")
    ap.add_argument("--sans-questions", action="store_true",
                    help="Ne pose aucune question : utilise les options, config.json ou 16:9 / 1080p")
    ap.add_argument("--musique-choisir", action="store_true", help="Propose la liste de pistes à choisir")
    ap.add_argument("--musique-dossier", help="Dossier de tes pistes (ex. téléchargées sur Epidemic Sound)")
    ap.add_argument("--seuil", help="Seuil de silence : un nombre en dB (ex: -45) ou « auto » (par défaut : "
                                    "l'agent le règle clip par clip d'après le volume)")
    ap.add_argument("--silence-min", type=float, help="Durée mini d'un silence supprimé (s)")
    args = ap.parse_args(sys.argv[1:] if "resolve" not in globals() else [])

    cfg = charger_config(args.config)
    if args.nettoyer:
        cfg["nettoyage"] = True
    if args.logos:
        cfg["logos"] = True
    if args.habillage:
        cfg["habillage"] = True
    if args.sous_titres:
        cfg["sous_titres"] = True
    if args.musique:
        cfg["musique"] = args.musique
    if args.musique_dossier:
        cfg["musique_dossier"] = args.musique_dossier
    if args.illustrations:
        cfg["illustrations"] = True
    if args.seuil is not None:
        if args.seuil.lower() == "auto":
            cfg["seuil_auto"] = True
        else:
            try:
                cfg["seuil_silence_db"] = float(args.seuil.replace(",", "."))
                cfg["seuil_auto"] = False  # un seuil donné à la main est respecté tel quel
            except ValueError:
                sys.exit("--seuil attend un nombre en dB (ex. -45) ou « auto ».")
    if args.silence_min is not None:
        cfg["duree_silence_min_s"] = args.silence_min

    racine = Path(args.dossier or choisir_dossier()).expanduser().resolve()
    if args.tout:
        cfg.update(nettoyage=True, sous_titres=True, habillage=True, logos=True)
        musiques = [f for f in (racine / cfg["musique_dossier"]).rglob("*")
                    if f.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg")
                    and "_rendus" not in f.parts] if (racine / cfg["musique_dossier"]).is_dir() else []
        if musiques and not cfg["musique"]:
            cfg["musique"] = "auto"
        args.export = True
        print("Mode tout automatique : silences, hésitations, répétitions, sous-titres, bandeaux, logos"
              + (", musique" if cfg["musique"] else ""))
    if not args.chutiers:  # les chutiers n'ont pas besoin du format du montage
        choisir_format(args, cfg)
    if not racine.is_dir():
        sys.exit(f"Dossier introuvable : {racine}")
    for exe in ("ffmpeg", "ffprobe"):
        if subprocess.run([exe, "-version"], capture_output=True).returncode != 0:
            sys.exit(f"{exe} est requis (https://ffmpeg.org) et doit être dans le PATH.")

    cfg_scan = dict(cfg, extensions=list(cfg["extensions"]) + [".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"]) \
        if args.chutiers else cfg  # chutiers : on range aussi les rushs audio (enregistreur de terrain)
    cats = scanner(racine, cfg_scan)
    if not cats:
        sys.exit("Aucun fichier vidéo trouvé dans ce dossier.")
    print(f"{sum(len(v) for v in cats.values())} rushs dans {len(cats)} catégorie(s) : "
          + ", ".join(cats))

    if args.chutiers:  # étape préparatoire : on range, on ne monte pas
        import chutiers
        if args.hors_ligne:
            cfg["chutiers_internet"] = False
        amb = [a.strip() for a in args.ambiances.split(",") if a.strip()] if args.ambiances else None
        chutiers.construire(racine, cats, cfg, analyser_clip, amb)
        return

    t0 = time.time()
    analyses = {}
    for cat, fichiers in cats.items():
        derush = doit_derusher(cat, cfg)
        analyses[cat] = []
        for f in fichiers:
            a = analyser_clip(f, cfg, derusher=derush)
            analyses[cat].append(a)
            seuil_txt = f", seuil auto {a['seuil_db']:g} dB" if "seuil_db" in a else ""
            print(f"  [{cat}] {f.name}: {a['mode']}, {len(a['segments'])} segment(s), "
                  f"-{a['supprimé_s']:.1f}s{seuil_txt}")
    tot_in = sum(a["duree_s"] for l in analyses.values() for a in l)
    tot_out = sum(a["gardé_s"] for l in analyses.values() for a in l)
    print(f"Analyse en {time.time() - t0:.0f}s : {tot_in / 60:.1f} min -> {tot_out / 60:.1f} min "
          f"({(1 - tot_out / tot_in) * 100 if tot_in else 0:.0f}% supprimé)")

    if cfg["nettoyage"]:
        import nettoyage
        print("Nettoyage : hésitations et prises répétées (transcription locale)...")
        nettoyage.appliquer(analyses, [c for c in analyses if doit_derusher(c, cfg)], cfg)

    marques = {}
    if cfg["logos"]:
        import logos
        print("Logos : lecture du dossier de logos...")
        marques = logos.charger(racine, cfg)
        # les noms de marques aident Whisper à bien les écrire (sous-titres compris)
        cfg["vocabulaire"] = list(cfg.get("vocabulaire") or []) + list(marques)

    sous_titres = None
    if cfg["sous_titres"]:
        import subtitles
        print("Sous-titres : transcription locale puis découpage...")
        cats_st = [c for c in analyses if doit_derusher(c, cfg)]
        sous_titres = subtitles.generer(analyses, cats_st, cfg, racine / cfg["dossier_sous_titres"])

    plan_hab = None
    if cfg["habillage"]:
        import habillage
        print("Habillage : bandeaux de nom et titres de sections...")
        plan_hab = habillage.generer(analyses, [c for c in analyses if doit_derusher(c, cfg)], cfg, racine)

    if marques:
        cats_logo = [c for c in analyses if doit_derusher(c, cfg)]
        plan_logos = logos.generer(analyses, cats_logo, cfg, racine, marques)
        plan_hab = plan_hab or {}
        for cle, liste in plan_logos.items():
            plan_hab[cle] = plan_hab.get(cle, []) + liste

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

    if args.analyse_seule:
        return
    if not args.export:
        try:
            construire_dans_resolve(racine, cats, analyses, cfg, musique, sous_titres, plan_hab)
            return
        except ResolveIndisponible as e:
            print(f"\n{e}\n-> Passage en mode export : fichier FCPXML à importer dans Resolve.")
    import export_timeline
    print("Export de la timeline (FCPXML)...")
    fichier = export_timeline.exporter(analyses, cats, cfg, racine,
                                       racine / "Export Resolve" / f"{racine.name}.fcpxml", musique, plan_hab)
    print(f"\nFichier créé : {fichier}")
    if args.tout and sys.platform.startswith("win"):
        try:
            os.startfile(str(fichier.parent))  # ouvre le dossier Export Resolve
        except OSError:
            pass
    print("Dans DaVinci Resolve :")
    print("  1. Fichier > Importer > Timeline... puis choisis ce fichier .fcpxml")
    print("  2. Si Resolve demande de lier les médias, coche « Chercher les médias dans... » et choisis "
          "ton dossier Montage vidéo")
    if sous_titres:
        print("  3. Sous-titres : ouvre la timeline, puis Fichier > Importer > Sous-titres... et choisis "
              f"le .srt du dossier {cfg['dossier_sous_titres']}/")


if __name__ == "__main__" or "resolve" in globals():  # 2e cas : lancé depuis Resolve
    main()
