# -*- coding: utf-8 -*-
"""
Logos animés : quand le dialogue cite une marque, son logo apparaît (animation « pop » + léger flottement).

Tu déposes les logos dans `Montage vidéo/Logos/` (PNG à fond transparent, pris sur la page officielle ou le
kit presse de la marque : l'agent ne télécharge aucun logo). Le NOM DU FICHIER = la marque :
    Logos/ElevenLabs.png   Logos/Notion.png   Logos/eleven-labs.png
Variantes de transcription à ajouter si besoin dans `Logos/logos.json` :
    {"ElevenLabs": ["eleven labs", "11 labs", "elevenlab"]}
Les mentions sont repérées dans la transcription Whisper (mot par mot) ; le logo est posé sur la piste V4.
"""
import difflib
import hashlib
import json
import re
import subprocess
import unicodedata
from pathlib import Path

import illustrations as ill
import subtitles as st

EXT_LOGOS = {".png", ".webp", ".jpg", ".jpeg", ".svg"}
POSITIONS = {"haut-droite": (0.88, 0.17), "haut-gauche": (0.12, 0.17),
             "bas-droite": (0.88, 0.83), "bas-gauche": (0.12, 0.83), "centre": (0.5, 0.5)}


def normaliser(t):
    t = unicodedata.normalize("NFD", t.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in t if unicodedata.category(c) != "Mn"))


# ------------------------------ chargement ------------------------------ #
def charger(racine, cfg):
    """{marque: {"fichier": chemin, "alias": {formes normalisées}}}. Crée le dossier s'il n'existe pas."""
    dossier = Path(racine) / cfg["dossier_logos"]
    if not dossier.exists():
        dossier.mkdir(parents=True)
        print(f"  Dossier « {cfg['dossier_logos']} » créé : dépose-y tes logos (ex. ElevenLabs.png) puis relance.")
        return {}
    extra = {}
    jf = dossier / "logos.json"
    if jf.exists():
        try:
            extra = json.loads(jf.read_text("utf-8"))
        except ValueError as e:
            print(f"  ! logos.json illisible ({e}), ignoré")
    marques = {}
    for f in sorted(dossier.iterdir()):
        if f.suffix.lower() in EXT_LOGOS:
            nom = f.stem
            alias = {normaliser(nom)} | {normaliser(a) for a in extra.get(nom, [])}
            marques[nom] = {"fichier": str(f), "alias": {a for a in alias if a}}
    if not marques:
        print(f"  Aucun logo dans « {cfg['dossier_logos']} » (formats : png, webp, jpg, svg).")
    return marques


# ------------------------------ détection ------------------------------ #
def trouver_mentions(mots, marques):
    """[(marque, début_s, fin_s)] dans une liste de mots horodatés (source du clip)."""
    norm = [normaliser(m["w"]) for m in mots]
    res, i = [], 0
    while i < len(mots):
        trouve = None
        for n in (3, 2, 1):  # on préfère l'expression la plus longue
            if i + n > len(mots):
                continue
            gram = "".join(norm[i:i + n])
            if not gram:
                continue
            for nom, m in marques.items():
                for a in m["alias"]:
                    if gram == a or (len(a) >= 6 and len(gram) >= 5 and
                                     difflib.SequenceMatcher(None, gram, a).ratio() >= 0.88):
                        trouve = (nom, mots[i]["start"], mots[i + n - 1]["end"], n)
                        break
                if trouve:
                    break
            if trouve:
                break
        if trouve:
            res.append(trouve[:3])
            i += trouve[3]
        else:
            i += 1
    return res


def mots_du_clip(a, cfg):
    mots = []
    for seg in ill.transcript_clip(a, cfg):
        mots += seg.get("words") or st._repartir(seg)
    return mots


