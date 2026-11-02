"""Suhbat: tg_chat.py read CHAT [N] | tg_chat.py say CHAT MATN
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
    cmd, chat = sys.argv[1], sys.argv[2]
    if cmd == "read":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        for m in reversed(await c.get_messages(chat, limit=n)):
            kind = "voice" if m.voice else ("text" if m.text else "media")
            print(m.id, m.date.strftime("%m-%d %H:%M"), "ME" if m.out else "HE", kind, (m.text or "")[:300])
    elif cmd == "say":
        m = await c.send_message(chat, sys.argv[3])
        print("SENT", m.id)
    await c.disconnect()

asyncio.run(main())
