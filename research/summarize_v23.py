import json, math, collections
d = json.load(open(r"D:\it-agent\data\trading_memory\lab\baseline_v23.json"))
def f(x): return "  -  " if x is None else f"{x:+.3f}"
rows = []
for k, v in d.items():
    sym, tf, sid, mode = k.split("|")
    if mode != "net": continue
    g = d[f"{sym}|{tf}|{sid}|gross"]["all"]; s = d[f"{sym}|{tf}|{sid}|stress"]["all"]; a = v["all"]; o = v["oos"]
    p = 1.0
    if a["n"] > 2 and a["ci_hi"] is not None:
        se = (a["ci_hi"] - a["ci_lo"]) / 2 / 1.96
        z = a["expectancy"] / se if se else 0
        p = math.erfc(abs(z) / math.sqrt(2)) / 2 if a["expectancy"] > 0 else 1.0
    rows.append((a["expectancy"] if a["expectancy"] is not None else -9, sym, tf, sid, a, g, s, o, p))
rows.sort(key=lambda r: -r[0])
m = len(rows)
ps = sorted(r[8] for r in rows)
def holm(p):
    rank = sum(1 for q in ps if q < p)
    return min(1.0, (m - rank) * p)
print(f"{m} kombinatsiya. sym tf strategy | n | WR% | gross E | net E [CI95] | stress E | PF | maxDD | OOS n/E | p(1-tomon) | Holm(m={m})")
for e, sym, tf, sid, a, g, s, o, p in rows:
    print(f"{sym:8}{tf:3} {sid:10}| {a['n']:5} | {a['win_rate']} | {f(g['expectancy'])} | {f(a['expectancy'])} [{f(a['ci_lo'])},{f(a['ci_hi'])}] | {f(s['expectancy'])} | {a['pf']} | {a['maxdd']} | {o['n']}/{f(o['expectancy'])} | {p:.4f} | {holm(p):.3f}")
agg = collections.defaultdict(list)
import pickle, glob
print("\n=== Strategiya bo'yicha jami (net, barcha instrument, 1h) ===")
for sid in ("LIQ-SWEEP", "TL-BOUNCE", "TL-BREAK", "SNR-REJ"):
    for tf in ("1h", "4h"):
        rs = []
        for p in glob.glob(rf"D:\it-agent\data\trading_memory\lab\trades_*_{tf}_{sid}_net.pkl"):
            rs += [t.r for t in pickle.load(open(p, "rb")) if t.status in ("TP_HIT", "SL_HIT", "EXPIRED") and t.r is not None]
        n = len(rs); mu = sum(rs) / n; sd = math.sqrt(sum((r - mu) ** 2 for r in rs) / (n - 1)); h = 1.96 * sd / math.sqrt(n)
        print(f"{sid:10} {tf}: n={n:6} E={mu:+.3f} CI[{mu-h:+.3f},{mu+h:+.3f}] WR={sum(r>0 for r in rs)/n*100:.1f}%")
