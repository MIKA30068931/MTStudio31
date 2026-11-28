# -*- coding: utf-8 -*-
"""
Module « musique » de l'agent de dérushage.

Sources (dans l'ordre de config "musique_sources") :
  - local    : TES pistes déjà téléchargées (ex. avec ton abonnement Epidemic Sound) dans
               <Montage vidéo>/Musique/ ; les noms de sous-dossiers servent d'ambiance
               (Musique/calme/, Musique/dynamique/...).
  - jamendo  : musique Creative Commons (clé gratuite JAMENDO_CLIENT_ID), hors licences NC.
  - openverse: audio sous licence libre commerciale (sans clé).
Epidemic Sound n'a pas d'API publique de téléchargement : la bibliothèque n'est PAS aspirée.

Rendu : musique normalisée, baissée automatiquement sous la voix (ducking), fondus début/fin,
coupée à la durée du montage.
"""
import json
import os
import re
import subprocess
import tempfile
import urllib.parse
from pathlib import Path

import illustrations as ill  # _get_json, telecharger

EXT_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


# ------------------------------ ambiance -> tags ------------------------------ #
def ambiance_auto(analyses, cfg):
    """Déduit l'ambiance du projet depuis le dialogue (Claude si clé, sinon valeur neutre)."""
    texte = ""
    for liste in analyses.values():
        for a in liste:
            if a.get("audio") and a["mode"] == "dérushé":
                segs = ill.transcript_clip(a, cfg)
                texte += " ".join(s["text"] for s in segs) + " "
            if len(texte) > 4000:
                break
    if os.environ.get("ANTHROPIC_API_KEY") and texte.strip():
        try:
            import anthropic
            m = anthropic.Anthropic().messages.create(
                model=cfg.get("modele_claude", "claude-haiku-5-5"), max_tokens=100,
                messages=[{"role": "user", "content":
                    "Dialogue d'une vidéo :\n" + texte[:4000] + "\n\nDonne 3 à 5 tags musicaux EN ANGLAIS "
                    "(ambiance, genre, énergie) pour une musique de fond qui ne gêne pas la voix. "
                    "Réponds uniquement par les tags séparés par des virgules."}])
            return m.content[0].text.strip()
        except Exception as e:
            print(f"  ! ambiance auto via Claude impossible ({e})")
    print("  (ambiance neutre par défaut : précise-la avec --musique \"calme, inspirant\")")
    return "calm, ambient, background"


