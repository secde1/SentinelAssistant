from PIL import Image, ImageDraw, ImageFilter, ImageFont
import math, sys, os

W, H = 1080, 1350
out = sys.argv[1]
img = Image.new("RGB", (W, H), (8, 14, 30))
px = img.load()
for y in range(H):
    for x in range(W):
        d = min(1, math.hypot(x - W / 2, y - H * 0.4) / (W * 0.9))
        px[x, y] = (int(14 - 10 * d), int(44 - 36 * d), int(78 - 58 * d))

d = ImageDraw.Draw(img)
cx = W // 2
# shield
sh = [(cx, 140), (cx + 190, 205), (cx + 190, 415), (cx, 650), (cx - 190, 415), (cx - 190, 205)]
glow = Image.new("RGB", (W, H), (0, 0, 0))
ImageDraw.Draw(glow).polygon(sh, fill=(0, 255, 170))
glow = glow.filter(ImageFilter.GaussianBlur(50))
img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.5)
d = ImageDraw.Draw(img)
d.polygon(sh, fill=(0, 230, 160))
inn = [(cx, 172), (cx + 165, 228), (cx + 165, 405), (cx, 612), (cx - 165, 405), (cx - 165, 228)]
d.polygon(inn, fill=(10, 28, 52))
for i in range(500):
    t = i / 500
    y = 230 + t * 340
    a = t * 4 * math.pi
    x1, x2 = cx + 70 * math.sin(a), cx - 70 * math.sin(a)
    r1, r2 = 6 + 3 * math.cos(a), 6 - 3 * math.cos(a)
    d.ellipse([x1 - r1, y - r1, x1 + r1, y + r1], fill=(0, 240, 170))
    d.ellipse([x2 - r2, y - r2, x2 + r2, y + r2], fill=(90, 170, 255))
    if i % 30 == 0:
        d.line([(x1, y), (x2, y)], fill=(180, 230, 255), width=3)

def font(sz, bold=True):
    for f in ("arialbd.ttf" if bold else "arial.ttf", "segoeuib.ttf", "calibrib.ttf"):
        try:
            return ImageFont.truetype(os.path.join("C:/Windows/Fonts", f), sz)
        except Exception:
            pass
    return ImageFont.load_default()

def center(txt, y, f, fill):
    w = d.textlength(txt, font=f)
    d.text(((W - w) / 2, y), txt, font=f, fill=fill)

center("РАҚАМЛИ АНТИДОТ", 720, font(84), (0, 235, 165))
center("Ижтимоий антивирус", 830, font(60), (230, 240, 255))
d.line([(300, 930), (780, 930)], fill=(0, 230, 160), width=5)
for i, t in enumerate(["Ёлғон маълумот", "Кибербуллинг", "Рақамли қарамлик"]):
    center(t, 970 + i * 70, font(46, False), (170, 200, 235))
center("Ҳар ҳафта янги антидот", 1230, font(48), (0, 235, 165))
d.rectangle([20, 20, W - 20, H - 20], outline=(0, 230, 160), width=6)
img.save(out, quality=95)
print("OK", out)
