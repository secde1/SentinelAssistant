"""Animatsion Reels renderer (Pillow + numpy -> ffmpeg pipe). Ishlatish: python reel_anim.py CHIQISH_PAPKA
TTS: edge-tts (uz Madina), temp D: da. Mavzu: bolalar va ekran vaqti (JSST 2019)."""
import asyncio, math, os, subprocess, sys, wave, random
from pathlib import Path
import numpy as np
import edge_tts, imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
tmp = out / "tmp"; tmp.mkdir(exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1080, 1920, 30
FB = r"C:\Windows\Fonts\segoeuib.ttf"; FR = r"C:\Windows\Fonts\segoeui.ttf"
f = lambda p, s: ImageFont.truetype(p, s)

SC = [
 dict(kind="hook", title="Болангиз кунига неча соат экранга қарайди?",
      say="Bolangiz kuniga necha soat ekranga qaraydi? Javob sizni hayron qoldirishi mumkin."),
 dict(kind="zero", title="1 ёшгача экран тавсия этилмайди", sub="ЖССТ, 2019",
      say="Jahon sog'liqni saqlash tashkiloti 2019 yilda aniq tavsiya berdi. Bir yoshgacha bolalar uchun ekran umuman tavsiya etilmaydi."),
 dict(kind="bars", title="Ёшга қараб кунлик чегара",
      say="Bir yoshda ham o'tirib ko'riladigan ekran tavsiya etilmaydi. Ikki yoshdan to'rt yoshgacha esa kuniga ko'pi bilan bir soat, kamroq bo'lsa yanada yaxshi."),
 dict(kind="icons", title="Экран ўрнига нима?",
      say="Ekran o'rniga nima qilish mumkin? O'yin, kitob, harakat va oddiy suhbat. Bola uchun eng foydali narsa sizning e'tiboringiz."),
 dict(kind="end", title="Бугун болангиз билан экрансиз неча дақиқа ўтказдингиз?",
      say="Bugun bolangiz bilan ekransiz necha daqiqa o'tkazdingiz? Fikringizni izohda yozing."),
]

async def tts(t, p): await edge_tts.Communicate(t, "uz-UZ-MadinaNeural", rate="-4%").save(str(p))

def load_wav(p):
    with wave.open(str(p)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()

SR = 44100; chunks = []; durs = []
for i, s in enumerate(SC):
    mp3 = tmp / f"s{i}.mp3"; wv = tmp / f"s{i}.wav"
    asyncio.run(tts(s["say"], mp3))
    subprocess.run([FF, "-y", "-i", str(mp3), "-ar", str(SR), "-ac", "1", str(wv)], check=True, capture_output=True)
    a, _ = load_wav(wv)
    pad = np.zeros(int(SR * 0.7), dtype=np.int16)
    a = np.concatenate([np.zeros(int(SR*0.3), dtype=np.int16), a, pad])
    chunks.append(a); durs.append(len(a) / SR)
audio = np.concatenate(chunks)
awav = tmp / "audio.wav"
with wave.open(str(awav), "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(audio.tobytes())
total = sum(durs); NF = int(total * FPS)
starts = np.cumsum([0] + durs)

ease = lambda x: 1 - (1 - min(1, max(0, x))) ** 3
PAL = [((20, 24, 60), (90, 40, 140)), ((10, 50, 70), (20, 120, 130)), ((40, 20, 70), (200, 80, 110)),
       ((15, 60, 50), (60, 160, 90)), ((30, 25, 80), (220, 120, 60))]
yy = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
random.seed(4)
parts = [(random.random() * W, random.random() * H, random.uniform(6, 24), random.uniform(20, 70), random.random() * 6) for _ in range(28)]

def bg(t, si, lt):
    c1 = np.array(PAL[si][0], np.float32); c2 = np.array(PAL[si][1], np.float32)
    sh = 0.5 + 0.5 * math.sin(t * 0.8)
    g = (c1 * (1 - yy * (0.6 + 0.4 * sh)) + c2 * (yy * (0.6 + 0.4 * sh))) if False else c1 + (c2 - c1) * (yy ** 1.3) * (0.7 + 0.3 * sh)
    img = Image.fromarray(np.broadcast_to(g, (H, W, 3)).astype(np.uint8))
    d = ImageDraw.Draw(img)
    for x, y, r, sp, ph in parts:
        py = (y - t * sp) % (H + 60) - 30; px = x + 25 * math.sin(t + ph)
        col = tuple(int(min(255, v + 45)) for v in PAL[si][1])
        d.ellipse([px - r, py - r, px + r, py + r], outline=col, width=2)
    return img, d

def wrap(d, text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        tt = (cur + " " + w).strip()
        if d.textlength(tt, font=font) <= maxw: cur = tt
        else: lines.append(cur); cur = w
    lines.append(cur); return lines

def text_block(img, d, text, y, font, lt, col=(255, 255, 255), maxw=900):
    a = ease(lt / 0.6); off = int((1 - a) * 60)
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ld = ImageDraw.Draw(lay)
    yy_ = y + off
    for ln in wrap(d, text, font, maxw):
        w = ld.textlength(ln, font=font)
        ld.text(((W - w) / 2 + 3, yy_ + 4), ln, font=font, fill=(0, 0, 0, int(120 * a)))
        ld.text(((W - w) / 2, yy_), ln, font=font, fill=col + (int(255 * a),))
        yy_ += int(font.size * 1.3)
    img.paste(lay, (0, 0), lay)

def frame(n):
    t = n / FPS
    si = max(0, int(np.searchsorted(starts, t, side="right") - 1)); si = min(si, len(SC) - 1)
    lt = t - starts[si]; sc = SC[si]; k = sc["kind"]
    img, d = bg(t, si, lt)
    big = f(FB, 74); mid = f(FB, 60)
    if k == "hook":
        text_block(img, d, sc["title"], 240, big, lt)
        s = 1 + 0.05 * math.sin(lt * 5); cx, cy = W // 2, 1150; pw, ph = int(380 * s), int(700 * s)
        d.rounded_rectangle([cx - pw // 2, cy - ph // 2, cx + pw // 2, cy + ph // 2], 50, fill=(25, 25, 40), outline=(255, 255, 255), width=8)
        n_ = int(ease(lt / 2.5) * 12 * 10) / 10
        hrs = f"{n_:.0f}"; fq = f(FB, 190); q = "?" if lt > 2.5 else hrs
        w = d.textlength(q, font=fq); d.text((cx - w / 2, cy - 130), q, font=fq, fill=(255, 220, 90))
    elif k == "zero":
        text_block(img, d, sc["title"], 240, big, lt)
        r = int(300 + 25 * math.sin(lt * 4)); cx, cy = W // 2, 1100
        for i, rr in enumerate([r, r - 60]):
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(255, 255, 255), width=10 - 4 * i)
        fz = f(FB, 330); a = ease(lt / 0.8); w = d.textlength("0", font=fz)
        d.text((cx - w / 2, cy - 230 + (1 - a) * 80), "0", font=fz, fill=(255, 220, 90))
        text_block(img, d, sc["sub"], 1520, f(FR, 52), lt - 1, (220, 220, 240))
    elif k == "bars":
        text_block(img, d, sc["title"], 240, big, lt)
        data = [("1 ёш", 0.05, "тавсия этилмайди"), ("2 ёш", 1, "1 соат"), ("3-4 ёш", 1, "1 соат")]
        fl = f(FB, 52); fs = f(FR, 46)
        for i, (lab, v, cap) in enumerate(data):
            x0 = 130 + i * 300; a = ease((lt - 0.6 - i * 0.5) / 1.2); hh = int(700 * v * a)
            base = 1500
            col = (255, 120, 120) if v < 0.1 else (120, 230, 160)
            d.rounded_rectangle([x0, base - max(hh, 8), x0 + 220, base], 24, fill=col)
            w = d.textlength(lab, font=fl); d.text((x0 + 110 - w / 2, base + 20), lab, font=fl, fill=(255, 255, 255))
            if a > 0.9:
                for j, ln in enumerate(wrap(d, cap, fs, 280)):
                    w = d.textlength(ln, font=fs); d.text((x0 + 110 - w / 2, base - max(hh, 8) - 70 + j * -0 - (len(wrap(d, cap, fs, 280)) - 1) * 52 + j * 52), ln, font=fs, fill=(255, 255, 255))
    elif k == "icons":
        text_block(img, d, sc["title"], 240, big, lt)
        labs = [("Ўйин", (255, 200, 80)), ("Китоб", (120, 200, 255)), ("Ҳаракат", (255, 120, 140)), ("Суҳбат", (170, 255, 170))]
        fl = f(FB, 54)
        for i, (lab, col) in enumerate(labs):
            a = ease((lt - 0.5 - i * 0.7) / 0.6); cx = 300 + (i % 2) * 480; cy = 800 + (i // 2) * 440
            r = int(170 * a * (1 + 0.04 * math.sin(lt * 4 + i)))
            if r > 5:
                d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
                dk = (30, 30, 60)
                if i == 0: d.polygon([(cx - 50, cy - 70), (cx - 50, cy + 70), (cx + 70, cy)], fill=dk)
                if i == 1:
                    d.rectangle([cx - 80, cy - 60, cx - 5, cy + 60], fill=dk); d.rectangle([cx + 5, cy - 60, cx + 80, cy + 60], fill=dk)
                if i == 2:
                    d.ellipse([cx - 25, cy - 90, cx + 25, cy - 40], fill=dk); d.line([cx, cy - 40, cx, cy + 30], fill=dk, width=14)
                    d.line([cx, cy + 30, cx - 40, cy + 90], fill=dk, width=14); d.line([cx, cy + 30, cx + 40, cy + 90], fill=dk, width=14)
                    d.line([cx - 55, cy - 10, cx + 55, cy - 10], fill=dk, width=14)
                if i == 3:
                    d.rounded_rectangle([cx - 85, cy - 60, cx + 85, cy + 40], 30, fill=dk); d.polygon([(cx - 30, cy + 35), (cx - 60, cy + 85), (cx + 10, cy + 40)], fill=dk)
                w = d.textlength(lab, font=fl); d.text((cx - w / 2, cy + r + 15), lab, font=fl, fill=(255, 255, 255))
    else:
        text_block(img, d, sc["title"], 420, big, lt, maxw=920)
        cx, cy = W // 2, 1300; s = 1 + 0.08 * math.sin(lt * 5); r = int(150 * s)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 220, 90))
        d.arc([cx - 100, cy - 60, cx + 100, cy + 100], 20, 160, fill=(60, 40, 20), width=14)
        d.ellipse([cx - 60, cy - 50, cx - 35, cy - 15], fill=(60, 40, 20)); d.ellipse([cx + 35, cy - 50, cx + 60, cy - 15], fill=(60, 40, 20))
    # progress bar
    d.rounded_rectangle([90, 1810, 990, 1824], 7, fill=(255, 255, 255, 60) if False else (80, 80, 110))
    d.rounded_rectangle([90, 1810, 90 + int(900 * t / total), 1824], 7, fill=(255, 220, 90))
    return img

video = out / "anim_noaudio.mp4"
p = subprocess.Popen([FF, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "720x1280", "-r", str(FPS), "-i", "-",
                      "-c:v", "libx264", "-preset", "ultrafast", "-bf", "0", "-refs", "1", "-threads", "1", "-x264-params", "rc-lookahead=0:threads=1:lookahead-threads=1:sync-lookahead=0:no-mbtree=1", "-crf", "23", "-pix_fmt", "yuv420p", str(video)],
                     stdin=subprocess.PIPE, stderr=open(out / "ff.log", "wb"))
for n in range(NF):
    import gc, time
    for _try in range(200):
        try:
            b = frame(n).resize((720, 1280), Image.LANCZOS).tobytes(); break
        except MemoryError:
            gc.collect(); time.sleep(1.5)
    else:
        raise MemoryError("frame %d" % n)
    for i in range(0, len(b), 1 << 20):
        p.stdin.write(b[i:i + (1 << 20)])
    p.stdin.flush()
p.stdin.close(); p.wait()
final = out / "reel_animatsion.mp4"
subprocess.run([FF, "-y", "-i", str(video), "-i", str(awav), "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(final)],
               check=True, capture_output=True)
print(final, f"{total:.1f}s", final.stat().st_size)






