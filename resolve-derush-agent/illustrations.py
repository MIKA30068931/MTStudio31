# -*- coding: utf-8 -*-
"""
Module « illustrations » de l'agent de dérushage.

Pipeline : transcription (Whisper) -> requêtes visuelles (Claude ou mots-clés)
-> recherche sur internet (Pexels / Pixabay / Wikimedia Commons)
-> téléchargement -> clips vidéo prêts à poser sur la piste V2.

ATTENTION confidentialité : les mots du dialogue (texte) sont envoyés aux services
de recherche (et à l'API Claude si ANTHROPIC_API_KEY est défini). L'audio n'est
jamais envoyé : la transcription est faite en local.
"""
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

UA = "DerushAgent/1.0 (outil de montage; contact: voir README)"

STOP_FR = set("""le la les un une des du de d l et ou mais donc or ni car que qui quoi dont où
ce cet cette ces mon ma mes ton ta tes son sa ses notre nos votre vos leur leurs je tu il elle on
nous vous ils elles me te se lui y en à au aux par pour sur sous dans avec sans chez vers entre
est sont était être été a ont avait avoir fait faire very très plus moins aussi alors comme si
pas ne n jamais toujours encore déjà bien mal peu trop tout tous toute toutes cela ça c qu s t m
voilà donc ensuite quand puis parce""".split())


# ------------------------------ transcription ------------------------------ #
_MODELE = {}


def _transcrire_avec(chemin, cfg, device, compute):
    from faster_whisper import WhisperModel
    nom = cfg.get("whisper_modele", "small")
    cle = (nom, device)
    if cle not in _MODELE:  # chargé une seule fois pour tous les clips
        _MODELE[cle] = WhisperModel(nom, device=device, compute_type=compute)
    vocab = cfg.get("vocabulaire") or []
    prompt = (", ".join(vocab) + ".") if vocab else ""
    if cfg.get("nettoyage") and cfg.get("retirer_hesitations", True):
        prompt += " Euh, hum, euh... bah, hum."  # incite Whisper à transcrire les hésitations (sinon il les omet)
    prompt = prompt.strip() or None
    segs, _ = _MODELE[cle].transcribe(
        str(chemin), language=cfg.get("langue", "fr"), vad_filter=True, word_timestamps=True,
        initial_prompt=prompt)
    out = []
    for s in segs:  # c'est ici que le calcul a vraiment lieu : une panne de GPU se manifeste à ce moment
        if s.text.strip():
            out.append({"start": s.start, "end": s.end, "text": s.text.strip(),
                        "words": [{"w": w.word.strip(), "start": w.start, "end": w.end}
                                  for w in (s.words or []) if w.word.strip()]})
    return out


def transcrire(chemin, cfg):
    """
    Segments [{start, end, text, words}] en secondes du fichier source (local, faster-whisper).
    Essaie la carte graphique si elle est utilisable, sinon bascule sur le processeur (plus lent, mais sûr).
    """
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        raise RuntimeError("Installe faster-whisper :  pip install faster-whisper")
    device = cfg.get("whisper_device", "auto")
    if device == "cpu":
        return _transcrire_avec(chemin, cfg, "cpu", "int8")
    try:
        return _transcrire_avec(chemin, cfg, device, "auto")
    except (RuntimeError, OSError) as e:
        msg = str(e).lower()
        if any(k in msg for k in ("cublas", "cudnn", "cuda", "dll", "library", "gpu")):
            print(f"  GPU inutilisable ({str(e)[:70]}...) : passage au processeur (plus lent).")
            _MODELE.clear()
            return _transcrire_avec(chemin, cfg, "cpu", "int8")
        raise


def transcript_clip(analyse, cfg):
    """Transcription d'un clip, calculée une seule fois (illustrations, sous-titres, ambiance)."""
    if "transcript" not in analyse:
        analyse["transcript"] = transcrire(analyse["fichier"], cfg)
    return analyse["transcript"]


def regrouper(segments, duree_min, duree_max):
    """Regroupe des phrases voisines en blocs de ~duree_min..duree_max secondes."""
    blocs, cur = [], None
    for s in segments:
        if cur is None:
            cur = dict(s)
        elif s["end"] - cur["start"] <= duree_max and cur["end"] - cur["start"] < duree_min:
            cur["end"], cur["text"] = s["end"], cur["text"] + " " + s["text"]
        else:
            blocs.append(cur)
            cur = dict(s)
    if cur:
        blocs.append(cur)
    return blocs


