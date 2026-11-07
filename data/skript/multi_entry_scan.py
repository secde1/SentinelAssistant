import requests, json, sys
import pandas as pd, numpy as np
B = "https://data-api.binance.vision/api/v3/klines"
SYMS = ["BTC","ETH","BNB","SOL","XRP","ADA","DOGE","AVAX","LINK","DOT","LTC","TRX","ATOM","NEAR","APT","ARB","OP","INJ","SUI","TON","UNI","AAVE","FIL","ETC","BCH","XLM","HBAR","ICP","RUNE","SEI"]
def kl(s, tf, n=300):
    r = requests.get(B, params={"symbol": s+"USDT", "interval": tf, "limit": n}, timeout=20).json()
    d = pd.DataFrame(r).iloc[:, :6]
    d.columns = ["t","o","h","l","c","v"]
    for c in "ohlcv": d[c] = d[c].astype(float)
    return d.iloc[:-1]
def ema(x, n): return x.ewm(span=n, adjust=False).mean()
def atr(d, n=14):
    pc = d.c.shift()
    tr = pd.concat([d.h-d.l, (d.h-pc).abs(), (d.l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()
def rsi(c, n=14):
    dl = c.diff(); u = dl.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); dn = (-dl.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100-100/(1+u/dn)
out = []
for s in SYMS:
    try:
        d4 = kl(s, "4h"); d1 = kl(s, "1h")
    except Exception as e:
        continue
    e20, e50, e200 = ema(d4.c,20), ema(d4.c,50), ema(d4.c,200)
    a4 = atr(d4); r1 = rsi(d1.c); a1 = atr(d1)
    px = d1.c.iloc[-1]
    up = e20.iloc[-1] > e50.iloc[-1] > e200.iloc[-1] and px > e50.iloc[-1]
    dn = e20.iloc[-1] < e50.iloc[-1] < e200.iloc[-1] and px < e50.iloc[-1]
    hi20 = d4.h.iloc[-30:].max(); lo20 = d4.l.iloc[-30:].min()
    dist20 = (px - e20.iloc[-1]) / a4.iloc[-1]
    ch7 = (px / d1.c.iloc[-168] - 1) * 100
    side = "LONG" if up else "SHORT" if dn else "-"
    note = ""
    sc = 0
    if side == "LONG":
        if abs(dist20) < 1.0: sc += 2; note += "4h EMA20 yaqin(pullback); "
        if 40 <= r1.iloc[-1] <= 60: sc += 1; note += "RSI1h neytral; "
        if r1.iloc[-1] > 72: sc -= 2; note += "haddan tashqari qizigan; "
        sl = px - 1.5*a1.iloc[-1]*1.5; tp = px + 2.25*a1.iloc[-1]*1.5
    elif side == "SHORT":
        if abs(dist20) < 1.0: sc += 2; note += "4h EMA20 yaqin(pullback); "
        if 40 <= r1.iloc[-1] <= 60: sc += 1; note += "RSI1h neytral; "
        if r1.iloc[-1] < 28: sc -= 2; note += "haddan tashqari sotilgan; "
        sl = px + 1.5*a1.iloc[-1]*1.5; tp = px - 2.25*a1.iloc[-1]*1.5
    else:
        sl = tp = np.nan
    if side != "-": sc += 1
    out.append(dict(sym=s, side=side, px=px, rsi1h=round(r1.iloc[-1],1), dist_ema20_atr=round(dist20,2), ch7d=round(ch7,1), score=sc, sl=sl, tp=tp, note=note))
df = pd.DataFrame(out).sort_values("score", ascending=False)
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
print(df.to_string(index=False))
