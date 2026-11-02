import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

counts = [45, 44, 44, 44, 44, 44]  # jami 265
cols, rows = 8, 6
fig, axes = plt.subplots(2, 3, figsize=(18, 9))
n = 1
for i, ax in enumerate(axes.flat):
    c = counts[i]
    ax.set_xlim(0, cols); ax.set_ylim(0, rows); ax.invert_yaxis()
    ax.set_aspect(0.5625)
    k = 0
    for r in range(rows):
        for q in range(cols):
            if k < c:
                ax.add_patch(Rectangle((q, r), 1, 1, fc="#cfe8ff", ec="#1f4e79", lw=1))
                ax.text(q + .5, r + .5, str(n), ha="center", va="center", fontsize=9)
                n += 1
            else:
                ax.add_patch(Rectangle((q, r), 1, 1, fc="#eeeeee", ec="#999999", lw=1))
                ax.text(q + .5, r + .5, "-", ha="center", va="center", fontsize=9, color="#999")
            k += 1
    ax.set_title("Ekran %d  (%d kamera, 8x6=48 kanal)" % (i + 1, c), fontsize=12)
    ax.axis("off")
fig.suptitle("265 kamera - 6 ekran, 8x6 bo'linish (jami 288 kanal, 23 zaxira)", fontsize=15)
plt.tight_layout()
plt.savefig(r"D:\it-agent\data\ish\ekran_8x6.png", dpi=110)
print("ok", n - 1)
