# -*- coding: utf-8 -*-
"""
Habillage graphique de l'agent : bandeaux de nom (lower thirds) et titres de sections.

Chaque graphique est rendu par ffmpeg en petit clip animé AVEC TRANSPARENCE (.mov ProRes 4444),
puis posé sur la piste V3 au bon moment. Avantage : rendu identique partout, aucune dépendance
aux titres de Resolve. Inconvénient : le texte n'est pas modifiable dans Resolve (on corrige
`habillage.json` et on relance).

Les noms viennent de `habillage.json` (créé automatiquement, à remplir) : l'agent n'affiche JAMAIS
un nom deviné. Les suggestions éventuelles (via Claude) restent dans un champ `_suggestion`.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import subtitles as st

POLICES = [  # première trouvée = utilisée (sinon "habillage_police" dans config.json)
    "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


# ------------------------------ rendu ffmpeg ------------------------------ #
def _echapper(chemin):
    """Chemin pour un filtre ffmpeg (antislash, ':' de 'C:' et apostrophes)."""
    return str(chemin).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def trouver_police(cfg):
    for p in ([cfg.get("habillage_police")] if cfg.get("habillage_police") else []) + POLICES:
        if p and Path(p).exists():
            return p
    raise RuntimeError("Aucune police trouvée : indique un fichier .ttf dans config.json "
                       "(\"habillage_police\").")


def _hex(c):
    return "0x" + c.lstrip("#")


def resolution(analyses, cfg):
    if cfg.get("habillage_resolution"):
        return tuple(cfg["habillage_resolution"])
    for liste in analyses.values():
        for a in liste:
            if a["video"]:
                r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=width,height", "-of", "csv=p=0:s=x", a["fichier"]],
                                   capture_output=True, text=True).stdout.strip()
                if "x" in r:
                    w, h = r.split("x")[:2]
                    return int(w), int(h)
    return 1920, 1080


def _ffmpeg(args):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg (habillage) : " + r.stderr.strip()[-400:])


def _texte(dossier, nom, contenu):
    f = Path(dossier) / nom
    f.write_text(contenu, encoding="utf-8")
    return f


def rendre_bandeau(nom, fonction, n_images, fps, sortie, res, cfg):
    """Bandeau qui glisse depuis la gauche, reste, puis ressort."""
    W, H = res
    D = n_images / fps
    tin, tout = 0.5, 0.4
    bh = int(H * (0.115 if fonction else 0.08))
    t_nom0, t_fct0 = int(bh * (0.38 if fonction else 0.5)), int(bh * 0.26)
    largeur_texte = max(len(nom) * t_nom0, len(fonction or "") * t_fct0) * 0.62  # estimation police grasse
    bw = min(int(W * 0.85), max(int(W * 0.34), int(largeur_texte + W * 0.04)))
    x1, x0, y = int(W * 0.06), -bw, int(H * 0.78)
    pol = _echapper(trouver_police(cfg))
    accent, fond = _hex(cfg["habillage_couleur_accent"]), _hex(cfg["habillage_couleur_fond"])
    t_nom = int(bh * (0.38 if fonction else 0.5))
    t_fct = int(bh * 0.26)
    with tempfile.TemporaryDirectory() as tmp:
        fn = _echapper(_texte(tmp, "nom.txt", nom))
        ff = _echapper(_texte(tmp, "fct.txt", fonction or ""))
        barre = (f"color=c={fond}@0.88:s={bw}x{bh}:r={fps}:d={D:.3f},format=rgba,"
                 f"drawbox=x=0:y=0:w={max(6, W // 190)}:h={bh}:color={accent}@1:t=fill,"
                 f"drawtext=fontfile='{pol}':textfile='{fn}':fontcolor=white:fontsize={t_nom}:"
                 f"x={int(bw * 0.07)}:y={int(bh * (0.14 if fonction else 0.5))}"
                 f"{'' if fonction else '-th/2'}")
        if fonction:
            barre += (f",drawtext=fontfile='{pol}':textfile='{ff}':fontcolor={accent}:"
                      f"fontsize={t_fct}:x={int(bw * 0.07)}:y={int(bh * 0.60)}")
        xe = (f"if(lt(t,{tin}),{x0}+({x1}-{x0})*(1-pow(1-t/{tin},3)),"
              f"if(gt(t,{D:.3f}-{tout}),{x1}+({x0}-{x1})*pow((t-({D:.3f}-{tout}))/{tout},3),{x1}))")
        fc = (f"color=c=black@0:s={W}x{H}:r={fps}:d={D:.3f},format=rgba[c];"
              f"{barre}[b];[c][b]overlay=x='{xe}':y={y}:format=auto,format=yuva444p10le[out]")
        _ffmpeg(["-filter_complex", fc, "-map", "[out]", "-frames:v", str(n_images),
                 "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(sortie)])


def rendre_titre_section(texte, n_images, fps, sortie, res, cfg):
    """Titre centré sur bandeau sombre : fondu, léger glissement vers le haut, trait d'accent."""
    W, H = res
    D = n_images / fps
    fade = 0.45
    bh = int(H * 0.22)
    pol = _echapper(trouver_police(cfg))
    accent, fond = _hex(cfg["habillage_couleur_accent"]), _hex(cfg["habillage_couleur_fond"])
    taille = int(H * 0.085)
    with tempfile.TemporaryDirectory() as tmp:
        ft = _echapper(_texte(tmp, "titre.txt", texte))
        al = f"if(lt(t,{fade}),t/{fade},if(gt(t,{D:.3f}-{fade}),({D:.3f}-t)/{fade},1))"
        yt = f"(h-th)/2-{int(H * 0.012)}+{int(H * 0.04)}*pow(1-min(t/0.7,1),3)"
        bande = (f"color=c={fond}@0.80:s={W}x{bh}:r={fps}:d={D:.3f},format=rgba,"
                 f"fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={D - fade:.3f}:d={fade}:alpha=1")
        trait = (f"color=c={accent}@1:s={int(W * 0.12)}x{max(4, H // 270)}:r={fps}:d={D:.3f},format=rgba,"
                 f"fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={D - fade:.3f}:d={fade}:alpha=1")
        fc = (f"color=c=black@0:s={W}x{H}:r={fps}:d={D:.3f},format=rgba[c];{bande}[b];{trait}[l];"
              f"[c][b]overlay=x=0:y={(H - bh) // 2}:format=auto[c2];"
              f"[c2][l]overlay=x=(W-w)/2:y={(H + bh) // 2 - int(H * 0.045)}:format=auto,"
              f"drawtext=fontfile='{pol}':textfile='{ft}':fontcolor=white:fontsize={taille}:"
              f"x=(w-tw)/2:y='{yt}':alpha='{al}',format=yuva444p10le[out]")
        _ffmpeg(["-filter_complex", fc, "-map", "[out]", "-frames:v", str(n_images),
                 "-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", str(sortie)])


