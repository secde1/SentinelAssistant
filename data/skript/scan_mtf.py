import requests, pandas as pd, json
SYMS=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","LTCUSDT","ADAUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT"]
def get(s,tf):
    r=requests.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":s,"interval":tf,"limit":300},timeout=20).json()
    d=pd.DataFrame(r,columns="t o h l c v ct q n tb tq i".split())
    for c in "ohlcv": d[c]=d[c].astype(float)
    d["e20"]=d.c.ewm(span=20,adjust=False).mean(); d["e50"]=d.c.ewm(span=50,adjust=False).mean()
    dl=d.c.diff(); up=dl.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); dn=(-dl.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    d["rsi"]=100-100/(1+up/dn)
    pc=d.c.shift(); tr=pd.concat([d.h-d.l,(d.h-pc).abs(),(d.l-pc).abs()],axis=1).max(axis=1); d["atr"]=tr.ewm(alpha=1/14,adjust=False).mean()
    d["vma"]=d.v.rolling(20).mean()
    return d.iloc[:-1].reset_index(drop=True)
out=[]
for s in SYMS:
    try: d4=get(s,"4h"); d1=get(s,"1h"); d15=get(s,"15m")
    except Exception as e: out.append(dict(sym=s,err=str(e))); continue
    t4="UP" if d4.iloc[-1].e20>d4.iloc[-1].e50 else "DOWN"
    t1="UP" if d1.iloc[-1].e20>d1.iloc[-1].e50 else "DOWN"
    l=d15.iloc[-1]; a=l.atr; c=l.c
    side=None; score=0; why=[]
    for sd,tr in (("BUY","UP"),("SELL","DOWN")):
        if t4==tr and t1==tr:
            sc=2; w=["4h+1h trend "+tr]
            if sd=="SELL":
                if l.h>=l.e20*0.998 and c<l.e20: sc+=1; w.append("15m pullback to EMA20 rejected")
                if c<d15.l.iloc[-21:-1].min(): sc+=1; w.append("15m breakdown")
                if 35<l.rsi<55: sc+=1; w.append("RSI room %d"%l.rsi)
            else:
                if l.l<=l.e20*1.002 and c>l.e20: sc+=1; w.append("15m pullback to EMA20 held")
                if c>d15.h.iloc[-21:-1].max(): sc+=1; w.append("15m breakout")
                if 45<l.rsi<65: sc+=1; w.append("RSI room %d"%l.rsi)
            if l.v>l.vma: sc+=1; w.append("volume>avg")
            if sc>score: side,score,why=sd,sc,w
    out.append(dict(sym=s,price=c,t4=t4,t1=t1,rsi=round(l.rsi),atr=round(a,5),side=side,score=score,why=why))
json.dump(out,open(r"D:\it-agent\data\ish\scan_mtf.json","w",encoding="utf-8"),ensure_ascii=False,indent=1)
for o in sorted(out,key=lambda x:-x.get("score",0)): print(json.dumps(o,ensure_ascii=True))
