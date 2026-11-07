import requests, pandas as pd, numpy as np, matplotlib, os, json
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
out = r"D:\it-agent\data\ish\xau"; os.makedirs(out, exist_ok=True)

def get(tf, n=110):
    r = requests.get("https://data-api.binance.vision/api/v3/klines", params={"symbol":"PAXGUSDT","interval":tf,"limit":300}, timeout=20).json()
    d = pd.DataFrame(r, columns="t o h l c v ct q n tb tq i".split())
    for c in "ohlcv": d[c] = d[c].astype(float)
    d["t"] = pd.to_datetime(d["t"], unit="ms") + pd.Timedelta(hours=5)
    d["e20"] = d.c.ewm(span=20, adjust=False).mean(); d["e50"] = d.c.ewm(span=50, adjust=False).mean()
    dl = d.c.diff(); up = dl.clip(lower=0).ewm(alpha=1/14, adjust=False).mean(); dn = (-dl.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    d["rsi"] = 100 - 100/(1+up/dn)
    tp = (d.h+d.l+d.c)/3
    d["vwap"] = (tp*d.v).groupby(d.t.dt.date).cumsum()/d.v.groupby(d.t.dt.date).cumsum()
    pc = d.c.shift()
    tr = pd.concat([d.h-d.l,(d.h-pc).abs(),(d.l-pc).abs()],axis=1).max(axis=1)
    d["atr"] = tr.ewm(alpha=1/14, adjust=False).mean()
    return d.tail(n).reset_index(drop=True)

def strategies(d):
    p = d.c.iloc[-1]; atr = d.atr.iloc[-1]; res = []
    hi = d.h.iloc[-21:-1].max(); lo = d.l.iloc[-21:-1].min()
    # 1 EMA trend
    if p < d.e20.iloc[-1] < d.e50.iloc[-1]: res.append(("EMA trend","SHORT","narx EMA20<EMA50 dan past"))
    elif p > d.e20.iloc[-1] > d.e50.iloc[-1]: res.append(("EMA trend","LONG","narx EMA20>EMA50 dan yuqori"))
    else: res.append(("EMA trend","KUTISH","EMA lar aralash"))
    # 2 VWAP
    res.append(("VWAP","SHORT" if p < d.vwap.iloc[-1] else "LONG", f"narx VWAP {d.vwap.iloc[-1]:.1f} dan {'past' if p<d.vwap.iloc[-1] else 'yuqori'}"))
    # 3 RSI
    r = d.rsi.iloc[-1]
    if r < 30: res.append(("RSI","LONG",f"RSI {r:.0f} oversold"))
    elif r > 70: res.append(("RSI","SHORT",f"RSI {r:.0f} overbought"))
    else: res.append(("RSI","KUTISH",f"RSI {r:.0f} neytral"))
    # 4 Breakout 20
    if p > hi: res.append(("Breakout20","LONG",f"{hi:.1f} yuqoriga chiqdi"))
    elif p < lo: res.append(("Breakout20","SHORT",f"{lo:.1f} pastga chiqdi"))
    else: res.append(("Breakout20","KUTISH",f"diapazon {lo:.1f}-{hi:.1f} ichida"))
    return res, p, atr, hi, lo

summary = {}
files = []
for tf in ["5m","15m","1h"]:
    d = get(tf); res, p, atr, hi, lo = strategies(d)
    votes = [x[1] for x in res]; ns, nl = votes.count("SHORT"), votes.count("LONG")
    side = "SHORT" if ns>nl else "LONG" if nl>ns else "KUTISH"
    fig, (a, b) = plt.subplots(2,1, figsize=(11,8), gridspec_kw={"height_ratios":[3,1]}, sharex=True)
    for i,r in d.iterrows():
        col = "#26a69a" if r.c>=r.o else "#ef5350"
        a.plot([i,i],[r.l,r.h], color=col, lw=0.8); a.add_patch(Rectangle((i-0.3,min(r.o,r.c)),0.6,max(abs(r.c-r.o),0.01),color=col))
    a.plot(d.e20,label="EMA20",color="orange"); a.plot(d.e50,label="EMA50",color="blue"); a.plot(d.vwap,label="VWAP",color="purple",ls="--")
    a.axhline(hi,color="gray",ls=":",lw=1); a.axhline(lo,color="gray",ls=":",lw=1)
    a.text(0,hi,f" qarshilik {hi:.1f}",color="gray",va="bottom",fontsize=8); a.text(0,lo,f" tayanch {lo:.1f}",color="gray",va="top",fontsize=8)
    lv = None
    if side != "KUTISH":
        sgn = -1 if side=="SHORT" else 1
        sl = p - sgn*1.5*atr; tp1 = p + sgn*1.5*atr*1.5; tp2 = p + sgn*1.5*atr*3
        lv = dict(entry=p, sl=sl, tp1=tp1, tp2=tp2)
        for nm,v,c in [("KIRISH",p,"black"),("SL",sl,"red"),("TP1 (1.5R)",tp1,"green"),("TP2 (3R)",tp2,"darkgreen")]:
            a.axhline(v,color=c,lw=1.3,ls="-" if nm=="KIRISH" else "--")
            a.text(len(d)-1,v,f"{nm} {v:.1f} ",color=c,ha="right",va="bottom",fontsize=9,fontweight="bold")
    txt = "\n".join(f"{n}: {s} ({w})" for n,s,w in res) + f"\nUmumiy: {side} ({ns} SHORT / {nl} LONG)"
    a.text(0.01,0.02,txt,transform=a.transAxes,fontsize=8,va="bottom",bbox=dict(fc="white",alpha=.85))
    a.set_title(f"PAXG/USDT (tilla) {tf} | narx {p:.1f} | ATR {atr:.2f} | {side}"); a.legend(loc="upper left"); a.grid(alpha=.3)
    b.plot(d.rsi,color="teal"); b.axhline(70,color="r",ls=":"); b.axhline(30,color="g",ls=":"); b.set_ylim(0,100); b.grid(alpha=.3); b.set_ylabel("RSI14")
    step=max(len(d)//8,1); b.set_xticks(range(0,len(d),step)); b.set_xticklabels([t.strftime("%d %H:%M") for t in d.t[::step]],rotation=30)
    pth = f"{out}\\xau_signal_{tf}.png"; fig.tight_layout(); fig.savefig(pth,dpi=110); plt.close(fig); files.append(pth)
    summary[tf] = dict(price=round(p,1), atr=round(atr,2), side=side, votes=res, levels=lv and {k:round(v,1) for k,v in lv.items()})
json.dump(summary, open(out+"\\xau_signal.json","w"), ensure_ascii=False, indent=1)
for f in files: print(f, os.path.getsize(f))
for tf,s in summary.items(): print(tf, s["price"], s["side"], s["levels"], [(x[0],x[1]) for x in s["votes"]])
