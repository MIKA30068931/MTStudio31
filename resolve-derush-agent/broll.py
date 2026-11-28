# -*- coding: utf-8 -*-
"""
B-roll adapté au dialogue : l'agent pose tes plans de coupe sur l'image (piste V2) quand la personne parle du sujet
du plan, pendant que sa voix continue (la piste audio de l'interview n'est jamais coupée).

Comment il choisit :
  1. Il inventorie tes plans de coupe (dossiers B-roll, Plans de coupe, Ambiance, Drone...).
  2. Il comprend ce que montre chaque plan grâce à : son nom de fichier et de dossier, ta description dans
     `broll.json` (créé automatiquement, à remplir : quelques mots suffisent), et, si une clé ANTHROPIC_API_KEY
     existe, une description automatique faite en regardant 3 images du plan (à vérifier).
  3. Il découpe le dialogue en phrases (transcription Whisper) et associe chaque phrase au plan qui correspond :
     par recoupement de mots-clés, ou par compréhension du sens avec Claude si la clé existe.
  4. Il pose le plan au moment où le mot-clé est prononcé, assez longtemps pour couvrir la phrase, en respectant des
     règles de montage (durée, écart entre deux plans, pas de répétition du même plan, jamais sur une coupe).
Les plans de coupe ne sont plus mis bout à bout sur V1 : ils servent uniquement de couverture.
"""
import base64
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

import illustrations as ill
import subtitles as st

STOP = ill.STOP_FR | set("""faire fait fais faisons voir vois vu dire dit aller va vais vont avoir ai as avons avez
chose choses truc trucs peu beaucoup vraiment tres très juste meme même autre autres quand comment pourquoi alors donc
oui non voila voilà ici là la""".split())


def norm(t):
    t = unicodedata.normalize("NFD", t.lower())
    return re.sub(r"[^a-z0-9 ]", " ", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def racine_mot(m):
    """Racine grossière pour rapprocher singulier/pluriel et conjugaisons proches (café/cafés, voitures/voiture)."""
    for suf in ("ements", "ement", "ations", "ation", "eurs", "eur", "es", "s", "x", "e"):
        if len(m) > len(suf) + 3 and m.endswith(suf):
            return m[:-len(suf)]
    return m


def mots_cles(texte):
    out = set()
    for m in norm(texte).split():
        if len(m) >= 4 and m not in STOP:
            out.add(racine_mot(m))
    return out


def decouper_nom(chemin, racine):
    """Mots d'un chemin : cafe_terrasse-2.mp4 dans B-roll/Ville -> {cafe, terrasse, ville}."""
    rel = Path(chemin).relative_to(racine)
    brut = " ".join(list(rel.parts[1:-1]) + [rel.stem])
    brut = re.sub(r"([a-z])([A-Z])", r"\1 \2", brut)  # CamelCase
    brut = re.sub(r"\d+", " ", brut)
    return mots_cles(brut.replace("_", " ").replace("-", " "))


# ------------------------------ catalogue ------------------------------ #
def categories_broll(cats, cfg):
    voulues = {c.lower() for c in (cfg.get("broll_categories") or cfg["sous_dossiers_sans_derush"])}
    return [c for c in cats if c.lower() in voulues]


def decrire_par_vision(chemin, duree):
    """3 images du plan envoyées à Claude : description courte en français (à vérifier)."""
    import anthropic
    imgs = []
    with tempfile.TemporaryDirectory() as tmp:
        for k, frac in enumerate((0.15, 0.5, 0.85)):
            f = Path(tmp) / f"{k}.jpg"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{duree * frac:.2f}",
                            "-i", str(chemin), "-frames:v", "1", "-vf", "scale=512:-2", str(f)], check=False)
            if f.exists():
                imgs.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                                         "data": base64.b64encode(f.read_bytes()).decode()}})
    if not imgs:
        return ""
    m = anthropic.Anthropic().messages.create(
        model=os.environ.get("MODELE_CLAUDE", "claude-haiku-5-5"), max_tokens=80,
        messages=[{"role": "user", "content": imgs + [{"type": "text", "text":
            "Ces 3 images viennent d'un même plan vidéo. Décris en 5 à 12 mots français ce qu'il montre "
            "(lieu, objet, action), sans phrase."}]}])
    return m.content[0].text.strip()


