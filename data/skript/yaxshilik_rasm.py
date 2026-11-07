from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os, random

W, H = 1080, 1350
out = r"D:\it-agent\data\ish\yaxshilik.jpg"
text = "Албатта, яхшиликлар ёмонликларни кетказади"

# gradient fon (тўқ яшил -> қора)
img = Image.new("RGB", (W, H))
px = img.load()
for y in range(H):
    t = y / H
    r = int(10 + 8 * (1 - t)); g = int(60 * (1 - t) + 18); b = int(50 * (1 - t) + 20)
    for x in range(W):
        px[x, y] = (r, g, b)

# юмшоқ ёруғлик доираси
glow = Image.new("RGB", (W, H), (0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse((W//2-420, H//2-420, W//2+420, H//2+420), fill=(60, 110, 80))
glow = glow.filter(ImageFilter.GaussianBlur(160))
img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.5)

# юлдузчалар
d = ImageDraw.Draw(img)
random.seed(7)
for _ in range(70):
    x, y, s = random.randint(0, W), random.randint(0, H), random.randint(1, 3)
    d.ellipse((x, y, x+s, y+s), fill=(230, 210, 150))

def font(names, size):
    for n in names:
        p = os.path.join(r"C:\Windows\Fonts", n)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()

f = font(["georgiaz.ttf", "georgiab.ttf", "georgia.ttf", "timesbd.ttf"], 82)

# қаторларга бўлиш
words, lines, cur = text.split(), [], ""
for w in words:
    t = (cur + " " + w).strip()
    if d.textlength(t, font=f) <= W - 180:
        cur = t
    else:
        lines.append(cur); cur = w
lines.append(cur)

lh = 115
total = lh * len(lines)
y0 = (H - total) // 2
gold = (232, 196, 110)
for i, ln in enumerate(lines):
    x = (W - d.textlength(ln, font=f)) // 2
    y = y0 + i * lh
    d.text((x+3, y+4), ln, font=f, fill=(0, 0, 0))
    d.text((x, y), ln, font=f, fill=gold)

# безак чизиқлар
d.line((W//2-140, y0-60, W//2+140, y0-60), fill=gold, width=3)
d.line((W//2-140, y0+total+30, W//2+140, y0+total+30), fill=gold, width=3)

img.save(out, quality=94)
print("OK", img.size, os.path.getsize(out))
