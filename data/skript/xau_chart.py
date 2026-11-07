import requests, pandas as pd, numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import sys
out = r"D:\it-agent\data\ish\xau"
import os; os.makedirs(out, exist_ok=True)

def get(tf, n=120):
    r = requests.get("https://data-api.binance.vision/api/v3/klines", params={"symbol":"PAXGUSDT","interval":tf,"limit":300}, timeout=20).json()
    d = pd.DataFrame(r, columns="t o h l c v ct q n tb tq i".split())
    for c in "ohlcv": d[c] = d[c].astype(float)
    d["t"] = pd.to_datetime(d["t"], unit="ms") + pd.Timedelta(hours=5)
    d["e20"] = d.c.ewm(span=20, adjust=False).mean()
    d["e50"] = d.c.ewm(span=50, adjust=False).mean()
    dl = d.c.diff(); up = dl.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); dn = (-dl.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    d["rsi"] = 100 - 100/(1+up/dn)
    tp = (d.h+d.l+d.c)/3
    d["vwap"] = (tp*d.v).groupby(d.t.dt.date).cumsum()/d.v.groupby(d.t.dt.date).cumsum()
    return d.tail(n).reset_index(drop=True)

files = []
for tf in ["5m","15m","1h"]:
    d = get(tf)
    fig, (a, b) = plt.subplots(2,1, figsize=(10,7), gridspec_kw={"height_ratios":[3,1]}, sharex=True)
    for i,r in d.iterrows():
        col = "#26a69a" if r.c>=r.o else "#ef5350"
        a.plot([i,i],[r.l,r.h], color=col, lw=0.8)
        a.add_patch(Rectangle((i-0.3,min(r.o,r.c)), 0.6, max(abs(r.c-r.o),0.01), color=col))
    a.plot(d.e20, label="EMA20", color="orange"); a.plot(d.e50, label="EMA50", color="blue")
    if tf!="1h": a.plot(d.vwap, label="VWAP", color="purple", ls="--")
    a.set_title(f"PAXG/USDT (tilla) {tf} | narx {d.c.iloc[-1]:.1f} | RSI {d.rsi.iloc[-1]:.0f}")
    a.legend(loc="upper left"); a.grid(alpha=.3)
    b.plot(d.rsi, color="teal"); b.axhline(70, color="r", ls=":"); b.axhline(30, color="g", ls=":"); b.set_ylim(0,100); b.set_ylabel("RSI14"); b.grid(alpha=.3)
    step = max(len(d)//8,1); b.set_xticks(range(0,len(d),step)); b.set_xticklabels([t.strftime("%d %H:%M") for t in d.t[::step]], rotation=30)
    p = f"{out}\\xau_{tf}.png"; fig.tight_layout(); fig.savefig(p, dpi=110); plt.close(fig); files.append(p)
    print(p, os.path.getsize(p), round(d.c.iloc[-1],1), round(d.rsi.iloc[-1]))
