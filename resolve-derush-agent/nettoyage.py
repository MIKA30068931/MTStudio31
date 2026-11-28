# -*- coding: utf-8 -*-
"""
Nettoyage au-delà des silences, à partir de la transcription Whisper (mot par mot) :
  - hésitations : « euh », « hum »... sont retirées (liste modifiable dans config.json) ;
  - prises répétées : si une phrase est redite quasiment à l'identique juste après (on recommence), on garde la
    DERNIÈRE version et on retire la première.
Tout ce qui est retiré est affiché (avec l'instant) pour que tu puisses vérifier.
"""
import difflib
import re
import unicodedata
from pathlib import Path

import illustrations as ill


def _norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def soustraire(segments, interdits, seg_min):
    """segments - interdits (listes de (début, fin) en s), en supprimant les restes plus courts que seg_min."""
    res = list(segments)
    for a, b in sorted(interdits):
        nouveau = []
        for s, e in res:
            if b <= s or a >= e:
                nouveau.append((s, e))
                continue
            if a - s > 0:
                nouveau.append((s, a))
            if e - b > 0:
                nouveau.append((b, e))
        res = nouveau
    return [(s, e) for s, e in res if e - s >= seg_min]


def hesitations(transcript, cfg):
    """[(début, fin, mot)] des hésitations repérées."""
    mots = {_norm(m) for m in cfg.get("hesitations", [])}
    out = []
    for seg in transcript:
        for w in seg.get("words", []):
            if _norm(w["w"]) in mots:
                out.append((max(0.0, w["start"] - 0.03), w["end"] + 0.08, w["w"]))
    return out


def repetitions(transcript, cfg):
    """[(début, fin, texte)] des prises à retirer : la phrase est redite après, on garde la dernière."""
    segs = [s for s in transcript if len(_norm(s["text"])) >= 20]
    out = []
    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            if b["start"] - a["end"] > cfg.get("repetition_fenetre_s", 30):
                break
            r = difflib.SequenceMatcher(None, _norm(a["text"]), _norm(b["text"])).ratio()
            if r >= cfg.get("repetition_similarite", 0.85):
                out.append((a["start"], a["end"], a["text"]))
                break
    return out


def appliquer(analyses, categories, cfg):
    """Retire hésitations et prises répétées des segments conservés de chaque clip."""
    seg_min = cfg["segment_min_s"]
    total_h = total_r = 0
    for cat in categories:
        for a in analyses[cat]:
            if not a["audio"] or a["mode"] != "dérushé":
                continue
            print(f"  [{cat}] nettoyage : {Path(a['fichier']).name}")
            tr = ill.transcript_clip(a, cfg)
            retirer = []
            if cfg.get("retirer_hesitations", True):
                h = hesitations(tr, cfg)
                total_h += len(h)
                retirer += [(s, e) for s, e, _ in h]
            if cfg.get("retirer_repetitions", True):
                r = repetitions(tr, cfg)
                total_r += len(r)
                retirer += [(s, e) for s, e, _ in r]
                for s, e, t in r[:8]:
                    print(f"    prise répétée retirée à {s:.0f}s : « {t[:60]} »")
            avant = sum(e - s for s, e in a["segments"])
            a["segments"] = soustraire(a["segments"], retirer, seg_min)
            apres = sum(e - s for s, e in a["segments"])
            a["gardé_s"] = round(apres, 3)
            a["supprimé_s"] = round(max(0.0, a["duree_s"] - apres), 3)
            a["mode"] = "dérushé et nettoyé"
            print(f"    -{avant - apres:.1f}s en plus (hésitations, répétitions)")
    print(f"  Nettoyage : {total_h} hésitation(s), {total_r} prise(s) répétée(s)")
