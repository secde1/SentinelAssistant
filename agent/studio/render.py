"""Animatsion matnli vertikal video (1080x1920, 30 fps, H.264 + AAC): Pillow kadrlar -> ffmpeg.

Har sahna: rangli gradient fon (sekin parallaks harakat), katta matn (paydo bo'lish animatsiyasi), sahna belgisi,
pastda kirill subtitr (ovoz bilan aniq vaqtda), tepada progress chizig'i. Hammasi o'zimizniki — tashqi
rasm/video/musiqa yo'q, mualliflik huquqi muammosi yo'q.
"""
from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .script import ROLE_LABELS

W, H, FPS = 1080, 1920, 30
PARALLAX = 300
FADE_IN = 0.45
FONT_CANDIDATES = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
UZ_CHARS = "ЎўҚқҒғҲҳЁё"
PALETTES = {  # (yuqori rang, pastki rang, urg'u)
    "hook": ("#1a0b2e", "#c2185b", "#ffd54f"),
    "problem": ("#0d1b2a", "#1b4965", "#ff6b6b"),
    "analysis": ("#10002b", "#3c096c", "#c77dff"),
    "insight": ("#002b36", "#006d77", "#83c5be"),
    "solution": ("#0b3d20", "#1e8449", "#a8e6a3"),
    "ending": ("#1b1b2f", "#3a0ca3", "#f9c74f"),
}
_EMOJI = re.compile("[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]")


class RenderError(Exception):
    pass


@dataclass
class SubLine:
    text: str
    start: float
    end: float


@dataclass
class Scene:
    role: str
    screen: str
    start: float
    end: float
    subs: list[SubLine] = field(default_factory=list)


def find_font(preferred: str = "") -> Path:
    """O'zbek kirill harflarini (ў қ ғ ҳ) to'liq ko'rsata oladigan birinchi shrift."""
    for cand in ([preferred] if preferred else []) + FONT_CANDIDATES:
        path = Path(cand)
        if path.is_file() and not missing_glyphs(path, UZ_CHARS):
            return path
    raise RenderError("O'zbek kirill harflarini ko'rsatadigan shrift topilmadi (REELS_FONT ni ko'rsating)")


def missing_glyphs(font_path: Path, chars: str) -> str:
    """Shriftda yo'q harflar: ularning tasviri "yo'q belgi" (.notdef) tasviri bilan bir xil chiqadi."""
    font = ImageFont.truetype(str(font_path), 64)

    def signature(ch: str) -> tuple:
        mask = font.getmask(ch)
        return mask.size, bytes(mask)

    notdef = signature("\U0010FFFD")
    return "".join(c for c in chars if signature(c) == notdef)


def _hex(color: str) -> tuple[int, int, int]:
    return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))


def _clean(text: str) -> str:
    return " ".join(_EMOJI.sub("", text).split())


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(lines[-1] + " " + word, font=font) <= width:
            lines[-1] += " " + word
        else:
            lines.append(word)
    return lines


def background(role: str) -> Image.Image:
    top, bottom, accent = (_hex(c) for c in PALETTES.get(role, PALETTES["problem"]))
    h = H + PARALLAX
    grad = Image.new("RGB", (1, h))
    for y in range(h):
        k = y / (h - 1)
        grad.putpixel((0, y), tuple(int(top[i] + (bottom[i] - top[i]) * k) for i in range(3)))
    img = grad.resize((W, h))
    glow = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i, (cx, cy, r) in enumerate(((0.15, 0.18, 380), (0.9, 0.42, 300), (0.25, 0.78, 420), (0.8, 0.95, 260))):
        alpha = 70 if i % 2 == 0 else 45
        gd.ellipse([cx * W - r, cy * h - r, cx * W + r, cy * h + r], fill=(*accent, alpha))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    return Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")


def text_layer(scene: Scene, font_path: Path) -> Image.Image:
    """Sahnaning katta matni (va belgisi) — markazda, soya bilan. Shrift o'lchami matnga moslanadi."""
    layer = Image.new("RGBA", (W, 1150), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    accent = _hex(PALETTES.get(scene.role, PALETTES["problem"])[2])
    text = _clean(scene.screen)
    size = 112 if scene.role == "hook" else 96
    while True:
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap(draw, text, font, 940)
        line_h = int(size * 1.22)
        if (len(lines) <= 7 and len(lines) * line_h <= 860) or size <= 56:
            break
        size -= 6
    label = ROLE_LABELS.get(scene.role, "")
    y = (1150 - len(lines) * line_h) // 2 + (40 if label else 0)
    if label:
        lf = ImageFont.truetype(str(font_path), 40)
        lw = draw.textlength(label, font=lf)
        box = [(W - lw) / 2 - 28, y - 110, (W + lw) / 2 + 28, y - 46]
        draw.rounded_rectangle(box, radius=32, fill=(*accent, 235))
        draw.text((W / 2, (box[1] + box[3]) / 2), label, font=lf, fill=(20, 20, 30), anchor="mm")
    for i, line in enumerate(lines):
        cy = y + i * line_h + line_h // 2
        draw.text((W / 2 + 4, cy + 5), line, font=font, fill=(0, 0, 0, 140), anchor="mm")
        draw.text((W / 2, cy), line, font=font, fill=accent if (scene.role == "hook" and i == 0) else (255, 255, 255),
                  anchor="mm")
    return layer


def subtitle_image(text: str, font_path: Path) -> Image.Image:
    font = ImageFont.truetype(str(font_path), 52)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = _wrap(probe, _clean(text), font, 900)
    line_h = 68
    box_w = int(max(probe.textlength(ln, font=font) for ln in lines)) + 64
    box_h = len(lines) * line_h + 40
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, box_w - 1, box_h - 1], radius=26, fill=(0, 0, 0, 165))
    for i, ln in enumerate(lines):
        draw.text((box_w / 2, 20 + i * line_h + line_h / 2), ln, font=font, fill=(255, 255, 255), anchor="mm")
    return img


