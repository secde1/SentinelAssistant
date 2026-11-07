import requests, pandas as pd, numpy as np
B = "https://data-api.binance.vision/api/v3/klines"
def get(tf, n=300):
    r = requests.get(B, params={"symbol": "PAXGUSDT", "interval": tf, "limit": n}, timeout=20).json()
    d = pd.DataFrame(r, columns="t o h l c v ct qv n tb tq i".split())
    for k in "ohlcv": d[k] = d[k].astype(float)
    d["t"] = pd.to_datetime(d["t"], unit="ms") + pd.Timedelta(hours=5)
    return d
def rsi(s, n=14):
    d = s.diff(); u = d.clip(lower=0).ewm(alpha=1/n).mean(); w = (-d.clip(upper=0)).ewm(alpha=1/n).mean()
    return 100 - 100/(1+u/w)
def atr(d, n=14):
    tr = pd.concat([d.h-d.l, (d.h-d.c.shift()).abs(), (d.l-d.c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n).mean()
for tf in ["5m", "15m", "1h"]:
    d = get(tf); c = d.c
    e20, e50 = c.ewm(span=20).mean(), c.ewm(span=50).mean()
    ma = c.rolling(20).mean(); sd = c.rolling(20).std()
    up, lo = ma+2*sd, ma-2*sd
    a = atr(d); r = rsi(c)
    tp = (d.h+d.l+d.c)/3; day = d.t.dt.date
    vwap = (tp*d.v).groupby(day).cumsum()/d.v.groupby(day).cumsum()
    hh, ll = d.h.iloc[-21:-1].max(), d.l.iloc[-21:-1].min()
    print(f"== {tf} last {d.t.iloc[-1]} (UZT) close {c.iloc[-1]:.2f}")
    print(f"EMA20 {e20.iloc[-1]:.2f} EMA50 {e50.iloc[-1]:.2f} | RSI {r.iloc[-1]:.1f} | BB {lo.iloc[-1]:.2f}-{up.iloc[-1]:.2f} | ATR {a.iloc[-1]:.2f} | VWAP {vwap.iloc[-1]:.2f}")
    print(f"Donchian20 high {hh:.2f} low {ll:.2f} | 50bar high {d.h.iloc[-50:].max():.2f} low {d.l.iloc[-50:].min():.2f}")
    print("last5 closes", [round(x,2) for x in c.iloc[-5:]])
