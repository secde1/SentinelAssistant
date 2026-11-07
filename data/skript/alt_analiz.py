import requests, pandas as pd, numpy as np, sys
syms = ["DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","LTCUSDT","TRXUSDT","DOTUSDT","TONUSDT","SUIUSDT","NEARUSDT"]
def kl(s, tf, n=300):
    r = requests.get("https://data-api.binance.vision/api/v3/klines", params={"symbol": s, "interval": tf, "limit": n}, timeout=20)
    r.raise_for_status()
    d = pd.DataFrame(r.json()).iloc[:, :6]
    d.columns = ["t","o","h","l","c","v"]
    d = d.astype(float)
    return d.iloc[:-1]
def rsi(c, n=14):
    d = c.diff(); u = d.clip(lower=0).ewm(alpha=1/n).mean(); w = (-d.clip(upper=0)).ewm(alpha=1/n).mean()
    return 100 - 100/(1+u/w)
def atr(d, n=14):
    tr = pd.concat([d.h-d.l, (d.h-d.c.shift()).abs(), (d.l-d.c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n).mean()
rows = []
for s in syms:
    try:
        h = kl(s, "1h"); f = kl(s, "4h"); dd = kl(s, "1d", 120)
    except Exception as e:
        rows.append((s, "xato", str(e)[:40])); continue
    c = h.c; e20 = c.ewm(span=20).mean(); e50 = c.ewm(span=50).mean()
    e50_4 = f.c.ewm(span=50).mean(); e20_4 = f.c.ewm(span=20).mean()
    a = atr(h).iloc[-1]; r = rsi(c).iloc[-1]; r4 = rsi(f.c).iloc[-1]
    price = c.iloc[-1]
    ch24 = (price/c.iloc[-25]-1)*100; ch7 = (price/dd.c.iloc[-8]-1)*100
    hi = h.h.iloc[-48:].max(); lo = h.l.iloc[-48:].min()
    vr = h.v.iloc[-6:].mean()/h.v.iloc[-72:].mean()
    t1 = "UP" if e20.iloc[-1] > e50.iloc[-1] else "DOWN"
    t4 = "UP" if e20_4.iloc[-1] > e50_4.iloc[-1] else "DOWN"
    rows.append((s, round(price, 5), f"{ch24:+.1f}%", f"{ch7:+.1f}%", t1, t4, round(r,0), round(r4,0), f"{a/price*100:.2f}%", f"{lo:.5g}", f"{hi:.5g}", round(vr,2)))
print("sym price 24h 7d 1hTrend 4hTrend RSI1h RSI4h ATR% low48 high48 volRatio")
for r in rows: print(*r)

