from PIL import Image, ImageDraw, ImageFilter
import math, sys

S = 1080
out = sys.argv[1]
img = Image.new("RGB", (S, S), (8, 14, 30))
px = img.load()
# radial gradient background
for y in range(S):
    for x in range(S):
        d = math.hypot(x - S / 2, y - S / 2) / (S * 0.7)
        t = min(1, d)
        px[x, y] = (int(14 + (4 - 14) * t), int(40 + (8 - 40) * t), int(70 + (20 - 70) * t))

# glow
glow = Image.new("RGB", (S, S), (0, 0, 0))
g = ImageDraw.Draw(glow)
cx, cy = S // 2, S // 2
shield = [(cx, 170), (cx + 270, 260), (cx + 270, 560), (cx, 900), (cx - 270, 560), (cx - 270, 260)]
g.polygon(shield, fill=(0, 255, 170))
glow = glow.filter(ImageFilter.GaussianBlur(60))
img = Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.55)

d = ImageDraw.Draw(img)
# shield outer + inner
d.polygon(shield, fill=(0, 230, 160))
inner = [(cx, 210), (cx + 235, 288), (cx + 235, 552), (cx, 852), (cx - 235, 552), (cx - 235, 288)]
d.polygon(inner, fill=(10, 28, 52))

# DNA-like double helix inside
for i in range(0, 600):
    t = i / 600
    y = 300 + t * 460
    a = t * 4 * math.pi
    x1 = cx + 95 * math.sin(a)
    x2 = cx - 95 * math.sin(a)
    r1 = 7 + 4 * math.cos(a)
    r2 = 7 - 4 * math.cos(a)
    d.ellipse([x1 - r1, y - r1, x1 + r1, y + r1], fill=(0, 240, 170))
    d.ellipse([x2 - r2, y - r2, x2 + r2, y + r2], fill=(90, 170, 255))
    if i % 35 == 0:
        d.line([(x1, y), (x2, y)], fill=(180, 230, 255), width=4)

# medical cross badge
bx, by = cx + 170, cy + 250
d.ellipse([bx - 80, by - 80, bx + 80, by + 80], fill=(0, 230, 160), outline=(8, 14, 30), width=8)
d.rectangle([bx - 14, by - 46, bx + 14, by + 46], fill=(8, 14, 30))
d.rectangle([bx - 46, by - 14, bx + 46, by + 14], fill=(8, 14, 30))

# circle ring (works well for round crop)
d.ellipse([20, 20, S - 20, S - 20], outline=(0, 230, 160), width=10)
img.save(out, quality=95)
print("OK", out)