def inventaire(racine, cats, analyses_brutes, cfg):
    """Fiches des plans de coupe : {fichier, nom, duree_s, fps, mots}. Crée / complète broll.json."""
    racine = Path(racine)
    chemin_json = racine / "broll.json"
    data = json.loads(chemin_json.read_text("utf-8")) if chemin_json.exists() else {}
    data.setdefault("_aide", "Pour chaque plan, écris quelques mots qui disent ce qu'il montre (ex. « café, terrasse, "
                             "boisson »). L'agent s'en sert pour choisir le plan quand ce sujet est évoqué. "
                             "Laisse vide un plan qui ne doit jamais être posé automatiquement.")
    plans = data.setdefault("plans", {})
    cle_vision = bool(os.environ.get("ANTHROPIC_API_KEY")) and cfg.get("broll_vision", True)
    fiches = []
    for cat in categories_broll(cats, cfg):
        for a in analyses_brutes.get(cat, []):
            if not a["video"]:
                continue
            f = Path(a["fichier"])
            cle = str(f.relative_to(racine)).replace("\\", "/")
            e = plans.setdefault(cle, {"description": "", "_suggestion": ""})
            if cle_vision and not e.get("_suggestion") and not e.get("description"):
                try:
                    e["_suggestion"] = decrire_par_vision(f, a["duree_s"])
                except Exception as ex:
                    print(f"    ! description automatique impossible ({f.name}) : {str(ex)[:60]}")
            mots = decouper_nom(f, racine) | mots_cles(e.get("description", "")) | (
                mots_cles(e.get("_suggestion", "")) if not e.get("description") else set())
            if e.get("exclure"):
                continue
            fiches.append({"fichier": str(f), "cle": cle, "nom": f.stem, "duree_s": a["duree_s"], "fps": a["fps"],
                           "mots": mots, "description": e.get("description") or e.get("_suggestion") or ""})
    chemin_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    sans_desc = [c for c, e in plans.items() if not e.get("description") and not e.get("_suggestion")]
    if sans_desc:
        print(f"  {len(sans_desc)} plan(s) sans description (noms de fichiers seuls utilisés) : "
              "remplis broll.json pour de meilleurs choix.")
    return fiches


# ------------------------------ phrases ------------------------------ #
def phrases_du_clip(a, cfg):
    """[{start, end, texte, mots_cles, mots: [(racine, start, end)]}] d'après la transcription."""
    out = []
    for seg in ill.transcript_clip(a, cfg):
        mots = []
        for w in (seg.get("words") or st._repartir(seg)):
            r = racine_mot(norm(w["w"]).strip())
            if len(r) >= 3:
                mots.append((r, w["start"], w["end"]))
        out.append({"start": seg["start"], "end": seg["end"], "texte": seg["text"],
                    "cles": mots_cles(seg["text"]), "mots": mots})
    return out


def associer_mots_cles(phrase, fiches, cfg):
    """Meilleur plan pour une phrase, d'après le recoupement de mots-clés : (fiche, mot déclencheur) ou None."""
    meilleur, score_max, mot_decl = None, 0, None
    for f in fiches:
        commun = {m for m in phrase["cles"] if m in f["mots"] or any(
            len(m) >= 5 and len(x) >= 5 and (m.startswith(x) or x.startswith(m)) for x in f["mots"])}
        if len(commun) > score_max:
            meilleur, score_max, mot_decl = f, len(commun), commun
    if meilleur and score_max >= cfg.get("broll_score_min", 1):
        decl = min((t for t in phrase["mots"] if t[0] in mot_decl or any(
            len(t[0]) >= 5 and len(x) >= 5 and (t[0].startswith(x) or x.startswith(t[0])) for x in mot_decl)),
            key=lambda t: t[1], default=None)
        return meilleur, (decl[1] if decl else phrase["start"])
    return None


def associer_claude(phrases, fiches, cfg):
    """Association par le sens (clé Anthropic) : {index de phrase: fiche}. Le texte du dialogue est envoyé à Claude."""
    import anthropic
    catalogue = "\n".join(f"{i}: {f['description'] or f['nom']}" for i, f in enumerate(fiches))
    texte = "\n".join(f"{i}: {p['texte']}" for i, p in enumerate(phrases))
    m = anthropic.Anthropic().messages.create(
        model=os.environ.get("MODELE_CLAUDE", "claude-haiku-5-5"), max_tokens=1500,
        messages=[{"role": "user", "content":
            "Tu aides un monteur vidéo. Voici des phrases d'une interview (numérotées) et des plans de coupe (B-roll) "
            "disponibles (numérotés, avec leur description). Pour chaque phrase dont le sujet est clairement illustré "
            "par un plan, donne le numéro du plan ; sinon null. N'invente aucun lien : un plan hors sujet est pire "
            "que pas de plan.\nRéponds uniquement par un JSON {\"numéro de phrase\": numéro de plan ou null}.\n\n"
            f"PHRASES\n{texte}\n\nPLANS\n{catalogue}"}])
    rep = m.content[0].text
    data = json.loads(rep[rep.index("{"): rep.rindex("}") + 1])
    out = {}
    for k, v in data.items():
        if v is not None and str(k).isdigit() and int(k) < len(phrases) and str(v).isdigit() and int(v) < len(fiches):
            out[int(k)] = fiches[int(v)]
    return out