def vers_tags(ambiance, cfg):
    """Texte libre (français) -> tags anglais. Claude si clé, sinon mots tels quels."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic
            m = anthropic.Anthropic().messages.create(
                model=cfg.get("modele_claude", "claude-haiku-5-5"), max_tokens=60,
                messages=[{"role": "user", "content":
                    f"Traduis en 3 à 5 tags musicaux anglais (virgules, rien d'autre) : {ambiance}"}])
            ambiance = m.content[0].text
        except Exception:
            pass
    return [t.strip().lower() for t in re.split(r"[,;]", ambiance) if t.strip()]


# ------------------------------ recherche ------------------------------ #
def chercher_local(dossier, tags):
    if not dossier.is_dir():
        return []
    res = []
    for f in dossier.rglob("*"):
        if f.suffix.lower() in EXT_AUDIO and "_rendus" not in f.parts:
            texte = " ".join(f.relative_to(dossier).parts).lower()
            score = sum(t in texte for t in tags)
            res.append({"score": score, "titre": f.stem, "fichier": str(f), "source": "Local",
                        "credit": "Piste personnelle (licence de ton abonnement, ex. Epidemic Sound)",
                        "licence": "personnelle"})
    return sorted(res, key=lambda r: -r["score"])


def chercher_jamendo(tags):
    cle = os.environ.get("JAMENDO_CLIENT_ID")
    if not cle:
        return []
    q = urllib.parse.urlencode({"client_id": cle, "format": "json", "limit": 15,
                                "tags": "+".join(tags[:3]), "audiodlformat": "mp32",
                                "order": "popularity_month", "include": "musicinfo"})
    out = []
    for t in ill._get_json("https://api.jamendo.com/v3.0/tracks/?" + q).get("results", []):
        lic = t.get("license_ccurl", "")
        if "-nc" in lic or not t.get("audiodownload_allowed") or not t.get("audiodownload"):
            continue  # on écarte les licences non commerciales
        out.append({"titre": t["name"], "url": t["audiodownload"], "source": "Jamendo",
                    "licence": lic, "duree": t.get("duration"),
                    "credit": f"{t['name']} - {t['artist_name']} (Jamendo) {lic} {t.get('shareurl', '')}"})
    return out


def chercher_openverse(tags):
    q = urllib.parse.urlencode({"q": " ".join(tags[:3]), "license_type": "commercial",
                                "page_size": 15, "category": "music"})
    out = []
    for t in ill._get_json("https://api.openverse.org/v1/audio/?" + q).get("results", []):
        if t.get("url"):
            lic = f"{t.get('license', '?')} {t.get('license_version', '')}".strip()
            out.append({"titre": t.get("title", "?"), "url": t["url"], "source": "Openverse",
                        "licence": lic, "duree": (t.get("duration") or 0) / 1000,
                        "credit": f"{t.get('title', '?')} - {t.get('creator', '?')} ({lic}) "
                                  f"{t.get('foreign_landing_url', '')}"})
    return out


def trouver(tags, racine, cfg):
    sources = {"local": lambda: chercher_local(racine / cfg["musique_dossier"], tags),
               "jamendo": lambda: chercher_jamendo(tags), "openverse": lambda: chercher_openverse(tags)}
    for nom in cfg["musique_sources"]:
        try:
            r = sources[nom]()
        except Exception as e:
            print(f"  ! source {nom} : {e}")
            continue
        if r:
            print(f"  {len(r)} piste(s) trouvée(s) via {nom}")
            return r
    return []


def choisir(candidats, interactif):
    if not interactif or len(candidats) == 1:
        return candidats[0]
    for i, c in enumerate(candidats[:8], 1):
        print(f"   {i}. {c['titre']} ({c['source']}, {c['licence']})")
    rep = input("   Numéro de la piste (Entrée = 1) : ").strip()
    return candidats[int(rep) - 1] if rep.isdigit() and 0 < int(rep) <= len(candidats[:8]) else candidats[0]


# ------------------------------ rendu audio ------------------------------ #
def reference_dialogue(analyses, dossier):
    """WAV des passages conservés, bout à bout, dans l'ordre de la timeline globale."""
    morceaux, total = [], 0.0
    for liste in analyses.values():
        for k, a in enumerate(liste):
            segs = a["segments"]
            dur = sum(e - s for s, e in segs)
            if dur <= 0:
                continue
            out = dossier / f"ref_{len(morceaux):04d}.wav"
            if a.get("audio"):
                sel = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in segs)
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", a["fichier"], "-vn",
                       "-af", f"aselect='{sel}',asetpts=N/SR/TB,aformat=sample_rates=48000:channel_layouts=mono",
                       str(out)]
            else:  # clip muet : silence de même durée
                cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                       "anullsrc=r=48000:cl=mono", "-t", f"{dur:.3f}", str(out)]
            subprocess.run(cmd, check=True)
            morceaux.append(out)
            total += dur
    liste_txt = dossier / "ref.txt"
    liste_txt.write_text("".join(f"file '{m.as_posix()}'\n" for m in morceaux), encoding="utf-8")
    ref = dossier / "dialogue_ref.wav"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(liste_txt), "-c", "copy", str(ref)], check=True)
    return ref, total


