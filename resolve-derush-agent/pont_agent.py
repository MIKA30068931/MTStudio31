# -*- coding: utf-8 -*-
"""
Pont local entre l'interface web (Base44) et l'agent monteur.

    py -3 pont_agent.py

Il écoute UNIQUEMENT sur ton ordinateur (127.0.0.1), n'exécute que des actions de la liste ci-dessous (jamais de
commande libre), exige un code secret et n'accepte que les pages autorisées (base44.app par défaut).
Sans dépendance : bibliothèque standard de Python.
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ICI = Path(__file__).resolve().parent
AGENT = ICI / "derush_agent.py"
CONFIG = Path.home() / ".pont_agent.json"
HISTORIQUE = Path.home() / ".pont_agent_historique.json"
VERSION = "1.0"

# action -> (libellé, arguments de base passés à l'agent)
ACTIONS = {
    "montage_complet": ("Montage complet", ["--tout", "--export"]),
    "silences": ("Silences", ["--export"]),
    "nettoyage": ("Hésitations et répétitions", ["--export", "--nettoyer"]),
    "sous_titres": ("Sous-titres", ["--export", "--sous-titres"]),
    "habillage": ("Bandeaux et titres", ["--export", "--habillage"]),
    "logos": ("Logos animés", ["--export", "--logos"]),
    "musique": ("Musique", ["--export", "--musique"]),
    "illustrations": ("Illustrations", ["--export", "--illustrations"]),
    "broll": ("B-roll adapté au dialogue", ["--export", "--broll"]),
    "chutiers": ("Chutiers", ["--chutiers"]),
    "analyse": ("Analyse seule", ["--analyse-seule"]),
}
RE_TEXTE = re.compile(r"^[\w ,'’-]{1,80}$", re.UNICODE)
ORIGINES_OK = re.compile(r"^https://([A-Za-z0-9-]+\.)+base44\.(app|com)$|^http://(localhost|127\.0\.0\.1)(:\d+)?$")

JOBS = {}          # id -> dict
ORDRE = []         # ids, du plus ancien au plus récent
VERROU = threading.Lock()
FILE = []          # ids en attente
COURANT = {"id": None, "proc": None}
CFG = {}


# ------------------------------ configuration et sécurité ------------------------------ #
def charger_config(origines_extra):
    cfg = {}
    try:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(24)
    cfg["origines"] = sorted(set(cfg.get("origines", [])) | set(origines_extra))
    try:
        CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(CONFIG, 0o600)
    except OSError:
        pass
    return cfg


def origine_autorisee(origine):
    return bool(origine) and (bool(ORIGINES_OK.match(origine)) or origine in CFG.get("origines", []))


# ------------------------------ validation des demandes ------------------------------ #
def construire_arguments(demande):
    """Transforme une demande JSON en liste d'arguments, après validation stricte. Lève ValueError sinon."""
    action = demande.get("action")
    if action not in ACTIONS:
        raise ValueError("action inconnue")
    dossier = Path(str(demande.get("dossier", ""))).expanduser()
    if not str(demande.get("dossier", "")).strip() or not dossier.is_dir():
        raise ValueError("dossier introuvable")
    args = [str(dossier.resolve())] + list(ACTIONS[action][1])
    opt = demande.get("options") or {}

    if action == "musique":
        amb = str(opt.get("ambiance", "auto")).strip() or "auto"
        if not RE_TEXTE.match(amb):
            raise ValueError("ambiance invalide")
        args.append(amb)
    if action == "chutiers":
        amb = str(opt.get("ambiances", "")).strip()
        if amb:
            if not RE_TEXTE.match(amb):
                raise ValueError("ambiances invalides")
            args += ["--ambiances", amb]
        if opt.get("hors_ligne"):
            args.append("--hors-ligne")
    if action != "chutiers":
        fmt = opt.get("format", "16:9")
        res = opt.get("resolution", "1080p")
        if fmt not in ("16:9", "9:16") or res not in ("1080p", "4k"):
            raise ValueError("format ou qualité invalide")
        args += ["--format", fmt, "--resolution", res, "--sans-questions"]
        seuil = str(opt.get("seuil", "auto")).strip().lower().replace(",", ".")
        if seuil != "auto":
            try:
                v = float(seuil)
            except ValueError:
                raise ValueError("seuil invalide")
            if not -80 <= v <= -10:
                raise ValueError("seuil hors limites (-80 à -10)")
            args += ["--seuil", str(v)]
        if str(opt.get("silence_min", "")).strip():
            try:
                v = float(str(opt["silence_min"]).replace(",", "."))
            except ValueError:
                raise ValueError("durée de silence invalide")
            if not 0.1 <= v <= 3:
                raise ValueError("durée de silence hors limites (0,1 à 3)")
            args += ["--silence-min", str(v)]
        # options d'ajout, valables sur les actions de montage (pas sur l'analyse)
        if action in ("silences",):
            for cle, flag in (("nettoyer", "--nettoyer"), ("sous_titres", "--sous-titres"),
                              ("habillage", "--habillage"), ("logos", "--logos"), ("illustrations", "--illustrations")):
                if opt.get(cle):
                    args.append(flag)
    return action, args


