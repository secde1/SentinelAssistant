"""BTCUSDT SHORT sС†РµРЅР°СЂРёР№ РєСѓР·Р°С‚СѓРІРё: РЅР°СЂС… РґР°СЂР°Р¶Р°Р»Р°СЂРёРіР° С‚РµРіСЃР° Telegram (Saved Messages) РіР° С…Р°Р±Р°СЂ.
ТІР°СЂ 1 РґР°Т›РёТ›Р°РґР° Task Scheduler РёС€РіР° С‚СѓС€РёСЂР°РґРё. РџР°СЂРѕР» Р№СћТ›: api_id/hash/phone ish/tg_env.json РґР°РЅ.
ТІРѕР»Р°С‚: ish/btc_alert_state.json (WAIT -> ENTERED -> CLOSED).
"""
import os, sys, json, time, asyncio, urllib.request

ENTRY, SL, TP1, TP2 = 76600.0, 77500.0, 75250.0, 74400.0
BASE = r"D:\it-agent\data\ish"
STATE = BASE + r"\btc_alert_state.json"
ENV = BASE + r"\tg_env.json"
SESS = BASE + r"\tg_session"
URL = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=%d"

def load():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {"phase": "WAIT", "last_ts": int(time.time() * 1000), "tp1": False, "sent": []}

def save(s):
    json.dump(s, open(STATE, "w"))

def klines(n=30):
    with urllib.request.urlopen(URL % n, timeout=20) as r:
        return json.load(r)

async def send(text):
    from telethon import TelegramClient
    e = json.load(open(ENV, encoding="utf-8-sig"))
    c = TelegramClient(SESS, int(e["api_id"]), e["api_hash"])
    await c.connect()
    try:
        if await c.is_user_authorized():
            await c.send_message("me", text)
            return True
    finally:
        await c.disconnect()
    return False

def main():
    s = load()
    if s["phase"] == "CLOSED":
        return
    ks = [k for k in klines() if k[0] > s["last_ts"] - 60000]
    if not ks:
        return
    msgs = []
    for k in ks:
        hi, lo = float(k[2]), float(k[3])
        if s["phase"] == "WAIT" and hi >= ENTRY:
            s["phase"] = "ENTERED"
            msgs.append("BTC SHORT: РЅР°СЂС… РљРР РРЁ РЅСѓТ›С‚Р°СЃРёРіР° РµС‚РґРё (%.0f). Р›РёРјРёС‚ РѕСЂРґРµСЂ РёС€Р»Р°РґРё, РЅР°СЂС… СЋТ›РѕСЂРё %.0f." % (ENTRY, hi))
        if s["phase"] == "ENTERED":
            if hi >= SL:
                s["phase"] = "CLOSED"
                msgs.append("BTC SHORT: SL %.0f РіР° С‚РµРіРґРё. РџРѕР·РёС†РёСЏ С‘РїРёР»РґРё (Р·Р°СЂР°СЂ)." % SL)
                break
            if lo <= TP2:
                s["phase"] = "CLOSED"
                msgs.append("BTC SHORT: TP2 %.0f РіР° РµС‚РґРё. РЎС†РµРЅР°СЂРёР№ СЏРєСѓРЅР»Р°РЅРґРё (С„РѕР№РґР°)." % TP2)
                break
            if lo <= TP1 and not s["tp1"]:
                s["tp1"] = True
                msgs.append("BTC SHORT: TP1 %.0f РіР° РµС‚РґРё." % TP1)
    s["last_ts"] = int(ks[-1][0])
    if msgs:
        ok = asyncio.run(send("\n".join(msgs)))
        if not ok:
            return  # ТіРѕР»Р°С‚РЅРё СЃР°Т›Р»Р°РјР°Р№РјРёР·: РєРµР№РёРЅРіРё safar Т›Р°Р№С‚Р° СѓСЂРёРЅРёС€
    save(s)

main()