# ------------------------------ habillage.json ------------------------------ #
def _cle(cat, a):
    return f"{cat}/{Path(a['fichier']).stem}"


def suggerer(a, cfg):
    """Nom/fonction DITS dans les 40 premières secondes (Claude si clé). Jamais utilisé tel quel."""
    if not os.environ.get("ANTHROPIC_API_KEY") or not a.get("transcript"):
        return ""
    texte = " ".join(s["text"] for s in a["transcript"] if s["start"] < 40)
    if not texte.strip():
        return ""
    try:
        import anthropic
        m = anthropic.Anthropic().messages.create(
            model=cfg.get("modele_claude", "claude-haiku-5-5"), max_tokens=80,
            messages=[{"role": "user", "content":
                "Début d'une interview :\n" + texte[:1500] + "\n\nSi la personne dit CLAIREMENT son nom et "
                "sa fonction, réponds « Nom - Fonction », sinon réponds exactement : rien."}])
        r = m.content[0].text.strip()
        return "" if r.lower().startswith("rien") else r
    except Exception:
        return ""


def charger(racine, analyses, categories, cfg):
    """Lit habillage.json ; le crée (à remplir) s'il n'existe pas ou s'il manque des clips."""
    chemin = Path(racine) / "habillage.json"
    data = json.loads(chemin.read_text("utf-8")) if chemin.exists() else {}
    data.setdefault("_aide", "Remplis 'nom' et 'fonction' pour afficher un bandeau ; laisse 'nom' vide pour "
                             "ne rien afficher. 'sections' : titre affiché au début de chaque catégorie "
                             "(vide = pas de titre).")
    inter = data.setdefault("intervenants", {})
    sections = data.setdefault("sections", {})
    nouveau = False
    for cat in categories:
        if cat not in sections:
            sections[cat] = cat.replace("_", " ").replace("-", " ").strip().capitalize()
            nouveau = True
        for a in analyses[cat]:
            if a["audio"] and _cle(cat, a) not in inter:
                inter[_cle(cat, a)] = {"nom": "", "fonction": "", "_suggestion": suggerer(a, cfg)}
                nouveau = True
    if nouveau or not chemin.exists():
        chemin.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    return data, chemin