def mixer(musique, ref, duree, sortie, cfg):
    """Normalise + boucle (étape 1), puis baisse sous la voix + fondus (étape 2)."""
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    norm = Path(str(sortie) + ".norm.wav")
    # étape 1 : loudnorm seul (combiné au ducking dans un même graphe, il tronque le flux)
    subprocess.run(base + ["-i", str(musique), "-af",
                   "aformat=sample_rates=48000:channel_layouts=stereo,aloop=loop=-1:size=2000000000,"
                   f"atrim=0:{duree:.3f},asetpts=PTS-STARTPTS,"
                   f"loudnorm=I={cfg['musique_lufs']}:TP=-2:LRA=11,"
                   f"aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:{duree:.3f}",
                   "-c:a", "pcm_s16le", str(norm)], check=True)
    fin = max(0.0, duree - cfg["musique_fade_out_s"])
    if cfg["musique_ducking"]:
        fc = ("[1:a]aformat=sample_rates=48000:channel_layouts=stereo[k];"
              f"[0:a][k]sidechaincompress=threshold=0.02:ratio={cfg['musique_ducking_ratio']}"
              ":attack=30:release=600:makeup=1[d];")
    else:
        fc = "[0:a]anull[d];"
    fc += (f"[d]afade=t=in:d={cfg['musique_fade_in_s']},"
           f"afade=t=out:st={fin:.3f}:d={cfg['musique_fade_out_s']}[out]")
    subprocess.run(base + ["-i", str(norm), "-i", str(ref), "-filter_complex", fc, "-map", "[out]",
                   "-t", f"{duree:.3f}", "-c:a", "pcm_s16le", str(sortie)], check=True)
    norm.unlink(missing_ok=True)
    return sortie


def mixer_fenetre(musique, ref, debut_s, duree_s, offset_s, fade_in, fade_out, sortie, cfg):
    """Extrait de musique pour la fenêtre [debut_s, debut_s+duree_s] de la timeline : normalisé, baissé sous la
    voix de CETTE fenêtre, fondus d'entrée et de sortie. `offset_s` = endroit du morceau où commencer."""
    base = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    norm = Path(str(sortie) + ".norm.wav")
    subprocess.run(base + ["-i", str(musique), "-af",
                   "aformat=sample_rates=48000:channel_layouts=stereo,aloop=loop=-1:size=2000000000,"
                   f"atrim=start={offset_s:.3f}:end={offset_s + duree_s:.3f},asetpts=PTS-STARTPTS,"
                   f"loudnorm=I={cfg['musique_lufs']}:TP=-2:LRA=11,"
                   f"aformat=sample_rates=48000:channel_layouts=stereo,apad,atrim=0:{duree_s:.3f}",
                   "-c:a", "pcm_s16le", str(norm)], check=True)
    if cfg["musique_ducking"]:
        fc = ("[1:a]aformat=sample_rates=48000:channel_layouts=stereo[k];"
              f"[0:a][k]sidechaincompress=threshold=0.02:ratio={cfg['musique_ducking_ratio']}"
              ":attack=30:release=600:makeup=1[d];")
    else:
        fc = "[0:a]anull[d];"
    fc += (f"[d]afade=t=in:d={fade_in:.3f},"
           f"afade=t=out:st={max(0.0, duree_s - fade_out):.3f}:d={fade_out:.3f}[out]")
    subprocess.run(base + ["-i", str(norm), "-ss", f"{debut_s:.3f}", "-t", f"{duree_s:.3f}", "-i", str(ref),
                   "-filter_complex", fc, "-map", "[out]", "-t", f"{duree_s:.3f}",
                   "-c:a", "pcm_s16le", str(sortie)], check=True)
    norm.unlink(missing_ok=True)
    return sortie


def sections_musique(analyses, cfg, fps):
    """Séquences (une par catégorie) avec début/fin en images sur la timeline globale, et total d'images."""
    import subtitles as st
    pos, sec = 0, []
    voulues = {c.lower() for c in cfg.get("musique_categories") or []}
    for cat, liste in analyses.items():
        a0 = pos
        for a in liste:
            _, pos = st.passages(a, fps, pos)
        if (not voulues or cat.lower() in voulues) and (pos - a0) / fps >= cfg["musique_section_min_s"]:
            sec.append({"cat": cat, "a": a0, "b": pos})
    return sec, pos


