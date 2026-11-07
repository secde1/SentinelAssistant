import requests, pandas as pd, matplotlib, os, json
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
out=r"D:\it-agent\data\ish\btc"; os.makedirs(out,exist_ok=True)
def get(tf,n=120):
    r=requests.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":"BTCUSDT","interval":tf,"limit":300},timeout=20).json()
    d=pd.DataFrame(r,columns="t o h l c v ct q n tb tq i".split())
    for c in "ohlcv": d[c]=d[c].astype(float)
    d["t"]=pd.to_datetime(d["t"],unit="ms")+pd.Timedelta(hours=5)
    d["e20"]=d.c.ewm(span=20,adjust=False).mean(); d["e50"]=d.c.ewm(span=50,adjust=False).mean()
    dl=d.c.diff(); up=dl.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); dn=(-dl.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    d["rsi"]=100-100/(1+up/dn)
    pc=d.c.shift(); tr=pd.concat([d.h-d.l,(d.h-pc).abs(),(d.l-pc).abs()],axis=1).max(axis=1); d["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    return d.tail(n).reset_index(drop=True)
for tf in ["15m","1h","4h"]:
    d=get(tf)
    fig,(a,b)=plt.subplots(2,1,figsize=(10,7),gridspec_kw={"height_ratios":[3,1]},sharex=True)
    for i,r in d.iterrows():
        col="#26a69a" if r.c>=r.o else "#ef5350"
        a.plot([i,i],[r.l,r.h],color=col,lw=.8); a.add_patch(Rectangle((i-.3,min(r.o,r.c)),.6,max(abs(r.c-r.o),1),color=col))
    a.plot(d.e20,color="orange",label="EMA20"); a.plot(d.e50,color="blue",label="EMA50")
    hi=d.h.max(); lo=d.l.min(); a.axhline(hi,color="r",ls=":",lw=.8); a.axhline(lo,color="g",ls=":",lw=.8)
    a.set_title(f"BTCUSD {tf} (Binance BTCUSDT) | {d.c.iloc[-1]:.0f} | RSI {d.rsi.iloc[-1]:.0f}"); a.legend(loc="upper left"); a.grid(alpha=.3)
    b.plot(d.rsi,color="teal"); b.axhline(70,color="r",ls=":"); b.axhline(30,color="g",ls=":"); b.set_ylim(0,100); b.grid(alpha=.3)
    st=max(len(d)//8,1); b.set_xticks(range(0,len(d),st)); b.set_xticklabels([t.strftime("%d %H:%M") for t in d.t[::st]],rotation=30)
    p=f"{out}\\btc_{tf}.png"; fig.tight_layout(); fig.savefig(p,dpi=110); plt.close(fig)
    l=d.iloc[-1]; print(tf,p,os.path.getsize(p),"c",round(l.c),"e20",round(l.e20),"e50",round(l.e50),"rsi",round(l.rsi),"atr",round(l.atr),"hi",round(hi),"lo",round(lo))
