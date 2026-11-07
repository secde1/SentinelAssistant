import pickle, glob, sys, collections, math
sys.path.insert(0, r"D:\it-agent\research")
import lab
L = r"D:\it-agent\data\trading_memory\lab"
def load(mode="net", tf=None):
    out = []
    for p in glob.glob(f"{L}/trades_*_{mode}.pkl"):
        _, sym, t, sid, _m = p.split("\\")[-1][:-4].split("_")
        if tf and t != tf: continue
        for tr in pickle.load(open(p, "rb")):
            tr.extra = {"sym": sym, "tf": t, "sid": sid}; out.append(tr)
    return out
def table(trades, key, title):
    g = collections.defaultdict(list)
    for t in lab.executed(trades): g[key(t)].append(t.r)
    print(f"\n## {title}")
    for k, rs in sorted(g.items(), key=lambda kv: sum(kv[1]) / len(kv[1])):
        n = len(rs); m = sum(rs) / n; sd = math.sqrt(sum((r - m) ** 2 for r in rs) / max(n - 1, 1)); h = 1.96 * sd / math.sqrt(n)
        print(f"{str(k):40} n={n:6} E={m:+.3f} CI[{m-h:+.3f},{m+h:+.3f}] WR={sum(r>0 for r in rs)/n*100:.1f}%")
for tf in ("1h", "4h"):
    T = load("net", tf)
    print(f"\n######## TF {tf}: {len(lab.executed(T))} savdo (net)")
    table(T, lambda t: t.extra["sid"], "strategiya")
    table(T, lambda t: t.regime, "rejim (barcha strategiyalar)")
    table(T, lambda t: (t.extra["sid"], t.regime), "strategiya x rejim")
    if tf == "1h":
        table(T, lambda t: t.htf, "H4 yo'nalishi bilan moslik")
        table(T, lambda t: (t.extra["sid"], t.htf), "strategiya x H4")
        table(T, lambda t: t.session, "sessiya")
        table(T, lambda t: t.direction, "yo'nalish")
    table(T, lambda t: t.extra["sym"], "instrument")
G = load("gross", "1h"); N = load("net", "1h")
for nm, X in (("gross", G), ("net", N)):
    rs = [t.r for t in lab.executed(X)]; print(nm, "1h jami E =", round(sum(rs) / len(rs), 4), "n", len(rs))
