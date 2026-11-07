import json
d = json.load(open(r"D:\it-agent\data\trading_memory\lab\baseline.json"))
def f(x): return "  -  " if x is None else f"{x:+.3f}"
print("sym tf strategy | n | WR% | gross E | net E (CI95) | stress E | PF net | maxDD | OOS n/E net")
rows = []
for k, v in d.items():
    sym, tf, sid, mode = k.split("|")
    if mode != "net": continue
    g = d[f"{sym}|{tf}|{sid}|gross"]["all"]; s = d[f"{sym}|{tf}|{sid}|stress"]["all"]; a = v["all"]; o = v["oos"]
    rows.append((a["expectancy"] or -9, sym, tf, sid, a, g, s, o))
rows.sort(key=lambda r: -r[0])
for e, sym, tf, sid, a, g, s, o in rows:
    print(f"{sym:8}{tf:3} {sid:12}| {a['n']:4} | {a['win_rate']} | {f(g['expectancy'])} | {f(a['expectancy'])} [{f(a['ci_lo'])},{f(a['ci_hi'])}] | {f(s['expectancy'])} | {a['pf']} | {a['maxdd']} | {o['n']}/{f(o['expectancy'])}")
