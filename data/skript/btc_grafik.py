import sys, requests, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = r"D:\it-agent\data\ish\trading"
import os; os.makedirs(OUT, exist_ok=True)

def klines(tf, n=200):
    r = requests.get("https://data-api.binance.vision/api/v3/klines",
                     params={"symbol": "BTCUSDT", "interval": tf, "limit": 1000}, timeout=20)
    r.raise_for_status()
    d = pd.DataFrame(r.json(), columns="t o h l c v ct qv n tb tq i".split())
    for c in "ohlc": d[c] = d[c].astype(float)
    d["t"] = pd.to_datetime(d["t"], unit="ms")
    for p in (20, 50, 200): d[f"e{p}"] = d.c.ewm(span=p, adjust=False).mean()
    dl = d.c.diff()
    up = dl.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    dn = (-dl.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    d["rsi"] = 100 - 100 / (1 + up / dn)
    return d, d.tail(n).reset_index(drop=True)

ENTRY, SL, TP1, TP2 = 76600, 77500, 75250, 74400
def draw(tf, title, n, strat, fname):
    full, d = klines(tf, n)
    fig, (ax, ar) = plt.subplots(2, 1, figsize=(13, 8.5), sharex=True,
                                 gridspec_kw={"height_ratios": [4, 1]}, facecolor="#0e1117")
    for a in (ax, ar):
        a.set_facecolor("#0e1117"); a.tick_params(colors="#aaa"); a.grid(color="#222", lw=.5)
        for s in a.spines.values(): s.set_color("#333")
    w = .6
    for i, r in d.iterrows():
        col = "#26a69a" if r.c >= r.o else "#ef5350"
        ax.plot([i, i], [r.l, r.h], color=col, lw=.8)
        ax.add_patch(Rectangle((i - w/2, min(r.o, r.c)), w, max(abs(r.c - r.o), 1), color=col))
    for p, c in ((20, "#ffb300"), (50, "#42a5f5"), (200, "#ab47bc")):
        ax.plot(d.index, d[f"e{p}"], color=c, lw=1.3, label=f"EMA{p}")
    last = d.c.iloc[-1]
    lv = [(SL, "#ef5350", f"SL {SL}"), (ENTRY, "#ffffff", f"KIRISH SHORT {ENTRY}"),
          (TP1, "#66bb6a", f"TP1 {TP1}"), (TP2, "#2e7d32", f"TP2 {TP2}"),
          (last, "#ffd54f", f"Hozirgi {last:.0f}")]
    x1 = len(d) - 1
    ax.add_patch(Rectangle((0, ENTRY), x1 + 8, SL - ENTRY, color="#ef5350", alpha=.12))
    ax.add_patch(Rectangle((0, TP2), x1 + 8, ENTRY - TP2, color="#66bb6a", alpha=.10))
    for y, c, t in lv:
        ax.axhline(y, color=c, ls="--", lw=1.1)
        ax.text(x1 + 1, y, t, color=c, va="center", fontsize=9, fontweight="bold")
    lo = min(d.l.min(), TP2) - 300; hi = max(d.h.max(), SL) + 300
    ax.set_ylim(lo, hi); ax.set_xlim(-1, x1 + 28)
    ax.set_title(f"BTCUSDT {title} | {strat}", color="w", fontsize=12)
    ax.legend(loc="upper left", facecolor="#161b22", labelcolor="w", fontsize=8)
    ar.plot(d.index, d.rsi, color="#ffb300"); ar.axhline(70, color="#555", ls=":"); ar.axhline(30, color="#555", ls=":")
    ar.set_ylim(10, 90); ar.set_ylabel(f"RSI14 = {d.rsi.iloc[-1]:.1f}", color="#ccc")
    step = max(len(d)//8, 1)
    ar.set_xticks(d.index[::step]); ar.set_xticklabels(d.t.dt.strftime("%m-%d %H:%M")[::step], color="#aaa", fontsize=8)
    plt.tight_layout(); p = os.path.join(OUT, fname); fig.savefig(p, dpi=110); plt.close(fig)
    print(p, "last", last, "ema20/50/200", round(d.e20.iloc[-1]), round(d.e50.iloc[-1]), round(d.e200.iloc[-1]), "rsi", round(d.rsi.iloc[-1], 1))

draw("1d", "1D (kunlik)", 150, "Strategiya 1: EMA trend (narx EMA20/50/200 dan past) + RSI", "btc_1D.png")
draw("4h", "4H", 170, "Strategiya 2: Qarshilik zonasi 77450-77600 (EMA20 4H) + EMA200 1D 76630", "btc_4H.png")
draw("1h", "1H", 170, "Strategiya 3: Kirish limit 76600 + SL ATR asosida (1H ATR ~452)", "btc_1H.png")

