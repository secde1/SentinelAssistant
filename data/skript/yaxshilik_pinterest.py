import numpy as np, random, textwrap
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1080, 1350
random.seed(7); np.random.seed(7)

def lerp(a, b, t):
    return a + (b - a) * t

# --- osmon gradienti (tepa: to'q ko'k-yashil -> ufq: iliq shaftoli) ---
top = np.array([22, 40, 62]); mid = np.array([120, 110, 140]); hor = np.array([255, 190, 140])
y = np.linspace(0, 1, H)[:, None, None]
sky = np.where(y < 0.5, lerp(top, mid, y / 0.5), lerp(mid, hor, (y - 0.5) / 0.3).clip(0, 255))
sky = np.where(y > 0.8, hor, sky)
img = np.repeat(sky, W, axis=1).astype(float)

# --- quyosh nuri ---
cx, cy = W * 0.62, H * 0.58
yy, xx = np.mgrid[0:H, 0:W]
d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
glow = np.exp(-(d / 330) ** 2)[..., None] * np.array([255, 215, 160]) * 0.9
core = np.exp(-(d / 70) ** 2)[..., None] * np.array([255, 245, 225])
img = np.clip(img + glow * 0.8 + core, 0, 255)

# --- tog' qatlamlari ---
def ridge(base, amp, seed):
    r = random.Random(seed)
    ph = [r.uniform(0, 6.28) for _ in range(5)]
    fr = [0.004, 0.009, 0.019, 0.04, 0.09]
    am = [1, 0.55, 0.3, 0.12, 0.05]
    x = np.arange(W)
    h = sum(a * np.sin(x * f + p) for a, f, p in zip(am, fr, ph))
    return base + amp * h

haze = np.array([245, 200, 165])
layers = 6
for i in range(layers):
    t = i / (layers - 1)
    base = H * (0.58 + 0.07 * i)
    prof = ridge(base, 55 - 4 * i, 10 + i)
    col = lerp(np.array([150, 120, 140]), np.array([14, 26, 32]), t ** 1.1)
    mask = (yy > prof[None, :]).astype(float)
    m = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2 + (layers - i) * 0.5))
    m = np.array(m)[..., None] / 255.0
    # tog' ichida tepadan pastga tuman
    fade = np.clip((yy - prof[None, :]) / 260.0, 0, 1)[..., None]
    layercol = lerp(col, lerp(haze * 0.55, col, 0.5), 0) * np.ones((H, W, 3))
    layercol = layercol * (0.78 + 0.22 * fade) + haze * (0.22 * (1 - fade)) * (1 - t)
    img = img * (1 - m) + layercol * m

# --- daraxt siluetlari old planda ---
im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
dr = ImageDraw.Draw(im)
rr = random.Random(3)
for k in range(26):
    x0 = rr.randint(-20, 330) if k % 2 == 0 else rr.randint(760, 1100)
    hh = rr.randint(160, 420)
    base_y = H + 10
    wd = hh * 0.28
    for j in range(7):
        yt = base_y - hh + j * hh / 7
        w2 = wd * (j + 1) / 7
        dr.polygon([(x0, yt - hh / 9), (x0 - w2, yt + hh / 6), (x0 + w2, yt + hh / 6)], fill=(8, 16, 18))
    dr.rectangle([x0 - 3, base_y - hh / 7, x0 + 3, base_y], fill=(8, 16, 18))
im = im.filter(ImageFilter.GaussianBlur(0.6))

# --- vinyetka + donador (film effekti) ---
a = np.array(im).astype(float)
v = 1 - 0.38 * (np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) ** 2.2)
a *= np.clip(v, 0.5, 1)[..., None]
a += np.random.normal(0, 5, (H, W, 1))
# tepani matn uchun biroz qoraytirish
a *= (1 - 0.35 * np.clip(1 - yy / (H * 0.5), 0, 1))[..., None]
im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")

# --- matn ---
F = "C:/Windows/Fonts/"
fb = ImageFont.truetype(F + "georgiai.ttf", 74)
fs = ImageFont.truetype(F + "georgia.ttf", 30)
lines = ["Албатта,", "яхшиликлар", "ёмонликларни", "кетказади"]
ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
od = ImageDraw.Draw(ov)
yy0 = 170
for ln in lines:
    w = od.textlength(ln, font=fb)
    od.text(((W - w) / 2 + 3, yy0 + 4), ln, font=fb, fill=(0, 0, 0, 140))
    yy0 += 98
ov = ov.filter(ImageFilter.GaussianBlur(5))
im = Image.alpha_composite(im, ov)
d2 = ImageDraw.Draw(im)
yy0 = 170
for ln in lines:
    w = d2.textlength(ln, font=fb)
    d2.text(((W - w) / 2, yy0), ln, font=fb, fill=(255, 248, 236, 255))
    yy0 += 98
d2.line([(W / 2 - 50, yy0 + 25), (W / 2 + 50, yy0 + 25)], fill=(255, 214, 150, 255), width=3)
cap = "Х И К М А Т"
w = d2.textlength(cap, font=fs)
d2.text(((W - w) / 2, yy0 + 50), cap, font=fs, fill=(255, 226, 180, 255))

im.convert("RGB").save("D:/it-agent/data/ish/yaxshilik_pinterest.jpg", quality=95)
print("OK")
