import requests, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import sys
out = sys.argv[1]
r = requests.get("https://data-api.binance.vision/api/v3/klines", params={"symbol": "ETHUSDT", "interval": "15m", "limit": 80}, timeout=20).json()
entry, sl, tp = 2244.73, 2253.0, 2224.0
fig, ax = plt.subplots(figsize=(11, 6), facecolor="#111")
ax.set_facecolor("#111")
for i, k in enumerate(r):
    o, h, l, c = map(float, k[1:5])
    col = "#26a69a" if c >= o else "#ef5350"
    ax.plot([i, i], [l, h], color=col, lw=1)
    ax.add_patch(Rectangle((i - 0.3, min(o, c)), 0.6, max(abs(c - o), 0.05), color=col))
n = len(r)
ax.axhspan(entry, sl, color="#ef5350", alpha=0.15)
ax.axhspan(tp, entry, color="#26a69a", alpha=0.15)
for y, t, c in [(sl, "SL 2253.0", "#ef5350"), (entry, "SELL 2244.73", "#ffd54f"), (tp, "TP 2224.0", "#26a69a")]:
    ax.axhline(y, color=c, ls="--", lw=1.3)
    ax.text(n + 0.5, y, t, color=c, va="center", fontsize=11, fontweight="bold")
ax.set_xlim(0, n + 12)
lo = min(float(k[3]) for k in r); hi = max(float(k[2]) for k in r)
ax.set_ylim(min(lo, tp) - 3, max(hi, sl) + 3)
ax.tick_params(colors="#ccc")
ax.set_title("ETHUSDm SELL 0.1 lot (DEMO) #2720305695 - 15m (Binance ETHUSDT)", color="white")
ax.grid(color="#333", lw=0.5)
plt.tight_layout()
plt.savefig(out, dpi=110, facecolor="#111")
