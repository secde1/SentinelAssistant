import requests, pandas as pd, numpy as np, json
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","LTCUSDT","ADAUSDT","DOGEUSDT"]
def get(s,tf="1h"):
    r=requests.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":s,"interval":tf,"limit":300},timeout=20).json()
    d=pd.DataFrame(r,columns="t o h l c v ct q n tb tq i".split())
    for c in "ohlcv": d[c]=d[c].astype(float)
    d["e20"]=d.c.ewm(span=20,adjust=False).mean(); d["e50"]=d.c.ewm(span=50,adjust=False).mean()
    dl=d.c.diff(); up=dl.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); dn=(-dl.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    d["rsi"]=100-100/(1+up/dn)
    pc=d.c.shift(); tr=pd.concat([d.h-d.l,(d.h-pc).abs(),(d.l-pc).abs()],axis=1).max(axis=1); d["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    d["vma"]=d.v.rolling(20).mean()
    return d.iloc[:-1].reset_index(drop=True)  # yopilgan shamlar
out=[]
for s in SYMS:
    try: d=get(s)
    except Exception as e: out.append((s,"ERR",str(e))); continue
    l=d.iloc[-1]; a=l.atr; c=l.c
    sig=[]
    # 1 trend pullback
    if l.e20>l.e50 and l.l<=l.e20*1.002 and c>l.e20 and l.rsi>45: sig.append(("TF-PULLBACK","BUY"))
    if l.e20<l.e50 and l.h>=l.e20*0.998 and c<l.e20 and l.rsi<55: sig.append(("TF-PULLBACK","SELL"))
    # 2 Donchian breakout (20) + volume
    hh=d.h.iloc[-21:-1].max(); ll=d.l.iloc[-21:-1].min()
    if c>hh and l.v>l.vma: sig.append(("VOL-BRK","BUY"))
    if c<ll and l.v>l.vma: sig.append(("VOL-BRK","SELL"))
    # 3 RSI mean reversion
    if l.rsi<30: sig.append(("RSI-MR","BUY"))
    if l.rsi>70: sig.append(("RSI-MR","SELL"))
    # 4 S/R bounce: 100-bar range zones
    sup=d.l.iloc[-100:].min(); res=d.h.iloc[-100:].max()
    if abs(c-sup)<1.0*a and c>l.o: sig.append(("SR-BOUNCE","BUY"))
    if abs(c-res)<1.0*a and c<l.o: sig.append(("SR-BOUNCE","SELL"))
    # 5 MA cross recent
    p=d.iloc[-4:]
    if (p.e20.iloc[0]<=p.e50.iloc[0]) and l.e20>l.e50: sig.append(("MA-CROSS","BUY"))
    if (p.e20.iloc[0]>=p.e50.iloc[0]) and l.e20<l.e50: sig.append(("MA-CROSS","SELL"))
    trend="UP" if l.e20>l.e50 else "DOWN"
    out.append(dict(sym=s,price=round(c,4),trend=trend,rsi=round(l.rsi),atr=round(a,4),sup=round(sup,4),res=round(res,4),e20=round(l.e20,4),e50=round(l.e50,4),sig=sig))
with open(r"D:\it-agent\data\ish\scan4.json","w",encoding="utf-8") as f: json.dump(out,f,ensure_ascii=False,indent=1)
for o in out: print(json.dumps(o,ensure_ascii=False))