# ------------------------------ plan ------------------------------ #
def generer(analyses, categories, cfg, racine, fiches):
    """
    Retourne {"<cat>": [...], "__global__": [...]} ; éléments {"fichier","rec_frame","n","debut_src_img","type":"broll","texte"}.
    `analyses` = les clips de montage (sans les plans de coupe).
    """
    if not fiches:
        return {}
    fps = st.fps_timeline(analyses, cfg)
    par_clip = {}
    for cat in categories:
        for a in analyses[cat]:
            if a["audio"]:
                print(f"  [{cat}] recherche des sujets : {Path(a['fichier']).name}")
                phrases = phrases_du_clip(a, cfg)
                assoc = {}
                if os.environ.get("ANTHROPIC_API_KEY") and cfg.get("broll_claude", True) and phrases:
                    try:
                        assoc = {i: (f, phrases[i]["start"]) for i, f in associer_claude(phrases, fiches, cfg).items()}
                        for i, (f, _) in assoc.items():  # le mot déclencheur donne l'instant exact
                            r = associer_mots_cles(phrases[i], [f], dict(cfg, broll_score_min=1))
                            assoc[i] = (f, r[1] if r else phrases[i]["start"])
                    except Exception as e:
                        print(f"    ! association par le sens impossible ({str(e)[:50]}) : repli sur les mots-clés")
                if not assoc:
                    for i, p in enumerate(phrases):
                        r = associer_mots_cles(p, fiches, cfg)
                        if r:
                            assoc[i] = r
                par_clip[(cat, a["fichier"])] = [(phrases[i], f, t) for i, (f, t) in sorted(assoc.items())]

    d_min, d_max = cfg["broll_duree_min_s"], cfg["broll_duree_max_s"]

    def planifier(cats_incluses):
        items, pos = [], 0
        derniere_fin = -10 ** 9          # fin (images) du dernier B-roll posé
        usage = {}                        # plan -> (fin dernière utilisation en images, curseur dans le plan en images)
        for cat in cats_incluses:
            for a in analyses[cat]:
                pas, pos_fin = st.passages(a, fps, pos)
                for phrase, f, t_decl in par_clip.get((cat, a["fichier"]), []):
                    seg = next(((s, e, ds, p, n) for (s, e, ds, p, n) in pas if s - 0.05 <= t_decl < e), None)
                    if not seg:
                        continue  # phrase prononcée dans un silence retiré
                    s, e, ds, p, nseg = seg
                    rec = p + max(int(round(0.4 * fps)), int(round((t_decl - 0.3 - s) * fps)))  # pas collé à la coupe
                    fin_phrase = p + int(round((min(phrase["end"], e) - s) * fps))
                    n = int(round(max(d_min, min(d_max, (fin_phrase - rec) / fps + 0.5)) * fps))
                    n = min(n, p + nseg - rec - int(round(0.3 * fps)))  # rester dans le passage, sans mordre la coupe
                    if n < int(round(d_min * fps * 0.8)):
                        continue
                    if rec - derniere_fin < cfg["broll_ecart_min_s"] * fps:
                        continue  # trop près du B-roll précédent
                    fin_u, curseur = usage.get(f["cle"], (-10 ** 9, 0))
                    if rec - fin_u < cfg["broll_reutilisation_min_s"] * fps:
                        continue  # même plan trop vite redonné
                    total = int(f["duree_s"] * f["fps"])
                    if curseur + n > total:
                        curseur = 0
                    if n > total:
                        n = total
                    if n < int(round(d_min * fps * 0.8)):
                        continue
                    items.append({"fichier": f["fichier"], "rec_frame": rec, "n": n, "debut_src_img": curseur,
                                  "type": "broll", "texte": f["nom"] + " : " + phrase["texte"][:50]})
                    derniere_fin = rec + n
                    usage[f["cle"]] = (rec + n, curseur + n)  # la prochaine fois, on prend la suite du plan
                pos = pos_fin
        return items

    plan = {cat: planifier([cat]) for cat in categories}
    plan["__global__"] = planifier(list(analyses.keys()))
    print(f"  B-roll : {len(plan['__global__'])} plan(s) posé(s) sur la timeline globale")
    return plan
