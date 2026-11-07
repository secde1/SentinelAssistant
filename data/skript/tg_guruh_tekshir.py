"""Telegram taklif havolasini JOYLASHSIZ tekshiradi (CheckChatInvite) va dialoglarda borligini ko'radi.
Argument: invite hash. Maxfiy qiymat ish/tg_env.json dan."""
import sys, json, asyncio
from telethon import TelegramClient
from telethon.tl.functions.messages import CheckChatInviteRequest
B = r"D:\it-agent\data\ish"
async def main():
    e = json.load(open(B + r"\tg_env.json", encoding="utf-8-sig"))
    c = TelegramClient(B + r"\tg_session", int(e["api_id"]), e["api_hash"])
    await c.connect()
    if not await c.is_user_authorized():
        print("AUTH YO'Q"); return
    r = await c(CheckChatInviteRequest(sys.argv[1]))
    print("TURI:", type(r).__name__)
    chat = getattr(r, "chat", None)
    print("NOM:", getattr(chat, "title", None) or getattr(r, "title", None))
    print("ID:", getattr(chat, "id", None))
    print("A'ZO:", getattr(r, "participants_count", None) or getattr(chat, "participants_count", None))
    async for d in c.iter_dialogs(limit=50):
        if d.is_group or d.is_channel:
            print("DIALOG", d.id, d.name)
    await c.disconnect()
asyncio.run(main())

