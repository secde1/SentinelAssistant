"""Avto-skaner: 10 kripto, 4h+1h trend + 15m kirish. Kuchli signal (score>=MIN_SCORE) topilsa
Jamshidga Telegram (Saved Messages) orqali 'zdelka ochaymi?' xabari yuboradi. Zdelka O'ZI OCHILMAYDI.
Task Scheduler har 15 daqiqada ishga tushiradi. Parol yo'q: api_id/hash ish/tg_env.json dan.
Argument: --dry  -> yubormaydi, faqat chiqaradi.
"""
import os, sys, json, time, asyncio
import requests, pandas as pd

SYMS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","LTCUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","TRXUSDT","SUIUSDT","NEARUSDT"]
MIN_SCORE = 5
COOLDOWN_H = 4
SL_ATR, TP_ATR = 1.5, 2.25
BASE = r"D:\it-agent\data\ish"
STATE = BASE + r"\auto_scan_state.json"
ENV = BASE + r"\tg_env.json"
SESS = BASE + r"\tg_session"
GROUP_ID = 871134228  # Jamshid shaxsiy chati (bot bilan). Guruhda tugma ishlamagani uchun shaxsiy chatga yuboriladi

def get(s, tf):
    r = requests.get("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": s, "interval": tf, "limit": 300}, timeout=20).json()
    d = pd.DataFrame(r, columns="t o h l c v ct q n tb tq i".split())
    for c in "ohlcv": d[c] = d[c].astype(float)
    d["e20"] = d.c.ewm(span=20, adjust=False).mean(); d["e50"] = d.c.ewm(span=50, adjust=False).mean()
    dl = d.c.diff(); up = dl.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-dl.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    d["rsi"] = 100 - 100/(1 + up/dn)
    pc = d.c.shift(); tr = pd.concat([d.h-d.l, (d.h-pc).abs(), (d.l-pc).abs()], axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    d["vma"] = d.v.rolling(20).mean()
    return d.iloc[:-1].reset_index(drop=True)

def scan():
    out = []
    for s in SYMS:
        try: d4 = get(s, "4h"); d1 = get(s, "1h"); d15 = get(s, "15m")
        except Exception: continue
        t4 = "UP" if d4.iloc[-1].e20 > d4.iloc[-1].e50 else "DOWN"
        t1 = "UP" if d1.iloc[-1].e20 > d1.iloc[-1].e50 else "DOWN"
        l = d15.iloc[-1]; c = l.c; a = l.atr
        best = None
        for sd, tr in (("BUY", "UP"), ("SELL", "DOWN")):
            if t4 == tr and t1 == tr:
                sc = 2; w = ["4h+1h trend " + tr]
                if sd == "SELL":
                    if l.h >= l.e20*0.998 and c < l.e20: sc += 1; w.append("15m EMA20 rad")
                    if c < d15.l.iloc[-21:-1].min(): sc += 1; w.append("15m breakdown")
                    if 35 < l.rsi < 55: sc += 1; w.append("RSI %d" % l.rsi)
                else:
                    if l.l <= l.e20*1.002 and c > l.e20: sc += 1; w.append("15m EMA20 ushladi")
                    if c > d15.h.iloc[-21:-1].max(): sc += 1; w.append("15m breakout")
                    if 45 < l.rsi < 65: sc += 1; w.append("RSI %d" % l.rsi)
                if l.v > l.vma: sc += 1; w.append("hajm>o'rtacha")
                if best is None or sc > best["score"]:
                    sl = c + SL_ATR*a if sd == "SELL" else c - SL_ATR*a
                    tp = c - TP_ATR*a if sd == "SELL" else c + TP_ATR*a
                    best = dict(sym=s, side=sd, score=sc, price=c, sl=sl, tp=tp, why=w)
        if best: out.append(best)
    return sorted(out, key=lambda x: -x["score"])

def send(text, buttons=None):
    """Guruhga BOT nomidan yuboradi (Bot API). Token ish/bot_env.json da."""
    tok = json.load(open(BASE + r"\bot_env.json", encoding="utf-8-sig"))["token"]
    r = requests.post("https://api.telegram.org/bot%s/sendMessage" % tok,
                      json=dict({"chat_id": GROUP_ID, "text": text}, **({"reply_markup": {"inline_keyboard": buttons}} if buttons else {})), timeout=20)
    print("send:", r.status_code, r.json().get("ok"))
    return r.ok and r.json().get("ok")
def send_voice(strong):
    """Signal xulosasini ovozli xabar (uz, lotin matn) qilib guruhga BOT nomidan yuboradi."""
    import subprocess
    parts = ["Shep, skaner kuchli kirish topdi."]
    for r in strong[:3]:
        sd = "sotish" if r["side"] == "SELL" else "sotib olish"
        nm = r["sym"].replace("USDT", "")
        parts.append("%s, %s. Ball %d dan 6. Kirish taxminan %.5g, stoplos %.5g, tayk profit %.5g." %
                     (nm, sd, r["score"], r["price"], r["sl"], r["tp"]))
    parts.append("Zdelka ochishni xohlasangiz, shu chatga ha deb yozing.")
    out = BASE + r"\alert_voice.ogg"
    py = r"D:\it-agent\.venv\Scripts\python.exe"
    subprocess.run([py, r"D:\it-agent\data\skript\tts_voice.py", " ".join(parts), "uz", out], check=True, capture_output=True, timeout=120)
    tok = json.load(open(BASE + r"\bot_env.json", encoding="utf-8-sig"))["token"]
    with open(out, "rb") as f:
        r = requests.post("https://api.telegram.org/bot%s/sendVoice" % tok, data={"chat_id": GROUP_ID}, files={"voice": f}, timeout=60)
    print("voice:", r.status_code, r.json().get("ok"))
    return r.ok

def main():
    dry = "--dry" in sys.argv
    st = json.load(open(STATE)) if os.path.exists(STATE) else {}
    now = time.time(); res = scan()
    strong = [r for r in res if r["score"] >= MIN_SCORE
              and now - st.get(r["sym"] + r["side"], 0) > COOLDOWN_H*3600]
    for r in res: print(r["sym"], r["side"], r["score"], round(r["price"], 4))
    if not strong: print("kuchli signal yo'q"); return
    lines = ["SENTINAL: kuchli kirish topildi. Zdelka ochaymi? Ha yoki yoq deb yozing, DEMO hisobda ochaman (BTC/ETH ochiladi)"]
    for r in strong[:3]:
        lines.append("%s %s ball %d/6\nkirish ~%.5g SL %.5g TP %.5g\n%s" %
                     (r["sym"], r["side"], r["score"], r["price"], r["sl"], r["tp"], ", ".join(r["why"])))
    txt = "\n\n".join(lines); print(txt)
    if dry: return
    BOT = "sentinel_v4bot"
    btns = []
    for r in strong[:3]:
        k = "%s_%s" % (r["sym"], r["side"])
        btns.append([{"text": "HA: %s %s" % (r["sym"], r["side"]), "url": "https://t.me/%s?start=ha_%s" % (BOT, k)},
                     {"text": "YO'Q", "url": "https://t.me/%s?start=yoq_%s" % (BOT, k)}])
    if send(txt, None):
        try: send_voice(strong)
        except Exception as e: print('voice xato:', e)
        for r in strong[:3]: st[r["sym"] + r["side"]] = now
        json.dump(st, open(STATE, "w"))

main()