# ------------------------------ plan + rendu ------------------------------ #
def generer(analyses, categories, cfg, racine):
    """
    Retourne {"<cat>": [...], "__global__": [...]} ; chaque élément :
    {"fichier", "rec_frame", "n", "type", "texte"} (rec_frame = images depuis le début de la timeline).
    """
    data, chemin_json = charger(racine, analyses, categories, cfg)
    fps = st.fps_timeline(analyses, cfg)
    res = resolution(analyses, cfg)
    dossier = Path(racine) / cfg["dossier_habillage"]
    dossier.mkdir(parents=True, exist_ok=True)
    cache = {}

    def clip(type_, texte, fonction, n):
        h = hashlib.md5(json.dumps([type_, texte, fonction, n, fps, res, cfg["habillage_couleur_accent"],
                                    cfg["habillage_couleur_fond"]]).encode()).hexdigest()[:10]
        f = dossier / f"{type_}_{re.sub(r'[^A-Za-z0-9]+', '-', texte)[:24]}_{h}.mov"
        if f not in cache and not f.exists():
            if type_ == "bandeau":
                rendre_bandeau(texte, fonction, n, fps, f, res, cfg)
            else:
                rendre_titre_section(texte, n, fps, f, res, cfg)
        cache[f] = True
        return str(f)

    def planifier(cats_incluses):
        """Éléments d'une timeline faite des catégories données, bout à bout."""
        items, pos = [], 0
        for cat in cats_incluses:
            debut_cat, fin_titre = pos, 0
            titre = sections_txt(cat)
            if titre:
                n = int(round(cfg["habillage_duree_titre_s"] * fps))
                rec = debut_cat + int(round(0.3 * fps))
                items.append({"fichier": clip("titre", titre, "", n), "rec_frame": rec, "n": n,
                              "type": "titre", "texte": titre})
                fin_titre = rec + n
            for a in analyses[cat]:
                pas, pos_fin = st.passages(a, fps, pos)
                inter = data["intervenants"].get(_cle(cat, a), {})
                nom = (inter.get("nom") or "").strip()
                if nom and pas and cat in categories:
                    place = False
                    for s_, e_, ds, p, nseg in pas:  # 1er passage où le bandeau tient (>= 2 s)
                        rec = p + int(round(cfg["habillage_delai_bandeau_s"] * fps))
                        if fin_titre > p:  # ne pas chevaucher le titre de section (même piste V3)
                            rec = max(rec, fin_titre + int(round(0.3 * fps)))
                        n = min(int(round(cfg["habillage_duree_bandeau_s"] * fps)), p + nseg - rec)
                        if n >= int(round(2 * fps)):
                            fct = (inter.get("fonction") or "").strip()
                            items.append({"fichier": clip("bandeau", nom, fct, n), "rec_frame": rec,
                                          "n": n, "type": "bandeau",
                                          "texte": nom + (f" - {fct}" if fct else "")})
                            place = True
                            break
                    if not place:
                        print(f"  ! bandeau « {nom} » ignoré : aucun passage assez long dans ce clip")
                pos = pos_fin
        return items

    def sections_txt(cat):
        return (data["sections"].get(cat) or "").strip() if cat in categories else ""

    plan = {}
    for cat in categories:
        plan[cat] = planifier([cat])
    # timeline globale : toutes les catégories, dans l'ordre (les non-dérushées font seulement avancer)
    plan["__global__"] = planifier(list(analyses.keys()))
    nb = sum(1 for i in plan["__global__"] if i["type"] == "bandeau")
    nt = sum(1 for i in plan["__global__"] if i["type"] == "titre")
    print(f"  Habillage : {nt} titre(s) de section, {nb} bandeau(x) de nom -> {dossier.name}/")
    sans_nom = [k for k, v in data["intervenants"].items() if not (v.get("nom") or "").strip()]
    if sans_nom:
        print(f"  {len(sans_nom)} intervenant(s) sans nom : remplis {chemin_json.name} puis relance "
              "pour afficher leurs bandeaux")
    return plan
