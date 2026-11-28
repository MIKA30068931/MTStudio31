# -*- coding: utf-8 -*-
"""
Mode « sans scripting » : écrit la timeline dans un fichier FCPXML à importer dans DaVinci Resolve
(Fichier > Importer > Timeline...), même dans la version gratuite.

Contenu : une timeline par catégorie + une timeline globale, avec
  V1  les passages conservés (silences retirés)      A1  leur son
  V2  les illustrations   V3  bandeaux et titres     A2  la musique mixée
Les sous-titres restent des fichiers .srt à importer à part (Fichier > Importer > Sous-titres).
"""
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import subtitles as st

FCPXML_VERSION = "1.9"


# ------------------------------ temps ------------------------------ #
def duree_image(fps):
    """frameDuration sous forme (numérateur, dénominateur) en secondes."""
    for n, d in ((24000, 1001), (30000, 1001), (60000, 1001)):
        if abs(fps - n / d) < 0.02:
            return (d, n)
    return (1, int(round(fps)))


def t(frames, fd):
    return f"{int(frames) * fd[0]}/{fd[1]}s"


# ------------------------------ sonde ffprobe ------------------------------ #
def sonde(chemin):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:format_tags=timecode:stream=codec_type,width,height,"
                        "avg_frame_rate,channels,sample_rate:stream_tags=timecode",
                        "-of", "json", str(chemin)], capture_output=True, text=True)
    d = json.loads(r.stdout or "{}")
    info = {"duree": float(d.get("format", {}).get("duration") or 0), "video": False, "audio": False,
            "w": 0, "h": 0, "fps": 25.0, "canaux": 2, "hz": 48000, "tc": None}
    tcs = [d.get("format", {}).get("tags", {}).get("timecode")]
    for s in d.get("streams", []):
        tcs.append((s.get("tags") or {}).get("timecode"))
        if s.get("codec_type") == "video" and not info["video"]:
            info.update(video=True, w=int(s.get("width") or 0), h=int(s.get("height") or 0))
            n, _, de = (s.get("avg_frame_rate") or "25/1").partition("/")
            try:
                info["fps"] = float(n) / float(de or 1) or 25.0
            except (ValueError, ZeroDivisionError):
                pass
        elif s.get("codec_type") == "audio" and not info["audio"]:
            info.update(audio=True, canaux=int(s.get("channels") or 2), hz=int(s.get("sample_rate") or 48000))
    for tc in tcs:  # timecode de début de fichier, s'il existe (caméras)
        if tc:
            try:
                h, m, s_, f = [int(x) for x in tc.replace(";", ":").split(":")]
                info["tc"] = (h * 3600 + m * 60 + s_) * info["fps"] + f  # en images
            except ValueError:
                pass
            break
    return info


