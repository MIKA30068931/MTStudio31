# -*- coding: utf-8 -*-
"""
Sous-titres français de l'agent de dérushage.

Whisper (local) donne chaque mot avec son horodatage ; on ne garde que les mots des passages
conservés, on recale leurs temps sur la timeline (silences retirés), on découpe en sous-titres
lisibles (2 lignes max, coupure aux phrases et aux changements de plan) et on écrit un fichier .srt
par catégorie + un pour la timeline globale.
"""
import re
from pathlib import Path

import illustrations as ill

NBSP = " "
FIN_PHRASE = (".", "?", "!", "…")
PAUSE_COUPE_S = 0.8        # pause entre deux mots qui force un nouveau sous-titre
ECART_IMAGES = 2           # images de vide entre deux sous-titres


# ------------------------------ temps / positions ------------------------------ #
def fps_timeline(analyses, cfg):
    if cfg.get("fps_timeline"):
        return float(cfg["fps_timeline"])
    premier = next((a for l in analyses.values() for a in l if a["video"]), None)
    return float(premier["fps"]) if premier else 25.0


def passages(analyse, fps, pos):
    """Passages conservés comme Resolve les posera : (src_s, src_e, début_src_images, pos, n_images)."""
    out = []
    for s, e in analyse["segments"]:
        ds, de = int(round(s * fps)), int(round(e * fps))
        if de - ds >= 2:  # même règle que la création des coupes (endFrame > startFrame)
            out.append((s, e, ds, pos, de - ds))
            pos += de - ds
    return out, pos


def mots_timeline(analyse, fps, pos, num_seg):
    """Mots du clip des passages conservés, avec leurs temps (secondes) sur la timeline."""
    pas, pos_fin = passages(analyse, fps, pos)
    mots = []
    for seg in analyse.get("transcript", []):
        liste = seg.get("words") or _repartir(seg)
        for w in liste:
            milieu = (w["start"] + w["end"]) / 2
            for k, (s, e, ds, p, n) in enumerate(pas):
                if s - 0.05 <= milieu < e:
                    def conv(t):
                        img = p + min(max(t * fps - ds, 0), n)
                        return img / fps
                    mots.append({"t": w["w"], "t0": conv(w["start"]), "t1": conv(w["end"]),
                                 "seg": num_seg + k})
                    break
    return mots, pos_fin, num_seg + len(pas)


def _repartir(seg):
    """Sans horodatage par mot : répartit les mots uniformément sur le segment."""
    mots = seg["text"].split()
    if not mots:
        return []
    pas = (seg["end"] - seg["start"]) / len(mots)
    return [{"w": m, "start": seg["start"] + i * pas, "end": seg["start"] + (i + 1) * pas}
            for i, m in enumerate(mots)]


# ------------------------------ découpage ------------------------------ #
def _texte(mots):
    return " ".join(m["t"] for m in mots)


def construire_cues(mots, cfg):
    maxc = cfg["sous_titres_max_car_ligne"]
    capacite = int(maxc * cfg["sous_titres_max_lignes"] * 0.9)
    dmax, dmin = cfg["sous_titres_duree_max_s"], cfg["sous_titres_duree_min_s"]
    cues, cur = [], []

    def fermer():
        nonlocal cur
        if cur:
            cues.append({"t0": cur[0]["t0"], "t1": cur[-1]["t1"], "texte": _texte(cur)})
        cur = []

    for w in mots:
        if cur:
            long = len(_texte(cur)) + 1 + len(w["t"]) > capacite
            coupe = (w["seg"] != cur[-1]["seg"]                      # changement de plan/coupe
                     or w["t0"] - cur[-1]["t1"] > PAUSE_COUPE_S      # vraie pause
                     or w["t1"] - cur[0]["t0"] > dmax                # trop long
                     or long)
            dur = cur[-1]["t1"] - cur[0]["t0"]
            phrase = cur[-1]["t"].endswith(FIN_PHRASE) and dur >= dmin
            virgule = cur[-1]["t"].endswith((",", ";", ":")) and len(_texte(cur)) >= 0.6 * capacite
            if coupe or phrase or virgule:
                fermer()
        cur.append(w)
    fermer()
    return _caler(cues, cfg)