def _fichier_piste(piste, dossier):
    if "fichier" not in piste:
        brut = dossier / (re.sub(r"[^\w-]+", "_", piste["titre"])[:40] + ".mp3")
        ill.telecharger(piste["url"], brut)
        piste["fichier"] = str(brut)
    return piste["fichier"]


def preparer_musique(demande, analyses, racine, cfg, interactif=False):
    """
    Musique par séquence avec J-cut (la musique démarre avant l'image) et L-cut (elle se termine après, sous la
    voix de la séquence suivante), en fondu enchaîné aux jonctions.
    Retourne {"clips": [...], "fichier", "duree", "credit", "titre", "tags"} ou None.
    """
    import subtitles as st
    print("Musique : recherche d'une piste...")
    ambiance = ambiance_auto(analyses, cfg) if demande.strip().lower() == "auto" else demande
    tags = vers_tags(ambiance, cfg)
    print(f"  Ambiance : {', '.join(tags)}")
    cands = trouver(tags, racine, cfg)
    if not cands:
        print("  ! aucune musique trouvée (mets des pistes dans 'Musique/' ou définis JAMENDO_CLIENT_ID)")
        return None
    principale = choisir(cands, interactif)
    dossier = racine / cfg["musique_dossier"]
    dossier.mkdir(exist_ok=True)
    fps = st.fps_timeline(analyses, cfg)
    if cfg.get("musique_sections", True):
        sec, total = sections_musique(analyses, cfg, fps)
        J, L = cfg["musique_j_cut_s"], cfg["musique_l_cut_s"]
    else:  # ancienne manière : une seule nappe sur toute la timeline
        _, total = sections_musique(analyses, dict(cfg, musique_section_min_s=0), fps)
        sec, J, L = [{"cat": "tout", "a": 0, "b": total}], 0.0, 0.0
    if not sec:
        print("  ! aucune séquence assez longue pour la musique")
        return None
    # une piste différente par séquence si on en a plusieurs ; sinon la même, qui continue là où elle s'était arrêtée
    pistes = [principale] + [c for c in cands if c is not principale][:max(0, min(3, len(sec) - 1))]
    for p in pistes:
        _fichier_piste(p, dossier)
    total_s = total / fps
    clips, decalage = [], {}
    (dossier / "_rendus").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ref, _ = reference_dialogue(analyses, Path(tmp))
        for k, sc in enumerate(sec):
            debut = max(0.0, sc["a"] / fps - J)          # J-cut : démarre avant le changement d'image
            fin = min(total_s, sc["b"] / fps + L)         # L-cut : continue après, sous la voix suivante
            duree = fin - debut
            if duree < 1.0:
                continue
            fi = cfg["musique_fade_in_s"] if debut <= 0 else min(J + 0.7, duree / 2)
            fo = cfg["musique_fade_out_s"] if fin >= total_s - 0.01 else min(L + 1.0, duree / 2)
            idx = k % len(pistes)
            off = decalage.get(idx, 0.0)
            sortie = dossier / "_rendus" / f"musique_{k + 1:02d}.wav"
            mixer_fenetre(pistes[idx]["fichier"], ref, debut, duree, off, fi, fo, sortie, cfg)
            decalage[idx] = off + duree
            clips.append({"fichier": str(sortie), "rec_frame": int(round(debut * fps)),
                          "n": int(round(duree * fps)), "piste": k % 2, "cat": sc["cat"],
                          "titre": pistes[idx]["titre"]})
            print(f"  Séquence « {sc['cat']} » : {debut:.1f}s -> {fin:.1f}s (J-cut {J:g}s, L-cut {L:g}s)")
    log = dossier / "CREDITS_MUSIQUE.json"
    log.write_text(json.dumps({"ambiance": tags, "pistes": [{k: p[k] for k in ("titre", "source", "licence", "credit")}
                                                            for p in pistes]}, ensure_ascii=False, indent=2), "utf-8")
    if not clips:
        return None
    return {"clips": clips, "fichier": clips[0]["fichier"], "duree": total_s,
            "credit": " | ".join(p["credit"] for p in pistes), "titre": principale["titre"], "tags": tags}
