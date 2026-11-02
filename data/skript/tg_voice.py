"""Telethon orqali ovozli xabar yuborish: tg_voice.py CHAT FAYL.ogg
Maxfiy qiymatlar muhitdan: TG_API_ID, TG_API_HASH, TG_PHONE."""
import os, re, sys, asyncio
from telethon import TelegramClient

def pick(p, *v):
    for x in v:
        m = re.search(p, x or "")
        if m:
            return m.group(0)

a, b = os.environ.get("TG_API_ID", ""), os.environ.get("TG_API_HASH", "")
api_id = int(pick(r"\b\d{5,10}\b", a, b))
api_hash = pick(r"\b[0-9a-f]{32}\b", a, b)

async def main():
    c = TelegramClient(r"D:\it-agent\data\ish\tg_session", api_id, api_hash)
    await c.connect()
    if not await c.is_user_authorized():
        print("AUTH YO'Q"); return
    ent = await c.get_entity(sys.argv[1])
    print("KIMGA:", getattr(ent, "first_name", ""), getattr(ent, "last_name", ""), getattr(ent, "username", ""))
    m = await c.send_file(ent, sys.argv[2], voice_note=True)
    print("YUBORILDI id=", m.id)
    await c.disconnect()

asyncio.run(main())