# ------------------------------ requêtes visuelles ------------------------------ #
def requetes_claude(blocs, cfg):
    """Une requête de recherche d'image (en anglais) par bloc, via l'API Claude."""
    import anthropic
    client = anthropic.Anthropic()
    texte = "\n".join(f"{i}: {b['text']}" for i, b in enumerate(blocs))
    msg = client.messages.create(
        model=cfg.get("modele_claude", "claude-haiku-5-5"), max_tokens=2000,
        messages=[{"role": "user", "content":
            "Voici des extraits numérotés d'un dialogue vidéo (français). Pour chacun, donne une "
            "requête de 2 à 4 mots EN ANGLAIS pour trouver une image/vidéo d'illustration de banque "
            "d'images, concrète et visuelle, fidèle au propos (pas d'abstraction, pas de personnes "
            "nommées). Si l'extrait ne s'illustre pas (bavardage, transition), mets null.\n"
            'Réponds uniquement en JSON : {"0": "query", "1": null, ...}\n\n' + texte}])
    rep = msg.content[0].text
    data = json.loads(rep[rep.index("{"): rep.rindex("}") + 1])
    return [data.get(str(i)) for i in range(len(blocs))]


def requetes_simples(blocs, cfg):
    """Sans IA : les 3 mots les plus longs/fréquents du bloc (qualité moindre, en français)."""
    out = []
    for b in blocs:
        mots = [m for m in re.findall(r"[\wÀ-ÿ'-]+", b["text"].lower())
                if m not in STOP_FR and len(m) > 3]
        top = sorted(dict.fromkeys(mots), key=lambda m: (-mots.count(m), -len(m)))[:3]
        out.append(" ".join(top) or None)
    return out


def construire_requetes(blocs, cfg):
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return requetes_claude(blocs, cfg)
        except Exception as e:
            print(f"  ! API Claude indisponible ({e}), repli sur mots-clés simples")
    else:
        print("  (ANTHROPIC_API_KEY absent : requêtes par mots-clés simples, moins pertinentes)")
    return requetes_simples(blocs, cfg)


# ------------------------------ recherche internet ------------------------------ #
def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def chercher_pexels(q):
    cle = os.environ.get("PEXELS_API_KEY")
    if not cle:
        return []
    h = {"Authorization": cle}
    res = []
    d = _get_json("https://api.pexels.com/videos/search?per_page=5&orientation=landscape&query="
                  + urllib.parse.quote(q), h)
    for v in d.get("videos", []):
        fichiers = [f for f in v["video_files"] if f.get("width") and f["width"] <= 1920
                    and f["file_type"] == "video/mp4"]
        if fichiers:
            f = max(fichiers, key=lambda f: f["width"])
            res.append({"type": "video", "url": f["link"], "source": "Pexels",
                        "credit": f"{v['user']['name']} / Pexels - {v['url']}"})
    d = _get_json("https://api.pexels.com/v1/search?per_page=3&orientation=landscape&query="
                  + urllib.parse.quote(q), h)
    for p in d.get("photos", []):
        res.append({"type": "image", "url": p["src"]["large2x"], "source": "Pexels",
                    "credit": f"{p['photographer']} / Pexels - {p['url']}"})
    return res


def chercher_pixabay(q):
    cle = os.environ.get("PIXABAY_API_KEY")
    if not cle:
        return []
    res = []
    d = _get_json(f"https://pixabay.com/api/videos/?key={cle}&per_page=5&q=" + urllib.parse.quote(q))
    for v in d.get("hits", []):
        f = v["videos"].get("large") or v["videos"].get("medium")
        if f and f.get("url"):
            res.append({"type": "video", "url": f["url"], "source": "Pixabay",
                        "credit": f"{v['user']} / Pixabay - {v['pageURL']}"})
    d = _get_json(f"https://pixabay.com/api/?key={cle}&per_page=3&image_type=photo&q="
                  + urllib.parse.quote(q))
    for p in d.get("hits", []):
        res.append({"type": "image", "url": p["largeImageURL"], "source": "Pixabay",
                    "credit": f"{p['user']} / Pixabay - {p['pageURL']}"})
    return res


