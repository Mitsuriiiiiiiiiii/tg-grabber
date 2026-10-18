import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID   = 35232256
API_HASH = "6c9b7f5467f4d00baef445bee72538b1"
SESSION = "sessions/account_0"
async def main():
    client = TelegramClient(
        SESSION,
        API_ID,
        API_HASH
    )

    try:
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            print("Connexion réussie !")
            print("ID du compte :", me.id)
            print("Nom :", me.first_name)
        else:
            print("Session non authentifiée.")

    except Exception as e:
        print("Erreur :", type(e).__name__, str(e))

    finally:
        await client.disconnect()

asyncio.run(main())