def _fade(layer: Image.Image, k: float) -> Image.Image:
    faded = layer.copy()
    faded.putalpha(layer.getchannel("A").point(lambda v: int(v * k)))
    return faded


def render(scenes: list[Scene], duration: float, audio_wav: Path, out: Path, ffmpeg: str, font_path: Path,
           brand: str = "") -> None:
    """Kadrlarni ffmpeg'ga uzatib MP4 yasaydi."""
    bgs = {i: background(sc.role) for i, sc in enumerate(scenes)}
    texts = {i: text_layer(sc, font_path) for i, sc in enumerate(scenes)}
    subs = {(i, j): subtitle_image(s.text, font_path) for i, sc in enumerate(scenes) for j, s in enumerate(sc.subs)}
    accent_of = {i: _hex(PALETTES.get(sc.role, PALETTES["problem"])[2]) for i, sc in enumerate(scenes)}
    brand_img = None
    if brand:
        bf = ImageFont.truetype(str(font_path), 34)
        brand_img = Image.new("RGBA", (W, 60), (0, 0, 0, 0))
        ImageDraw.Draw(brand_img).text((W / 2, 30), brand, font=bf, fill=(255, 255, 255, 170), anchor="mm")

    # Kam xotira: 2 oqim va qisqa lookahead — 8 GB li noutbukda boshqa dasturlar ochiq bo'lsa ham kodlanadi.
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-i", str(audio_wav), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-threads", "2", "-x264-params", "rc-lookahead=10:ref=2", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-shortest", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        frames = int(math.ceil(duration * FPS))
        for n in range(frames):
            t = n / FPS
            i = next((k for k, sc in enumerate(scenes) if sc.start <= t < sc.end), len(scenes) - 1)
            sc = scenes[i]
            span = max(0.001, sc.end - sc.start)
            local = t - sc.start
            off = int(PARALLAX * min(1.0, max(0.0, local / span)))
            frame = bgs[i].crop((0, off, W, off + H))
            k = min(1.0, local / FADE_IN)
            ease = 1 - (1 - k) ** 3
            layer = texts[i] if k >= 1 else _fade(texts[i], ease)
            frame.paste(layer, (0, 230 + int(50 * (1 - ease))), layer)
            for j, s in enumerate(sc.subs):
                if s.start - 0.05 <= t <= s.end + 0.12:
                    img = subs[(i, j)]
                    frame.paste(img, ((W - img.width) // 2, 1470), img)
                    break
            draw = ImageDraw.Draw(frame)
            draw.rectangle([0, 0, int(W * min(1.0, t / duration)), 9], fill=accent_of[i])
            if brand_img:
                frame.paste(brand_img, (0, 1830), brand_img)
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode("utf-8", "replace")
        if proc.wait(timeout=300) != 0:
            raise RenderError(f"ffmpeg xatosi: {err[-500:]}")
    except BrokenPipeError:
        err = proc.stderr.read().decode("utf-8", "replace")
        proc.kill()
        raise RenderError(f"ffmpeg kadrlarni qabul qilmadi: {err[-500:]}") from None
    finally:
        if proc.poll() is None:
            proc.kill()


@dataclass
class Probe:
    ok: bool
    problems: list[str]
    duration: float
    width: int
    height: int
    size_mb: float


def probe(path: Path, ffmpeg: str, min_s: float = 20, max_s: float = 90, max_mb: float = 49) -> Probe:
    """Sifat nazorati: H.264, 1080x1920, AAC ovoz, davomiylik va hajm (Telegram ko'rib chiqish uchun <= 49 MB)."""
    if not path.is_file():
        return Probe(False, ["video fayli yaratilmadi"], 0, 0, 0, 0)
    info = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, timeout=60)
    text = info.stderr.decode("utf-8", "replace")
    problems: list[str] = []
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", text)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    v = re.search(r"Video: (\w+).*?(\d{3,5})x(\d{3,5})", text)
    width, height = (int(v.group(2)), int(v.group(3))) if v else (0, 0)
    if not v or v.group(1) != "h264":
        problems.append("video kodeki H.264 emas")
    if (width, height) != (W, H):
        problems.append(f"o'lcham {width}x{height}, kerak {W}x{H}")
    if not re.search(r"Audio: aac", text):
        problems.append("AAC ovoz yo'lagi yo'q")
    if not min_s <= duration <= max_s:
        problems.append(f"davomiylik {duration:.1f} s — {min_s:.0f}..{max_s:.0f} s oralig'ida bo'lishi kerak")
    size_mb = path.stat().st_size / 1_048_576
    if size_mb > max_mb:
        problems.append(f"hajm {size_mb:.1f} MB > {max_mb:.0f} MB")
    return Probe(not problems, problems, duration, width, height, size_mb)
