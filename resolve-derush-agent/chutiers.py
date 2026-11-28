# -*- coding: utf-8 -*-
"""
Chutiers : prépare, AVANT le montage, une bibliothèque rangée de rushs, musiques et SFX.

    Montage vidéo/Chutiers/
        01_RUSHS/      Dialogue/  B-roll/  Son seul/     (liens vers tes rushs : rien n'est déplacé ni dupliqué)
        02_MUSIQUE/    <ambiance>/ ...  Mes pistes/      (musiques libres téléchargées + les tiennes)
        03_SFX/        Whoosh/ Impact/ Clic/ ...  Mes SFX/ (bruitages libres téléchargés + les tiens)
        04_LOGOS/  05_HABILLAGE/  06_SOUS-TITRES/
        INDEX_RUSHS.csv   CREDITS_CHUTIERS.json   LISEZ-MOI.txt

Dans Resolve : page Média, clic droit sur le dossier « Chutiers » > « Ajouter le dossier et les sous-dossiers dans la
bibliothèque de médias (créer des bins) » : chaque sous-dossier devient un bin.

Les rushs sont reliés par des liens physiques (NTFS : pas de copie, pas d'espace disque en plus, aucun droit
administrateur). Si le lien est impossible (autre disque), un petit fichier est copié, sinon il est seulement listé.
"""
import csv
import json
import os
import re
import shutil
from pathlib import Path

import illustrations as ill
import music

EXT_AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

AMBIANCES_DEFAUT = ["calme", "dynamique", "inspirant"]
TRADUCTION = {  # repli sans clé Anthropic : mots français -> tags de recherche anglais
    "calme": "calm ambient", "dynamique": "upbeat energetic", "inspirant": "inspiring cinematic",
    "joyeux": "happy upbeat", "triste": "sad emotional piano", "epique": "epic cinematic", "épique": "epic cinematic",
    "suspense": "suspense dark", "corporate": "corporate background", "chill": "chill lofi", "tendu": "tension dark",
    "romantique": "romantic piano", "drole": "funny quirky", "drôle": "funny quirky", "tech": "technology electronic",
}
SFX_TYPES = {  # dossier -> requête Openverse (en anglais)
    "Whoosh": "whoosh", "Transition": "swoosh transition", "Impact": "impact hit", "Clic et interface": "button click",
    "Notification": "notification chime", "Riser": "riser build up", "Applaudissements": "applause",
    "Ambiance": "room tone ambience",
}


def propre(nom):
    return re.sub(r'[<>:"/\\|?*]+', "_", nom).strip(" .")[:80] or "sans_nom"


