"""Oxirgi xabarni o'qish (faqat o'qish): tg_last.py CHAT
Maxfiy qiymatlar muhitdan: TG_API_ID, TG_API_HASH."""
import os, re, sys, asyncio
from telethon import TelegramClient

def pick(p, *v):
    for x in v:
        m = re.search(p, x or "")
        if m:
            return m.group(0)

a, b = os.environ.get("TG_API_ID", ""), os.environ.get("TG_API_HASH", "")

async def main():
    c = TelegramClient(r"D:\it-agent\data\ish\tg_session", int(pick(r"\b\d{5,10}\b", a, b)), pick(r"\b[0-9a-f]{32}\b", a, b))
    await c.connect()
    m = (await c.get_messages(sys.argv[1], limit=1))[0]
    print("id", m.id, "out", m.out, "voice", bool(m.voice))
    await c.disconnect()

asyncio.run(main())
