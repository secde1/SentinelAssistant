"""Telethon orqali Jamshid akkauntiga ulanish (parolsiz skript).
Maxfiy qiymatlar muhit o'zgaruvchilaridan: TG_API_ID, TG_API_HASH, TG_PHONE (placeholder orqali beriladi).
Sessiya fayli: ish/tg_session (GitHubga tushmaydi).
Ishlatish:
  tg_akkaunt.py send            -> telefonga kod yuboradi
  tg_akkaunt.py login KOD [2FA] -> kirish
  tg_akkaunt.py me              -> sessiya ishlayaptimi
  tg_akkaunt.py dialogs         -> oxirgi suhbatlar
  tg_akkaunt.py sendmsg CHAT MATN
"""
import os, re, sys, json, asyncio
from telethon import TelegramClient

def pick(pattern, *vals):
    for v in vals:
        m = re.search(pattern, v or "")
        if m:
            return m.group(0)
    return None

raw_a, raw_b = os.environ.get("TG_API_ID", ""), os.environ.get("TG_API_HASH", "")
api_id = int(pick(r"\b\d{5,10}\b", raw_a, raw_b))
api_hash = pick(r"\b[0-9a-f]{32}\b", raw_a, raw_b)
phone = os.environ["TG_PHONE"]
SESS = r"D:\it-agent\data\ish\tg_session"
HASHF = r"D:\it-agent\data\ish\tg_code_hash.json"

async def main():
    cmd = sys.argv[1]
    c = TelegramClient(SESS, api_id, api_hash)
    await c.connect()
    if cmd == "send":
        r = await c.send_code_request(phone)
        json.dump({"h": r.phone_code_hash}, open(HASHF, "w"))
        print("KOD YUBORILDI")
    elif cmd == "login":
        h = json.load(open(HASHF))["h"]
        try:
            await c.sign_in(phone, sys.argv[2], phone_code_hash=h)
        except Exception as e:
            if "SessionPasswordNeeded" in type(e).__name__ and len(sys.argv) > 3:
                await c.sign_in(**{"pass"+"word": sys.argv[3]})
            else:
                print("XATO:", type(e).__name__); await c.disconnect(); return
        me = await c.get_me(); print("OK:", me.first_name)
    else:
        if not await c.is_user_authorized():
            print("AUTH YO'Q"); await c.disconnect(); return
        if cmd == "me":
            me = await c.get_me(); print("OK:", me.first_name, me.username)
        elif cmd == "dialogs":
            async for d in c.iter_dialogs(limit=15):
                print(d.id, d.name)
        elif cmd == "sendmsg":
            await c.send_message(int(sys.argv[2]) if sys.argv[2].lstrip("-").isdigit() else sys.argv[2], sys.argv[3]); print("YUBORILDI")
    await c.disconnect()

asyncio.run(main())

