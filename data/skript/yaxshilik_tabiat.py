from PIL import Image, ImageDraw, ImageFont, ImageFilter
import os, random, math

W, H = 1080, 1350
out = r"D:\it-agent\data\ish\yaxshilik_tabiat.jpg"
text = "Албатта, яхшиликлар ёмонликларни кетказади"
random.seed(11)

def lerp(a, b, t): return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))

# осмон: тепада тўқ кўк/кулранг (ёмонлик) -> пастда олтин тонг (яхшилик)
img = Image.new("RGB", (W, H))
d = ImageDraw.Draw(img)
horizon = 800
stops = [(0, (28, 36, 58)), (0.35, (70, 90, 120)), (0.7, (240, 170, 100)), (1.0, (255, 225, 150))]
for y in range(horizon):
    t = y / horizon
    for i in range(len(stops)-1):
        if stops[i][0] <= t <= stops[i+1][0]:
            tt = (t - stops[i][0]) / (stops[i+1][0] - stops[i][0])
            d.line((0, y, W, y), fill=lerp(stops[i][1], stops[i+1][1], tt))
            break

# қуёш ва нур
sun = Image.new("RGB", (W, H), (0, 0, 0))
sd = ImageDraw.Draw(sun)
sx, sy = W//2, horizon - 40
sd.ellipse((sx-300, sy-300, sx+300, sy+300), fill=(255, 190, 110))
sun = sun.filter(ImageFilter.GaussianBlur(120))
img = Image.composite(Image.blend(img, sun, 0.0), img, Image.new("L", (W, H), 255))
from PIL import ImageChops
img = ImageChops.add(img, sun)
d = ImageDraw.Draw(img)
d.ellipse((sx-70, sy-70, sx+70, sy+70), fill=(255, 245, 205))

# қора булутлар (тарқалаётган)
clouds = Image.new("RGBA", (W, H), (0, 0, 0, 0))
cd = ImageDraw.Draw(clouds)
for _ in range(14):
    cx = random.choice([random.randint(-100, 300), random.randint(780, 1180)])
    cy = random.randint(60, 420)
    for _ in range(8):
        r = random.randint(60, 130)
        ox, oy = random.randint(-120, 120), random.randint(-30, 30)
        cd.ellipse((cx+ox-r, cy+oy-r//2, cx+ox+r, cy+oy+r//2), fill=(35, 42, 62, 150))
clouds = clouds.filter(ImageFilter.GaussianBlur(35))
img.paste(clouds, (0, 0), clouds)

# тоғлар қатламлари
def hills(base, amp, color, seed, freq):
    random.seed(seed)
    ph = [random.random()*6.28 for _ in range(3)]
    pts = [(0, H)]
    for x in range(0, W+10, 10):
        y = base + amp*math.sin(x/freq + ph[0]) + amp*0.5*math.sin(x/(freq*0.4) + ph[1]) + amp*0.25*math.sin(x/(freq*0.17)+ph[2])
        pts.append((x, y))
    pts.append((W, H))
    ImageDraw.Draw(img).polygon(pts, fill=color)

hills(790, 40, (120, 120, 140), 1, 140)
hills(850, 45, (70, 100, 90), 2, 120)
hills(930, 40, (40, 85, 55), 3, 100)
hills(1040, 35, (25, 60, 35), 4, 90)

# дарахт
d = ImageDraw.Draw(img)
tx, ty = 220, 1010
d.polygon([(tx-14, 1110), (tx+14, 1110), (tx+8, ty), (tx-8, ty)], fill=(30, 22, 16))
foliage = Image.new("RGBA", (W, H), (0, 0, 0, 0))
fd = ImageDraw.Draw(foliage)
for _ in range(60):
    a = random.random()*6.28; r = random.random()*110
    x = tx + math.cos(a)*r; y = ty - 60 + math.sin(a)*r*0.8
    s = random.randint(30, 55)
    g = random.randint(70, 130)
    fd.ellipse((x-s, y-s, x+s, y+s), fill=(30, g, 45, 255))
img.paste(foliage, (0, 0), foliage)

# гуллар
d = ImageDraw.Draw(img)
random.seed(5)
for _ in range(90):
    x = random.randint(0, W); y = random.randint(1080, H-10)
    c = random.choice([(255, 225, 120), (255, 255, 255), (240, 150, 170)])
    d.line((x, y, x, y+14), fill=(30, 90, 40), width=2)
    d.ellipse((x-4, y-4, x+4, y+4), fill=c)

# матн учун қоронғилаштириш (пастки)
shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
sh = ImageDraw.Draw(shade)
sh.rectangle((0, 120, W, 560), fill=(0, 0, 0, 0))
img = img.convert("RGBA")
panel = Image.new("RGBA", (W, H), (0, 0, 0, 0))
pd = ImageDraw.Draw(panel)
pd.rounded_rectangle((60, 90, W-60, 520), 30, fill=(10, 15, 25, 120))
img = Image.alpha_composite(img, panel).convert("RGB")
d = ImageDraw.Draw(img)

def font(names, size):
    for n in names:
        p = os.path.join(r"C:\Windows\Fonts", n)
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()
f = font(["georgiab.ttf", "georgiaz.ttf", "timesbd.ttf"], 70)

lines, cur = [], ""
for w in text.split():
    t = (cur + " " + w).strip()
    if d.textlength(t, font=f) <= W - 200: cur = t
    else: lines.append(cur); cur = w
lines.append(cur)
lh = 95; total = lh*len(lines); y0 = 90 + (430 - total)//2
for i, ln in enumerate(lines):
    x = (W - d.textlength(ln, font=f))//2; y = y0 + i*lh
    d.text((x+3, y+4), ln, font=f, fill=(0, 0, 0))
    d.text((x, y), ln, font=f, fill=(255, 236, 190))

img.save(out, quality=94)
print("OK", img.size, os.path.getsize(out))