# ------------------------------ exécution ------------------------------ #
def resume(j):
    return {k: j[k] for k in ("id", "action", "libelle", "dossier", "statut", "debut", "fin", "resultat", "code")}


def sauver_historique():
    try:
        data = [dict(resume(JOBS[i]), log=JOBS[i]["log"][-200:]) for i in ORDRE[-50:]]
        HISTORIQUE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def charger_historique():
    try:
        for j in json.loads(HISTORIQUE.read_text(encoding="utf-8")):
            if j.get("statut") in ("en_attente", "en_cours"):
                j["statut"] = "interrompu"
            JOBS[j["id"]] = j
            ORDRE.append(j["id"])
    except (OSError, ValueError, KeyError):
        pass


def lancer_job(j):
    cmd = [sys.executable, "-u", str(AGENT)] + j["args"]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    drapeaux = 0x08000000 if os.name == "nt" else 0  # pas de fenêtre noire
    j["statut"], j["debut"] = "en_cours", time.time()
    try:
        p = subprocess.Popen(cmd, cwd=str(ICI), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace", env=env, creationflags=drapeaux)
    except OSError as e:
        j["log"].append(f"Impossible de lancer l'agent : {e}")
        j["statut"], j["fin"], j["code"] = "erreur", time.time(), -1
        return
    COURANT["proc"] = p
    for ligne in p.stdout:
        ligne = ligne.rstrip("\n")
        j["log"].append(ligne)
        m = re.search(r"Fichier créé : (.+)$", ligne)
        if m:
            j["resultat"] = m.group(1).strip()
        elif ligne.startswith("Chutiers prêts : "):
            j["resultat"] = ligne.split(": ", 1)[1].strip()
    p.wait()
    j["code"], j["fin"] = p.returncode, time.time()
    if j["statut"] != "arrete":
        j["statut"] = "termine" if p.returncode == 0 else "erreur"


def boucle_file():
    while True:
        with VERROU:
            jid = FILE.pop(0) if FILE else None
        if jid is None:
            time.sleep(0.3)
            continue
        j = JOBS[jid]
        if j["statut"] == "arrete":  # annulé avant de démarrer
            continue
        COURANT["id"] = jid
        try:
            lancer_job(j)
        finally:
            COURANT["id"], COURANT["proc"] = None, None
            sauver_historique()


def ouvrir_dossier(chemin):
    chemin = str(chemin)
    if sys.platform.startswith("win"):
        os.startfile(chemin)  # noqa: S606 - chemin choisi par l'utilisateur et validé
    elif sys.platform == "darwin":
        subprocess.Popen(["open", chemin])
    else:
        subprocess.Popen(["xdg-open", chemin])


def choisir_dossier_pc():
    """Ouvre la fenêtre de choix de dossier de Windows sur le PC ; retourne le chemin ou ''."""
    code = ("import tkinter as tk\nfrom tkinter import filedialog\nr=tk.Tk()\nr.withdraw()\n"
            "r.attributes('-topmost', True)\n"
            "print(filedialog.askdirectory(title='Choisir le dossier Montage vidéo'))\n")
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
        return r.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


# ------------------------------ serveur HTTP ------------------------------ #
class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "PontAgent/" + VERSION

    def log_message(self, *a):  # silence
        pass

    def _entetes_cors(self):
        o = self.headers.get("Origin")
        if origine_autorisee(o):
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")

    def _json(self, code, obj):
        corps = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._entetes_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _hote_ok(self):  # protège contre le « DNS rebinding »
        h = (self.headers.get("Host") or "").split(":")[0].lower()
        return h in ("127.0.0.1", "localhost")

    def _autorise(self):
        o = self.headers.get("Origin")
        if o and not origine_autorisee(o):
            return False
        jeton = (self.headers.get("Authorization") or "").removeprefix("Bearer ").strip()
        return secrets.compare_digest(jeton, CFG["token"])

    def do_OPTIONS(self):
        if not self._hote_ok():
            return self._json(403, {"erreur": "hôte refusé"})
        self.send_response(204)
        self._entetes_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20000:
            raise ValueError("demande trop grande")
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}") if n else {}

    def do_GET(self):
        self._traiter("GET")

    def do_POST(self):
        self._traiter("POST")

    def _traiter(self, methode):
        if not self._hote_ok():
            return self._json(403, {"erreur": "hôte refusé"})
        url = urlparse(self.path)
        chemin, q = url.path.rstrip("/"), parse_qs(url.query)
        if chemin == "/api/health" and methode == "GET" and not self.headers.get("Authorization"):
            return self._json(200, {"ok": True, "pont": VERSION, "authentification": "requise"})
        if not self._autorise():
            return self._json(401, {"erreur": "code secret manquant ou incorrect"})
        try:
            if chemin == "/api/health" and methode == "GET":
                return self._json(200, {"ok": True, "pont": VERSION, "agent": AGENT.exists(), "en_cours": COURANT["id"],
                                        "actions": {k: v[0] for k, v in ACTIONS.items()}})
            if chemin == "/api/jobs" and methode == "GET":
                with VERROU:
                    return self._json(200, {"jobs": [resume(JOBS[i]) for i in reversed(ORDRE[-30:])]})
            if chemin == "/api/jobs" and methode == "POST":
                action, args = construire_arguments(self._corps())
                jid = uuid.uuid4().hex[:10]
                j = {"id": jid, "action": action, "libelle": ACTIONS[action][0], "args": args, "dossier": args[0],
                     "statut": "en_attente", "debut": None, "fin": None, "resultat": None, "code": None, "log": []}
                with VERROU:
                    JOBS[jid] = j
                    ORDRE.append(jid)
                    FILE.append(jid)
                return self._json(202, resume(j))
            m = re.fullmatch(r"/api/jobs/([0-9a-f]{10})(/arreter|/ouvrir)?", chemin)
            if m and m.group(1) in JOBS:
                j = JOBS[m.group(1)]
                if m.group(2) is None and methode == "GET":
                    depuis = max(0, int((q.get("depuis") or ["0"])[0]))
                    return self._json(200, dict(resume(j), log=j["log"][depuis:], total_lignes=len(j["log"])))
                if m.group(2) == "/arreter" and methode == "POST":
                    if j["statut"] == "en_attente":
                        j["statut"] = "arrete"
                    elif j["statut"] == "en_cours" and COURANT["proc"] is not None and COURANT["id"] == j["id"]:
                        j["statut"] = "arrete"
                        COURANT["proc"].terminate()
                    return self._json(200, resume(j))
                if m.group(2) == "/ouvrir" and methode == "POST":
                    cible = Path(j["dossier"]) / ("Chutiers" if j["action"] == "chutiers" else "Export Resolve")
                    if not cible.is_dir():
                        cible = Path(j["dossier"])
                    ouvrir_dossier(cible)
                    return self._json(200, {"ouvert": str(cible)})
            if chemin == "/api/choisir-dossier" and methode == "POST":
                return self._json(200, {"dossier": choisir_dossier_pc()})
            return self._json(404, {"erreur": "inconnu"})
        except ValueError as e:
            return self._json(400, {"erreur": str(e)})
        except Exception as e:  # ne jamais planter le pont
            return self._json(500, {"erreur": f"{type(e).__name__}: {e}"})


def main():
    global CFG
    ap = argparse.ArgumentParser(description="Pont local entre l'interface web et l'agent monteur")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--origine", action="append", default=[],
                    help="Adresse de ta page à autoriser en plus de *.base44.app (ex. https://monsite.exemple)")
    a = ap.parse_args()
    if not AGENT.exists():
        sys.exit(f"derush_agent.py introuvable à côté de ce fichier : {AGENT}")
    CFG = charger_config(a.origine)
    charger_historique()
    threading.Thread(target=boucle_file, daemon=True).start()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", a.port), Gestionnaire)
    except OSError as e:
        sys.exit(f"Impossible d'ouvrir le port {a.port} ({e}). Est-ce que le pont est déjà lancé ?")
    print("=" * 60)
    print(" Pont de l'agent monteur - en écoute sur cet ordinateur")
    print(f" Adresse : http://127.0.0.1:{a.port}")
    print(f" Code secret : {CFG['token']}")
    print(" Colle ce code dans l'interface (onglet Connexion).")
    print(" Laisse cette fenêtre ouverte. Ctrl+C pour arrêter.")
    print("=" * 60)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt du pont.")


if __name__ == "__main__":
    main()