# ------------------------------ plan d'une timeline ------------------------------ #
def plan(analyses, categories_incluses, fps, plan_hab_items, musique):
    """
    Retourne (coupes, overlays) pour une timeline faite des catégories données, bout à bout.
      coupes   : [{"fichier","debut_img","n","rec","marqueur"}]      (V1/A1)
      overlays : [{"fichier","rec","n","lane","nom"}]                 (V2/V3)
    """
    coupes, overlays, pos = [], [], 0
    for cat in categories_incluses:
        for a in analyses[cat]:
            pas, pos_fin = st.passages(a, fps, pos)
            precedent = 0.0
            entier = a["mode"].startswith("gardé")
            for (s, e, ds, p, n) in pas:
                gap = s - precedent
                marq = None
                if not entier and gap >= 3:
                    marq = f"Grosse coupe : -{gap:.1f}s"
                coupes.append({"fichier": a["fichier"], "debut_img": ds, "n": n, "rec": p, "marqueur": marq,
                               "nom": Path(a["fichier"]).stem})
                precedent = e
            for ill in a.get("illustrations", []):
                c = next(((s, e, ds, p, n) for (s, e, ds, p, n) in pas
                          if s <= ill["src_start"] + 0.01 < e), None)
                if c:
                    s, e, ds, p, n = c
                    nb = int(round((min(ill["src_end"], e) - ill["src_start"]) * fps))
                    rec = p + int(round((ill["src_start"] - s) * fps))
                    if nb > 1:
                        overlays.append({"fichier": ill["fichier"], "rec": rec, "n": nb, "lane": 1,
                                         "nom": "Illustration : " + ill["requete"], "conform": True})
            pos = pos_fin
    for i in plan_hab_items or []:
        lane = 3 if i["type"] == "logo" else 2  # V4 pour les logos, V3 pour bandeaux et titres
        pref = {"bandeau": "Bandeau : ", "logo": "Logo : "}.get(i["type"], "Titre : ")
        overlays.append({"fichier": i["fichier"], "rec": i["rec_frame"], "n": i["n"], "lane": lane,
                         "nom": pref + i["texte"]})
    if musique:
        for mc in musique.get("clips") or [{"fichier": musique["fichier"], "rec_frame": 0, "piste": 0,
                                            "n": int(round(musique["duree"] * fps)), "titre": musique["titre"]}]:
            overlays.append({"fichier": mc["fichier"], "rec": mc["rec_frame"], "n": mc["n"],
                             "lane": -1 - mc["piste"], "nom": "Musique : " + mc["titre"], "audio": True})
    return coupes, overlays, pos


# ------------------------------ écriture FCPXML ------------------------------ #
class Ressources:
    def __init__(self, fps):
        self.res = ET.Element("resources")
        self.fps = fps
        self.fd_seq = duree_image(fps)
        self.formats, self.assets, self.n = {}, {}, 0

    def _id(self):
        self.n += 1
        return f"r{self.n}"

    def format(self, w, h, fps):
        fd = duree_image(fps)
        cle = (w, h, fd)
        if cle not in self.formats:
            i = self._id()
            nom = f"FFVideoFormat{w}x{h}p{int(round(fps))}"
            ET.SubElement(self.res, "format", id=i, name=nom, frameDuration=f"{fd[0]}/{fd[1]}s",
                          width=str(w), height=str(h), colorSpace="1-1-1 (Rec. 709)")
            self.formats[cle] = i
        return self.formats[cle]

    def asset(self, chemin):
        if chemin in self.assets:
            return self.assets[chemin]
        s = sonde(chemin)
        i = self._id()
        fd = duree_image(s["fps"] if s["video"] else self.fps)
        fps_a = s["fps"] if s["video"] else self.fps
        att = {"id": i, "name": Path(chemin).stem, "uid": f"derush-{i}",
               "start": t(round(s["tc"]), fd) if s["tc"] else "0s",
               "duration": t(round(s["duree"] * fps_a), fd),
               "hasVideo": "1" if s["video"] else "0", "hasAudio": "1" if s["audio"] else "0"}
        if s["video"]:
            att["format"] = self.format(s["w"], s["h"], s["fps"])
        if s["audio"]:
            att.update(audioSources="1", audioChannels=str(s["canaux"]), audioRate=str(s["hz"]))
        a = ET.SubElement(self.res, "asset", att)
        ET.SubElement(a, "media-rep", kind="original-media", src=Path(chemin).resolve().as_uri())
        self.assets[chemin] = (i, s, fd, round(s["tc"]) if s["tc"] else 0)
        return self.assets[chemin]


def self_fps(s, fps):
    return s["fps"] if s["video"] else fps


def _remplir(el, s, res_seq):
    """Plan d'une autre proportion que la timeline (ex. 16:9 dans un montage 9:16) : remplit l'écran (recadré au centre)."""
    if s["video"] and s["w"] and s["h"] and res_seq and abs(s["w"] / s["h"] - res_seq[0] / res_seq[1]) > 0.02:
        ET.SubElement(el, "adjust-conform", type="fill")