# ------------------------------ rendu ------------------------------ #
def rendre_logo(logo, n_images, fps, sortie, res, cfg):
    """Logo : apparition « pop » (rebond), léger flottement, fondu de sortie, sur fond transparent."""
    W, H = res
    D = n_images / fps
    taille = int(min(W, H) * cfg["logo_taille"] * 1.78)  # = largeur * logo_taille en 16:9
    px, py = POSITIONS.get(cfg["logo_position"], POSITIONS["haut-droite"])
    ax, ay = int(W * px), int(H * py)
    marge = W * 0.04
    demi = taille * 1.1 / 2  # demi-largeur avec le rebond d'entrée
    ax = int(min(max(ax, marge + demi), W - marge - demi))  # le logo reste entièrement dans l'image
    x = "min(t/0.45,1)-1"
    pop = f"(1+2.70158*pow({x},3)+1.70158*pow({x},2))"
    sortie_exp = f"if(gt(t,{D:.3f}-0.3),max(0.02,({D:.3f}-t)/0.3),1)"
    fc = (f"[0:v]format=rgba,fade=t=in:st=0:d=0.2:alpha=1,fade=t=out:st={max(D - 0.3, 0):.3f}:d=0.3:alpha=1,"
          f"scale=w='max(2,{taille}*{pop}*{sortie_exp})':h=-1:eval=frame[l];"
          f"color=c=black@0:s={W}x{H}:r={fps}:d={D:.3f},format=rgba[c];"
          f"[c][l]overlay=x='{ax}-w/2':y='{ay}-h/2+{max(4, H // 180)}*sin(2*PI*t/2.2)':"
          f"eval=frame:format=auto,format=yuva444p10le[out]")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
                        "-framerate", str(fps), "-t", f"{D:.3f}", "-i", str(logo), "-filter_complex", fc,
                        "-map", "[out]", "-frames:v", str(n_images), "-c:v", "prores_ks", "-profile:v", "4444",
                        "-pix_fmt", "yuva444p10le", str(sortie)], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg (logo) : " + r.stderr.strip()[-300:])


# ------------------------------ plan ------------------------------ #
def generer(analyses, categories, cfg, racine, marques):
    """Retourne {"<cat>": [...], "__global__": [...]} ; éléments {"fichier","rec_frame","n","type":"logo","texte"}."""
    if not marques:
        return {}
    fps = st.fps_timeline(analyses, cfg)
    import habillage  # résolution commune
    res = habillage.resolution(analyses, cfg)
    dossier = Path(racine) / cfg["dossier_habillage"]
    dossier.mkdir(parents=True, exist_ok=True)

    mentions = {}  # (cat, fichier) -> [(marque, t0, t1)]
    for cat in categories:
        for a in analyses[cat]:
            if a["audio"]:
                print(f"  [{cat}] recherche des marques : {Path(a['fichier']).name}")
                mentions[(cat, a["fichier"])] = trouver_mentions(mots_du_clip(a, cfg), marques)

    def planifier(cats_incluses):
        items, pos = [], 0
        derniere = {}  # marque -> fin (images) de sa dernière apparition
        for cat in cats_incluses:
            for a in analyses[cat]:
                pas, pos_fin = st.passages(a, fps, pos)
                for marque, t0, t1 in mentions.get((cat, a["fichier"]), []):
                    seg = next(((s, e, ds, p, n) for (s, e, ds, p, n) in pas if s - 0.05 <= t0 < e), None)
                    if not seg:
                        continue  # mot prononcé dans un silence retiré
                    s, e, ds, p, nseg = seg
                    rec = p + max(0, int(round((t0 - s) * fps)))
                    n = min(int(round(cfg["logo_duree_s"] * fps)), p + nseg - rec)
                    if n < int(round(1.2 * fps)):
                        continue
                    if marque in derniere and rec - derniere[marque] < cfg["logo_repetition_min_s"] * fps:
                        continue
                    items.append({"marque": marque, "rec_frame": rec, "n": n})
                    derniere[marque] = rec + n
                pos = pos_fin
        items.sort(key=lambda i: i["rec_frame"])
        for i in range(len(items) - 1):  # pas de chevauchement sur la piste : le précédent s'arrête avant
            maxn = items[i + 1]["rec_frame"] - items[i]["rec_frame"] - 1
            items[i]["n"] = min(items[i]["n"], maxn)
        items = [i for i in items if i["n"] >= int(round(1.0 * fps))]
        out = []
        for i in items:
            h = hashlib.md5(json.dumps([i["marque"], i["n"], fps, res, cfg["logo_taille"],
                                        cfg["logo_position"]]).encode()).hexdigest()[:10]
            f = dossier / f"logo_{re.sub(r'[^A-Za-z0-9]+', '-', i['marque'])}_{h}.mov"
            if not f.exists():
                rendre_logo(marques[i["marque"]]["fichier"], i["n"], fps, f, res, cfg)
            out.append({"fichier": str(f), "rec_frame": i["rec_frame"], "n": i["n"], "type": "logo",
                        "texte": i["marque"]})
        return out

    plan = {cat: planifier([cat]) for cat in categories}
    plan["__global__"] = planifier(list(analyses.keys()))
    nb = len(plan["__global__"])
    print(f"  Logos : {nb} apparition(s) dans la timeline globale")
    return plan