def _caler(cues, cfg):
    """Léger avant/après, durée mini, pas de chevauchement."""
    gap = ECART_IMAGES / cfg["_fps"]
    for i, c in enumerate(cues):
        suivant = cues[i + 1]["t0"] if i + 1 < len(cues) else float("inf")
        c["t0"] = max(0.0, c["t0"] - 0.05)
        c["t1"] = c["t1"] + 0.15
        if c["t1"] - c["t0"] < cfg["sous_titres_duree_min_s"]:
            c["t1"] = c["t0"] + cfg["sous_titres_duree_min_s"]
        c["t1"] = min(c["t1"], suivant - gap)
    for i in range(1, len(cues)):  # t0 de départ ne doit pas passer sous la fin du précédent
        cues[i]["t0"] = max(cues[i]["t0"], cues[i - 1]["t1"] + gap)
    return [c for c in cues if c["t1"] > c["t0"]]


def typographie_fr(t):
    """Espaces insécables avant ? ! ; : et guillemets, sans toucher aux heures (12:30)."""
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"(?<=\S)\s*([?!;»])(?=\s|$)", NBSP + r"\1", t)
    t = re.sub(r"(?<=[^\d\s])\s*:(?=\s|$)", NBSP + ":", t)
    t = re.sub(r"«\s*", "«" + NBSP, t)
    return t


def en_lignes(texte, max_car, max_lignes):
    """Coupe en 1 ou 2 lignes équilibrées, de préférence après une virgule."""
    if len(texte) <= max_car or max_lignes < 2:
        return [texte]
    mots = texte.split(" ")
    meilleur, score = None, None
    for i in range(1, len(mots)):
        a, b = " ".join(mots[:i]), " ".join(mots[i:])
        s = max(len(a), len(b)) + (0 if a.endswith((",", ";", ":", ".")) else 3)
        if score is None or s < score:
            meilleur, score = [a, b], s
    return meilleur


# ------------------------------ SRT ------------------------------ #
def _hms(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def ecrire_srt(cues, chemin, cfg):
    blocs = []
    for i, c in enumerate(cues, 1):
        lignes = en_lignes(typographie_fr(c["texte"]), cfg["sous_titres_max_car_ligne"],
                           cfg["sous_titres_max_lignes"])
        blocs.append(f"{i}\n{_hms(c['t0'])} --> {_hms(c['t1'])}\n" + "\n".join(lignes) + "\n")
    Path(chemin).write_text("\n".join(blocs), encoding="utf-8")
    return len(cues)


# ------------------------------ point d'entrée ------------------------------ #
def generer(analyses, categories, cfg, dossier):
    """
    Transcrit les clips des `categories` puis écrit un SRT par catégorie + un global.
    Retourne {"<catégorie>": chemin, "__global__": chemin}.
    """
    dossier = Path(dossier)
    dossier.mkdir(parents=True, exist_ok=True)
    cfg = dict(cfg, _fps=fps_timeline(analyses, cfg))
    fps = cfg["_fps"]
    for cat in categories:
        for a in analyses[cat]:
            if a["audio"]:
                print(f"  [{cat}] transcription : {Path(a['fichier']).name}")
                ill.transcript_clip(a, cfg)

    # global : toutes les catégories bout à bout, comme la timeline globale
    pos_g, num_g, mots_g, resultat = 0, 0, [], {}
    for cat, liste in analyses.items():
        pos_c, num_c, mots_c = 0, 0, []
        for a in liste:
            if cat in categories and a["audio"]:
                m, _, _ = mots_timeline(a, fps, pos_c, num_c)
                mg, _, _ = mots_timeline(a, fps, pos_g, num_g)
                mots_c += m
                mots_g += mg
            _, pos_c = passages(a, fps, pos_c)
            num_c += len(passages(a, fps, 0)[0])
            _, pos_g = passages(a, fps, pos_g)
            num_g += len(passages(a, fps, 0)[0])
        if cat in categories and mots_c:
            nom_fichier = re.sub(r"[^\w-]+", "_", cat)
            f = dossier / (nom_fichier + ".srt")
            n = ecrire_srt(construire_cues(mots_c, cfg), f, cfg)
            resultat[cat] = str(f)
            print(f"  Sous-titres « {cat} » : {n} lignes -> {f.name}")
    if mots_g:
        f = dossier / "global.srt"
        n = ecrire_srt(construire_cues(mots_g, cfg), f, cfg)
        resultat["__global__"] = str(f)
        print(f"  Sous-titres globaux : {n} lignes -> {f.name}")
    return resultat