def _ajouter_timeline(event, ressources, nom, coupes, overlays, total, fps, fmt_id, res_seq=None):
    fd = ressources.fd_seq
    proj = ET.SubElement(event, "project", name=nom)
    seq = ET.SubElement(proj, "sequence", format=fmt_id, duration=t(total, fd), tcStart="0s",
                        tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")
    parents = []
    for c in coupes:
        ident, s, fda, tc0 = ressources.asset(c["fichier"])
        fps_a = s["fps"] if s["video"] else fps
        att = {"name": c["nom"], "ref": ident, "offset": t(c["rec"], fd),
               "start": t(tc0 + c["debut_img"], fda), "duration": t(c["n"], fd), "tcFormat": "NDF"}
        if s["video"]:
            att["format"] = ressources.format(s["w"], s["h"], s["fps"])
        el = ET.SubElement(spine, "asset-clip", att)
        _remplir(el, s, res_seq)
        if c.get("marqueur"):
            ET.SubElement(el, "marker", start=t(tc0 + c["debut_img"], fda),
                          duration=t(1, fda), value=c["marqueur"])
        parents.append((c, el, tc0, fda))
    for o in sorted(overlays, key=lambda o: o["rec"]):
        # rattaché au clip de V1 qui contient son début
        cible = next((p for p in parents if p[0]["rec"] <= o["rec"] < p[0]["rec"] + p[0]["n"]), parents[-1])
        c, el, tc0, fda = cible
        ident, s, fdo, tco = ressources.asset(o["fichier"])
        att = {"name": o["nom"], "ref": ident, "lane": str(o["lane"]),
               "offset": t(tc0 + c["debut_img"] + (o["rec"] - c["rec"]), fda),
               "start": t(tco, fdo),
               "duration": t(min(o["n"], int(s["duree"] * self_fps(s, fps))), fd)}
        if s["video"]:
            att["format"] = ressources.format(s["w"], s["h"], s["fps"])
        oc = ET.SubElement(el, "asset-clip", att)
        if o.get("conform"):
            _remplir(oc, s, res_seq)
    return proj


def exporter(analyses, categories, cfg, racine, sortie, musique=None, plan_hab=None):
    """Écrit le FCPXML et retourne son chemin."""
    fps = st.fps_timeline(analyses, cfg)
    premier = next((a for l in analyses.values() for a in l if a["video"]), None)
    w, h = (1920, 1080)
    if cfg.get("resolution_timeline"):
        w, h = cfg["resolution_timeline"]
    elif premier:
        s = sonde(premier["fichier"])
        w, h = s["w"] or w, s["h"] or h
    fcp = ET.Element("fcpxml", version=FCPXML_VERSION)
    res = Ressources(fps)
    fcp.append(res.res)
    fmt_id = res.format(w, h, fps)
    lib = ET.SubElement(fcp, "library")
    event = ET.SubElement(lib, "event", name=Path(racine).name)
    plans = []
    if cfg.get("creer_timeline_par_categorie", True):
        for cat in analyses:
            plans.append((f"{cat} - Dérushé", [cat], cat))
    if cfg.get("creer_timeline_globale", True):
        plans.append((f"{Path(racine).name} - Dérushage global", list(analyses.keys()), "__global__"))
    for nom, cats, cle in plans:
        hab = (plan_hab or {}).get(cle)
        coupes, ov, total = plan(analyses, cats, fps, hab, musique if cle == "__global__" else None)
        if coupes:
            _ajouter_timeline(event, res, nom, coupes, ov, total, fps, fmt_id, (w, h))
            print(f"  Timeline « {nom} » : {len(coupes)} coupes, {len(ov)} éléments sur V2/V3/A2")
    ET.indent(fcp, space="  ")
    sortie = Path(sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    corps = ET.tostring(fcp, encoding="unicode")
    sortie.write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + corps, encoding="utf-8")
    return sortie