# ------------------------------ liens ------------------------------ #
def lier(src, dst, cfg):
    """'lien' (aucune copie), 'copie' (petit fichier) ou 'non lié'."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return "déjà là"
    try:
        os.link(src, dst)
        return "lien"
    except OSError:
        pass
    try:
        if src.stat().st_size <= cfg["chutiers_copie_max_mo"] * 1024 * 1024:
            shutil.copy2(src, dst)
            return "copie"
    except OSError:
        pass
    return "non lié"


def nom_libre(dossier, nom):
    p, i = Path(dossier) / nom, 2
    while p.exists():
        p = Path(dossier) / f"{Path(nom).stem} ({i}){Path(nom).suffix}"
        i += 1
    return p


# ------------------------------ rushs ------------------------------ #
def classer(cats, cfg, analyser):
    """Une fiche par rush : type (Dialogue / B-roll / Son seul), durée, part de parole."""
    fiches = []
    for cat, fichiers in cats.items():
        for f in fichiers:
            a = analyser(f, cfg, derusher=True)
            duree = a["duree_s"] or 0.0
            parole = sum(e - s for s, e in a["segments"]) / duree if duree and a["mode"].startswith("dérushé") else 0.0
            if not a["video"]:
                type_ = "Son seul"
            elif a["audio"] and parole >= cfg["chutiers_seuil_dialogue"]:
                type_ = "Dialogue"
            else:
                type_ = "B-roll"
            fiches.append({"fichier": str(f), "categorie": cat, "type": type_, "duree_s": round(duree, 1),
                           "fps": round(a["fps"], 2), "parole_pct": round(parole * 100), "audio": a["audio"]})
    return fiches


def ranger_rushs(fiches, racine, cfg):
    base = Path(racine) / cfg["dossier_chutiers"] / "01_RUSHS"
    stats = {"lien": 0, "copie": 0, "non lié": 0, "déjà là": 0}
    for fi in fiches:
        dst = nom_libre(base / fi["type"], Path(fi["fichier"]).name)
        r = lier(fi["fichier"], dst, cfg)
        fi["chutier"] = r
        stats[r] = stats.get(r, 0) + 1
    with open(Path(racine) / cfg["dossier_chutiers"] / "INDEX_RUSHS.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Fichier", "Catégorie d'origine", "Type", "Durée (s)", "Parole (%)", "Chutier"])
        for fi in sorted(fiches, key=lambda x: (x["type"], x["fichier"])):
            w.writerow([Path(fi["fichier"]).name, fi["categorie"], fi["type"], fi["duree_s"], fi["parole_pct"],
                        fi["chutier"]])
    return stats


# ------------------------------ musique et SFX ------------------------------ #
def _tags_ambiance(mot, cfg):
    t = mot.strip().lower()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return music.vers_tags(mot, cfg)
    return [x for x in TRADUCTION.get(t, t).split()]


def _openverse(q, categorie, n, duree_max_s=None):
    import urllib.parse
    p = {"q": q, "license_type": "commercial", "page_size": 20, "category": categorie}
    d = ill._get_json("https://api.openverse.org/v1/audio/?" + urllib.parse.urlencode(p))
    out = []
    for t in d.get("results", []):
        dur = (t.get("duration") or 0) / 1000
        if not t.get("url") or (duree_max_s and dur and dur > duree_max_s):
            continue
        lic = f"{t.get('license', '?')} {t.get('license_version', '')}".strip()
        out.append({"titre": t.get("title") or "sans titre", "url": t["url"], "source": "Openverse", "licence": lic,
                    "credit": f"{t.get('title', '?')} - {t.get('creator', '?')} ({lic}) {t.get('foreign_landing_url', '')}"})
        if len(out) >= n:
            break
    return out


def _telecharger(piste, dossier, credits, categorie):
    Path(dossier).mkdir(parents=True, exist_ok=True)
    ext = Path(re.sub(r"[?#].*", "", piste["url"])).suffix.lower()
    ext = ext if ext in EXT_AUDIO else ".mp3"
    dst = nom_libre(dossier, propre(piste["titre"]) + ext)
    ill.telecharger(piste["url"], dst)
    credits.append({"fichier": str(dst.relative_to(dst.parents[2])), "categorie": categorie, **{
        k: piste[k] for k in ("titre", "source", "licence", "credit")}})
    return dst


def remplir_musique(racine, cfg, ambiances, credits):
    base = Path(racine) / cfg["dossier_chutiers"] / "02_MUSIQUE"
    n_tot = 0
    for amb in ambiances:
        tags = _tags_ambiance(amb, cfg)
        trouvees = []
        for fn, nom in ((music.chercher_jamendo, "Jamendo"), (lambda t: _openverse(" ".join(t[:3]), "music", 5), "Openverse")):
            try:
                trouvees += fn(tags)
            except Exception as e:
                print(f"    ! {nom} : {e}")
            if len(trouvees) >= cfg["chutiers_musiques_par_ambiance"]:
                break
        for p in trouvees[:cfg["chutiers_musiques_par_ambiance"]]:
            try:
                _telecharger(p, base / propre(amb.capitalize()), credits, "musique")
                n_tot += 1
            except Exception as e:
                print(f"    ! téléchargement impossible ({p['titre'][:30]}) : {e}")
        print(f"  Musique « {amb} » : {min(len(trouvees), cfg['chutiers_musiques_par_ambiance'])} piste(s)")
    return n_tot


def remplir_sfx(racine, cfg, credits):
    base = Path(racine) / cfg["dossier_chutiers"] / "03_SFX"
    n_tot = 0
    for dossier, requete in cfg["chutiers_sfx_types"].items():
        try:
            res = _openverse(requete, "sound_effect", cfg["chutiers_sfx_par_type"], duree_max_s=12)
        except Exception as e:
            print(f"    ! SFX « {dossier} » : {e}")
            continue
        for p in res:
            try:
                _telecharger(p, base / propre(dossier), credits, "sfx")
                n_tot += 1
            except Exception as e:
                print(f"    ! téléchargement impossible ({p['titre'][:30]}) : {e}")
        print(f"  SFX « {dossier} » : {len(res)} son(s)")
    return n_tot


def lier_fichiers_perso(racine, cfg):
    """Tes propres musiques / SFX / logos : reliés (sans copie) dans le chutier."""
    base = Path(racine) / cfg["dossier_chutiers"]
    n = 0
    for dossier_src, dest in ((cfg["musique_dossier"], "02_MUSIQUE/Mes pistes"), ("SFX", "03_SFX/Mes SFX"),
                              (cfg["dossier_logos"], "04_LOGOS"), (cfg["dossier_habillage"], "05_HABILLAGE")):
        src = Path(racine) / dossier_src
        if not src.is_dir():
            continue
        for f in src.rglob("*"):
            if f.is_file() and "_rendus" not in f.parts and f.name != "CREDITS_MUSIQUE.json" and f.suffix.lower() in (
                    EXT_AUDIO | {".png", ".webp", ".jpg", ".jpeg", ".svg", ".mov", ".mp4"}):
                if lier(f, nom_libre(base / dest, f.name), cfg) != "non lié":
                    n += 1
    return n


# ------------------------------ point d'entrée ------------------------------ #
def construire(racine, cats, cfg, analyser, ambiances=None):
    racine = Path(racine)
    base = racine / cfg["dossier_chutiers"]
    for d in ("01_RUSHS", "02_MUSIQUE", "03_SFX", "04_LOGOS", "05_HABILLAGE", "06_SOUS-TITRES"):
        (base / d).mkdir(parents=True, exist_ok=True)
    print(f"Chutiers : {base}")

    print("Rushs : classement (dialogue / B-roll / son seul)...")
    fiches = classer(cats, cfg, analyser)
    stats = ranger_rushs(fiches, racine, cfg)
    par_type = {}
    for fi in fiches:
        par_type[fi["type"]] = par_type.get(fi["type"], 0) + 1
    print("  " + ", ".join(f"{k} : {v}" for k, v in par_type.items()) + f"  | liens : {stats['lien']}, copies : "
          f"{stats['copie']}, non liés : {stats['non lié']}")
    if stats["non lié"]:
        print("  ! certains rushs sont sur un autre disque : ils sont listés dans INDEX_RUSHS.csv mais non reliés "
              "(importe-les depuis leur dossier d'origine).")

    credits = []
    n_perso = lier_fichiers_perso(racine, cfg)
    print(f"Tes propres fichiers (musique, SFX, logos) : {n_perso} reliés")
    if cfg.get("chutiers_internet", True):
        print("Musique et SFX libres : recherche en ligne (seuls des mots-clés sont envoyés, jamais ton dialogue)...")
        amb = ambiances or cfg.get("chutiers_ambiances") or AMBIANCES_DEFAUT
        remplir_musique(racine, cfg, amb, credits)
        remplir_sfx(racine, cfg, credits)
        (base / "CREDITS_CHUTIERS.json").write_text(json.dumps(credits, ensure_ascii=False, indent=2), "utf-8")
    (base / "LISEZ-MOI.txt").write_text(
        "CHUTIERS\n\n"
        "Dans DaVinci Resolve : page Média, clic droit sur le dossier « Chutiers » dans l'explorateur de médias,\n"
        "puis « Ajouter le dossier et les sous-dossiers dans la bibliothèque de médias (créer des bins) ».\n"
        "(le libellé exact peut varier selon la version)\n\n"
        "- 01_RUSHS : tes rushs classés (liens : rien n'est déplacé ni dupliqué). Voir INDEX_RUSHS.csv.\n"
        "- 02_MUSIQUE / 03_SFX : sons libres téléchargés + les tiens. Les crédits sont dans CREDITS_CHUTIERS.json :\n"
        "  de nombreuses licences (CC BY) exigent de citer l'auteur. Vérifie chaque licence avant publication.\n"
        "- Ne supprime pas tes rushs d'origine : les liens pointent vers les mêmes données.\n", encoding="utf-8")
    print(f"\nChutiers prêts : {base}")
    return fiches
