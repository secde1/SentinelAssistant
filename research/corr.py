import sys, math
sys.path.insert(0, r"D:\it-agent\research")
import lab
S = ["BTCUSDm", "ETHUSDm", "XAUUSDm", "USTECm", "US500m", "EURUSDm", "GBPUSDm"]
R = {}
for s in S:
    c = lab.load(s, "1d"); R[s] = {k.ts.date(): math.log(b.close / a.close) for a, b, k in zip(c, c[1:], c[1:]) if a.close > 0}
def corr(a, b, days=None):
    ks = sorted(set(R[a]) & set(R[b]))
    if days: ks = ks[-days:]
    x = [R[a][k] for k in ks]; y = [R[b][k] for k in ks]
    n = len(x); mx, my = sum(x)/n, sum(y)/n
    sx = math.sqrt(sum((v-mx)**2 for v in x)); sy = math.sqrt(sum((v-my)**2 for v in y))
    return sum((p-mx)*(q-my) for p, q in zip(x, y)) / (sx*sy)
for label, d in (("5 yil (kunlik logaritmik daromad)", None), ("oxirgi 90 kun", 90), ("oxirgi 250 kun", 250)):
    print("\n", label); print("%9s" % "", *["%8s" % s[:6] for s in S])
    for a in S: print("%9s" % a[:6], *["%8.2f" % corr(a, b, d) for b in S])
# rolling 90d min/max for key pairs
for a, b in (("BTCUSDm","ETHUSDm"),("USTECm","US500m"),("BTCUSDm","USTECm"),("XAUUSDm","USTECm")):
    ks = sorted(set(R[a]) & set(R[b])); vals = []
    for i in range(90, len(ks), 30):
        w = ks[i-90:i]; x=[R[a][k] for k in w]; y=[R[b][k] for k in w]; mx,my=sum(x)/90,sum(y)/90
        vals.append(sum((p-mx)*(q-my) for p,q in zip(x,y))/math.sqrt(sum((p-mx)**2 for p in x)*sum((q-my)**2 for q in y)))
    print(a, b, "90k rolling: min %.2f max %.2f" % (min(vals), max(vals)))