def chercher_wikimedia(q):
    """Sans clé. Licences libres mais ATTRIBUTION OBLIGATOIRE (voir CREDITS.json)."""
    url = ("https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrnamespace=6"
           "&gsrlimit=6&prop=imageinfo&iiprop=url|extmetadata|mime&iiurlwidth=1920&format=json"
           "&gsrsearch=" + urllib.parse.quote(q + " filetype:bitmap"))
    d = _get_json(url)
    res = []
    for p in (d.get("query", {}).get("pages", {})).values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime", "").startswith("image/") and ii.get("thumburl"):
            meta = ii.get("extmetadata", {})
            lic = meta.get("LicenseShortName", {}).get("value", "?")
            auteur = re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "?"))
            res.append({"type": "image", "url": ii["thumburl"], "source": "Wikimedia",
                        "credit": f"{auteur} - {lic} - {ii.get('descriptionurl', '')}"})
    return res


SOURCES = (chercher_pexels, chercher_pixabay, chercher_wikimedia)


def chercher(q, cfg, sources=SOURCES):
    """Premier résultat utile : vidéos d'abord (Pexels/Pixabay), puis photos."""
    trouves = []
    for fn in sources:
        try:
            trouves += fn(q)
        except Exception as e:
            print(f"    ! {fn.__name__}: {e}")
    trouves.sort(key=lambda r: r["type"] != "video")
    return trouves


# ------------------------------ téléchargement / clips ------------------------------ #
def telecharger(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        f.write(r.read())


def image_vers_clip(image, sortie, duree, fps, w=1920, h=1080):
    """Photo -> clip vidéo avec léger zoom (effet Ken Burns) de durée exacte."""
    n = max(1, int(round(duree * fps)))
    vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
          f"zoompan=z='min(zoom+0.0007,1.15)':d={n}:s={w}x{h}:fps={fps},format=yuv420p")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(image),
           "-vf", vf, "-frames:v", str(n), "-r", str(fps), "-c:v", "libx264", "-an", str(sortie)]
    subprocess.run(cmd, check=True)
    return sortie


def preparer_illustration(bloc_id, q, duree, dossier, fps, cfg, credits):
    """Cherche + télécharge la 1re illustration valable. Retourne le chemin d'un clip vidéo."""
    for r in chercher(q, cfg):
        try:
            ext = Path(urllib.parse.urlparse(r["url"]).path).suffix or (
                ".mp4" if r["type"] == "video" else ".jpg")
            brut = dossier / f"{bloc_id:03d}_{re.sub(r'[^a-z0-9]+', '-', q.lower())[:30]}{ext}"
            telecharger(r["url"], brut)
            if r["type"] == "image":
                clip = brut.with_suffix(".mp4")
                w, h = cfg.get("resolution_timeline") or (1920, 1080)
                image_vers_clip(brut, clip, duree, fps, w, h)
                brut.unlink(missing_ok=True)
                brut = clip
            credits.append({"fichier": brut.name, "requete": q, **r})
            return brut
        except Exception as e:
            print(f"    ! échec {r['source']} : {e}")
    return None


def planifier_illustrations(analyse, cfg, dossier_out):
    """
    Pour un clip analysé : renvoie [{"src_start", "src_end", "fichier", "requete"}]
    (temps en secondes du clip source), uniquement sur des passages conservés.
    """
    if not analyse["audio"]:
        return []
    dossier_out.mkdir(parents=True, exist_ok=True)
    segs = transcript_clip(analyse, cfg)
    blocs = regrouper(segs, cfg.get("illustration_duree_min_s", 4), cfg.get("illustration_duree_max_s", 9))
    requetes = construire_requetes(blocs, cfg)
    credits_path = dossier_out / "CREDITS.json"
    credits = json.loads(credits_path.read_text("utf-8")) if credits_path.exists() else []
    plan = []
    for i, (b, q) in enumerate(zip(blocs, requetes)):
        if not q:
            continue
        # recadrer dans un passage conservé (les silences coupés n'existent plus au montage)
        seg = next(((s, e) for s, e in analyse["segments"] if s <= b["start"] + 0.01 < e), None)
        if seg is None:
            continue
        deb, fin = max(b["start"], seg[0]), min(b["end"], seg[1])
        if fin - deb < 1.5:
            continue
        print(f"    [{deb:6.1f}s] « {b['text'][:50]} » -> {q}")
        f = preparer_illustration(i, q, fin - deb, dossier_out, analyse["fps"], cfg, credits)
        if f:
            info = next((c for c in reversed(credits) if c["fichier"] == f.name), {})
            plan.append({"src_start": deb, "src_end": fin, "fichier": str(f), "requete": q,
                         "texte": b["text"], "credit": info.get("credit", "")})
    credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=2), "utf-8")
    return plan
