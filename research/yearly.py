import pickle, sys, collections, math
sys.path.insert(0, r"D:\it-agent\research")
import lab
L = r"D:\it-agent\data\trading_memory\lab"
for sym, tf, sid in (("XAUUSDm","4h","MA-CROSS"),("XAUUSDm","1h","VOL-BRK"),("USTECm","1h","TF-PULLBACK"),("BTCUSDm","1h","TF-PULLBACK"),("BTCUSDm","4h","RSI-MR")):
    tr = lab.executed(pickle.load(open(f"{L}/trades_{sym}_{tf}_{sid}_net.pkl","rb")))
    y = collections.defaultdict(list)
    for t in tr: y[t.ts.year].append(t.r)
    rs=[t.r for t in tr]; n=len(rs); m=sum(rs)/n; sd=math.sqrt(sum((r-m)**2 for r in rs)/(n-1)); tt=m/(sd/math.sqrt(n))
    print(sym, tf, sid, f"t={tt:.2f}", " | ".join(f"{k}: n={len(v)} E={sum(v)/len(v):+.2f}" for k, v in sorted(y.items())))
