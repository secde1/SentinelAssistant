"""Ustki panel (oynacha) — coucou uslubidagi notch, Pillow bilan chizilgan silliq dizayn.

coucou kabi: ekran tepa-o'rtasiga yopishgan qora notch (yuqori chet tekis, pastki burchaklar dumaloq).
Bo'sh turganda yashirinadi; tepa chetga sichqoncha tegsa mo'ralaydi; ish/tasdiq bo'lsa tushadi; bosilsa ochiladi.
Butun yuza Pillow bilan rasm qilib chiziladi — gradient fon, silliq burchaklar, yaltiroq maskot (ko'zida nur,
ishlaganda ореол), dumaloq "chip"lar va tugmalar. Faqat matn kiritish maydoni — haqiqiy widget (ustiga qo'yiladi).

Ranglar coucou palitrasidan: kutyapti #f29b38, ishlayapti #38bdf8, tayyor #4ade80, xato #f4505e. Fon qora.
coucou'ning "Mochi" personaji/nomi/ikonkasi KO'CHIRILMADI — o'z maskotimiz va "Sentinel" nomi.

Mahalliy (127.0.0.1) + token. Ishga tushirish: oynacha.cmd
"""
from __future__ import annotations

import json
import math
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .config import Config
from .workspace import Paths

KEY = "#010203"       # shaffoflik kaliti (deyarli qora -> AA cheti bilinmaydi)
ISLAND_TOP = (28, 31, 38)
ISLAND_BOT = (9, 10, 13)
ISLAND_MID = (18, 20, 25)
FG = (245, 246, 248)
DIM = (140, 146, 156)
READY = (74, 222, 128)    # tayyor (yashil)  — coucou palitrasi
WORK = (56, 189, 248)     # ishlayapti (ko'k)
WAIT = (242, 155, 56)     # kutyapti (to'q sariq)
BAD = (244, 80, 94)       # xato/limit (qizil)
OFF = (120, 128, 140)     # o'chiq (kulrang)

WIDE_W = 672
PADX = 18
HBAND = 54
MASCOT = 30
POLL_MS = 1500
SIZES = {"hidden": (196, 9), "peek": (268, 50), "compact": (392, 58)}
RADIUS = {"hidden": 8, "peek": 16, "compact": 16, "expanded": 24}


def _lerp(a, b, t):
    return (int(a[0] + (b[0] - a[0]) * t), int(a[1] + (b[1] - a[1]) * t), int(a[2] + (b[2] - a[2]) * t))


def _hexf(c):
    return f"#{c[0]:02x}{c[1]:02x}{c[2]:02x}"


class AgentPanel:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.state: dict = {}
        self.err = "ulanmoqda…"
        self.strong = False
        self.mode = "hidden"
        self.lock_open = False
        self.hover = False
        self._collapse_job = None
        self._phase = 0.0
        self._blink = 0
        self._wave = 0
        self._cur = OFF
        self._title = "Sentinel"
        self._sub = ""
        self._hits: list = []
        self._mascot_pos = (PADX, 12)
        self._fonts: dict = {}
        self._island_img = None
        self._photo = None
        self._mascot_photo = None
        self._build()
        self._pin()
        self._animate()
        self._schedule_poll()

    # ============================================================ shriftlar
    def _font(self, size, w="r"):
        key = (size, w)
        if key in self._fonts:
            return self._fonts[key]
        files = {"r": "segoeui.ttf", "sb": "seguisb.ttf", "b": "segoeuib.ttf"}
        try:
            f = ImageFont.truetype(f"C:/Windows/Fonts/{files[w]}", size)
        except OSError:
            try:
                f = ImageFont.truetype(files[w], size)
            except OSError:
                f = ImageFont.load_default()
        self._fonts[key] = f
        return f

    # ============================================================ server (mahalliy)
    def _control_info(self):
        try:
            info = json.loads((self.paths.ish / "control.json").read_text(encoding="utf-8"))
            return info.get("port"), info.get("token")
        except Exception:  # noqa: BLE001
            return None, None

    def _get_state(self):
        port, token = self._control_info()
        if not port or not token:
            return None, "agent topilmadi"
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"X-Token": token})
            with urllib.request.urlopen(req, timeout=3) as r:
                return json.loads(r.read().decode("utf-8")), ""
        except urllib.error.URLError:
            return None, "aloqa yo'q"
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)[:50]

    def _post(self, path: str, payload: dict) -> dict:
        port, token = self._control_info()
        if not port or not token:
            return {"error": "agent o'chiq"}
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data,
                                         headers={"X-Token": token, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:60]}

    # ============================================================ qurilish
    def _build(self):
        self.root = tk.Tk()
        self.root.title("Sentinel")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.root.configure(bg=KEY)
        self.sw = self.root.winfo_screenwidth()
        self.canvas = tk.Canvas(self.root, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self._img_id = self.canvas.create_image(0, 0, anchor="nw")
        self._mascot_id = self.canvas.create_image(0, 0, anchor="nw")

        self.entry = tk.Entry(self.canvas, bg=_hexf(_lerp(ISLAND_MID, (255, 255, 255), 0.06)), fg=_hexf(FG),
                              insertbackground=_hexf(FG), relief="flat", font=("Segoe UI", 11), highlightthickness=0)
        self.entry.bind("<Return>", lambda e: self._send_task())
        self._entry_win = self.canvas.create_window(0, 0, anchor="nw", window=self.entry, state="hidden")

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        for w in (self.root, self.canvas):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        self.x = (self.sw - SIZES["hidden"][0]) // 2
        self.y = 0
        self.w, self.h = SIZES["hidden"]
        self._apply_geometry(*SIZES["hidden"])
        self._compose()
        self._show_island()

    def _pin(self):
        try:
            self.root.attributes("-topmost", False)
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after(3000, self._pin)

    def _apply_geometry(self, w, h):
        self.w, self.h = int(w), int(h)
        self.x = max(0, min(self.x, self.sw - self.w))
        self.root.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

    # ============================================================ orol shakli (silliq)
    def _island_base(self, W, H, r):
        S = 3
        mask = Image.new("L", (W * S, H * S), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, W * S - 1, H * S - 1], radius=r * S,
                                               corners=(False, False, True, True), fill=255)
        mask = mask.resize((W, H), Image.LANCZOS)
        grad = Image.new("RGBA", (W, H))
        gd = ImageDraw.Draw(grad)
        for y in range(H):
            gd.line([(0, y), (W, y)], fill=_lerp(ISLAND_TOP, ISLAND_BOT, y / max(1, H - 1)) + (255,))
        base = Image.composite(grad, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask)
        d = ImageDraw.Draw(base)
        d.line([(2, 1), (W - 3, 1)], fill=(255, 255, 255, 30))   # yuqori "shisha" yorug'i
        return base, d

    # ============================================================ kichik chizuvchilar
    def _chip(self, d, x, y, text, dot=None, h=20):
        f = self._font(11, "sb")
        tw = d.textlength(text, font=f)
        pad = 9
        extra = 15 if dot else 0
        w = int(tw + pad * 2 + extra)
        fill = _lerp(ISLAND_MID, (255, 255, 255), 0.08)
        d.rounded_rectangle([x, y, x + w, y + h], radius=h // 2, fill=fill)
        tx = x + pad
        if dot:
            cy = y + h / 2
            d.ellipse([tx, cy - 3.5, tx + 7, cy + 3.5], fill=dot)
            tx += extra
        d.text((tx, y + h / 2), text, font=f, fill=DIM, anchor="lm")
        return w

    def _button(self, d, box, label, fill, fg=FG, icon=None):
        x0, y0, x1, y1 = box
        d.rounded_rectangle(box, radius=(y1 - y0) // 2, fill=fill)
        f = self._font(12, "sb")
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        ix = x0 + 14
        if icon == "check":
            d.line([(ix, cy + 1), (ix + 4, cy + 5), (ix + 11, cy - 5)], fill=fg, width=2, joint="curve")
            d.text((ix + 17, cy), label, font=f, fill=fg, anchor="lm")
        elif icon == "cross":
            d.line([(ix, cy - 5), (ix + 10, cy + 5)], fill=fg, width=2)
            d.line([(ix, cy + 5), (ix + 10, cy - 5)], fill=fg, width=2)
            d.text((ix + 16, cy), label, font=f, fill=fg, anchor="lm")
        else:
            d.text((cx, cy), label, font=f, fill=fg, anchor="mm")
        self._hits.append((x0, y0, x1, y1, label))

    def _icon_btn(self, d, cx, cy, r, kind, color):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_lerp(ISLAND_MID, (255, 255, 255), 0.1))
        if kind == "send":
            d.polygon([(cx - 4, cy - 5), (cx + 6, cy), (cx - 4, cy + 5)], fill=color)
        elif kind == "stop":
            d.rounded_rectangle([cx - 4, cy - 4, cx + 4, cy + 4], radius=2, fill=color)
        elif kind == "bolt":
            d.polygon([(cx + 1, cy - 6), (cx - 4, cy + 1), (cx, cy + 1), (cx - 1, cy + 6),
                       (cx + 4, cy - 1), (cx, cy - 1)], fill=color)
        self._hits.append((cx - r, cy - r, cx + r, cy + r, kind))

    def _wrap(self, text, font, maxw, d):
        out, cur = [], ""
        for word in text.split():
            t = (cur + " " + word).strip()
            if d.textlength(t, font=font) <= maxw or not cur:
                cur = t
            else:
                out.append(cur)
                cur = word
        if cur:
            out.append(cur)
        return out[:6]

    # ============================================================ kompozitsiya
    def _compose(self):
        self._hits = []
        mode = self.mode
        if mode == "expanded":
            self._compose_expanded()
            return
        self.canvas.itemconfigure(self._entry_win, state="hidden")
        W, H = SIZES[mode]
        r = RADIUS[mode]
        base, d = self._island_base(W, H, r)
        if mode == "hidden":
            for dx in (-8, 0, 8):
                d.ellipse([W / 2 + dx - 1.4, H / 2 - 1.4, W / 2 + dx + 1.4, H / 2 + 1.4], fill=(70, 76, 86))
            self._mascot_pos = None
        else:
            self._mascot_pos = (PADX, (H - MASCOT) / 2)
            tx = PADX + MASCOT + 12
            if mode == "peek":
                d.text((tx, H / 2), "Salom!", font=self._font(13, "sb"), fill=FG, anchor="lm")
            else:  # compact
                d.text((tx, H / 2 - 9), self._title, font=self._font(12, "sb"), fill=FG, anchor="lm")
                d.text((tx, H / 2 + 8), self._clip(self._sub, d, W - tx - 40), font=self._font(10), fill=DIM, anchor="lm")
                self._x_btn(d, W)
        self._island_img = base
        self._apply_image(base, W, H)

    def _compose_expanded(self):
        st = self.state
        pending = st.get("pending") or []
        tasks = st.get("tasks") or []
        W = WIDE_W
        body_w = W - 2 * PADX
        fbody = self._font(10)
        # --- balandlikni o'lchash ---
        tmp = Image.new("RGBA", (W, 10))
        dm = ImageDraw.Draw(tmp)
        y = HBAND + 6
        field_h = 40
        y += field_h + 12
        if pending:
            p = pending[0]
            lines = self._wrap(p.get("text") or "(matn yo'q)", fbody, body_w - 24, dm)
            y += 22 + len(lines) * 19 + 10
            if p["kind"] in ("approval", "question"):
                y += 40
            else:
                y += 24
        else:
            rows = len(tasks) + len((st.get("activity") or [])[-5:])
            y += (rows or 1) * 20 + 10
        H = y + 14
        r = RADIUS["expanded"]
        base, d = self._island_base(W, H, r)

        # --- bosh qatori ---
        self._mascot_pos = (PADX, (HBAND - MASCOT) / 2)
        tx = PADX + MASCOT + 12
        d.text((tx, HBAND / 2 - 10), self._title, font=self._font(13, "sb"), fill=FG, anchor="lm")
        d.text((tx, HBAND / 2 + 9), self._clip(self._sub, d, 330), font=self._font(10), fill=DIM, anchor="lm")
        cx = W - PADX - 90
        cx += self._chip(d, cx, HBAND / 2 - 10, st.get("plan", "obuna"), dot=self._cur) + 6
        self._x_btn(d, W)

        # --- kiritish qatori (field + tugmalar) ---
        fy = HBAND + 6
        btns_w = 3 * 34
        fx1 = W - PADX - btns_w
        fill = _lerp(ISLAND_MID, (255, 255, 255), 0.06)
        d.rounded_rectangle([PADX, fy, fx1 - 8, fy + field_h], radius=12, fill=fill)
        d.text((PADX + 14, fy + field_h / 2), "" if self.entry.get() else "topshiriq yozing…",
               font=self._font(11), fill=_lerp(DIM, ISLAND_MID, 0.3), anchor="lm")
        self._entry_rect = (PADX + 10, fy + 7, fx1 - 8 - PADX - 10, field_h - 14)
        bx = fx1 + 17
        self._icon_btn(d, bx, fy + field_h / 2, 15, "bolt", WORK if self.strong else DIM)
        self._icon_btn(d, bx + 34, fy + field_h / 2, 15, "send", WORK)
        self._icon_btn(d, bx + 68, fy + field_h / 2, 15, "stop", WAIT)

        # --- karta ---
        cy = fy + field_h + 12
        card_fill = _lerp(ISLAND_MID, (255, 255, 255), 0.04)
        if pending:
            p = pending[0]
            d.rounded_rectangle([PADX, cy, W - PADX, H - 12], radius=12, fill=card_fill)
            d.text((PADX + 12, cy + 12), f"{p['label']} · {p['task_id']}", font=self._font(10, "sb"),
                   fill=WAIT, anchor="lm")
            ty = cy + 26
            for ln in self._wrap(p.get("text") or "(matn yo'q)", fbody, body_w - 24, d):
                d.text((PADX + 12, ty), ln, font=fbody, fill=FG, anchor="lm")
                ty += 19
            if p["kind"] == "approval":
                self._button(d, (PADX + 12, ty + 6, PADX + 92, ty + 36), "Ha", (46, 158, 87), icon="check")
                self._button(d, (PADX + 104, ty + 6, PADX + 190, ty + 36), "Yo'q", (181, 67, 74), icon="cross")
            elif p["kind"] == "question":
                d.text((PADX + 12, ty + 20), "Javobni yuqoridagi maydonga yozing", font=fbody, fill=DIM, anchor="lm")
            else:
                d.text((PADX + 12, ty + 20), "Maxfiy ma'lumotni Telegram orqali yuboring", font=fbody, fill=DIM, anchor="lm")
        else:
            ty = cy
            for t in tasks:
                d.polygon([(PADX + 2, ty - 4), (PADX + 8, ty), (PADX + 2, ty + 4)], fill=WORK)
                d.text((PADX + 14, ty), f"{t['id']} · {t['elapsed']} · {t['steps']} amal", font=fbody,
                       fill=WORK, anchor="lm")
                ty += 20
            for a in (st.get("activity") or [])[-5:]:
                txt = a.get("text", "")
                good, bad = txt.startswith("✓"), txt.startswith("✗")
                txt = txt.lstrip("✓✗ ").strip()
                dotc = READY if good else BAD if bad else _lerp(DIM, ISLAND_MID, 0.2)
                d.ellipse([PADX + 2, ty - 2.5, PADX + 7, ty + 2.5], fill=dotc)
                d.text((PADX + 14, ty), f"{a['ts']}  {txt}", font=fbody, fill=DIM, anchor="lm")
                ty += 20
            if not tasks and not (st.get("activity")):
                d.text((PADX + 2, ty), "Topshiriq yozing va Enter bosing", font=fbody, fill=DIM, anchor="lm")

        self._island_img = base
        self._apply_image(base, W, H)
        # haqiqiy entry'ni maydon ustiga qo'yamiz
        ex, ey, ew, eh = self._entry_rect
        self.canvas.coords(self._entry_win, ex, ey)
        self.canvas.itemconfigure(self._entry_win, state="normal", width=ew, height=eh)

    def _x_btn(self, d, W):
        cx, cy = W - 16, HBAND / 2 if self.mode == "expanded" else self.h / 2
        d.line([(cx - 4, cy - 4), (cx + 4, cy + 4)], fill=DIM, width=2)
        d.line([(cx - 4, cy + 4), (cx + 4, cy - 4)], fill=DIM, width=2)
        self._hits.append((cx - 8, cy - 8, cx + 8, cy + 8, "close"))

    def _clip(self, text, d, maxw):
        f = self._font(10)
        if d.textlength(text, font=f) <= maxw:
            return text
        while text and d.textlength(text + "…", font=f) > maxw:
            text = text[:-1]
        return text + "…"

    def _apply_image(self, base, W, H):
        if (W, H) != (self.w, self.h):
            cur_h = self.h
            self.x = int(self.x + self.w / 2 - W / 2)
            self._apply_geometry(W, cur_h)
            self._slide(cur_h, H)
        else:
            self._apply_geometry(W, H)
        self._photo = ImageTk.PhotoImage(base)
        self.canvas.itemconfigure(self._img_id, image=self._photo)
        self.canvas.coords(self._img_id, 0, 0)
        self._draw_mascot()

    def _slide(self, frm, to, step=0):
        steps = 6
        t = 1 - (1 - (step + 1) / steps) ** 2
        self._apply_geometry(self.w, frm + (to - frm) * t)
        if step + 1 < steps:
            self.root.after(13, lambda: self._slide(frm, to, step + 1))

    def _show_island(self):
        if self._island_img is not None:
            self._photo = ImageTk.PhotoImage(self._island_img)
            self.canvas.itemconfigure(self._img_id, image=self._photo)
        self._draw_mascot()

    # ============================================================ maskot (alohida, animatsiyali)
    def _mascot_image(self):
        c = self._cur
        S = 3
        box = 44
        img = Image.new("RGBA", (box * S, box * S), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        cx = box * S / 2
        m = MASCOT * S
        x0, y0 = cx - m / 2, cx - m / 2
        if c == WORK:  # ishlaganda ореол (glow)
            g = (box - 4) * S
            d.ellipse([(box * S - g) / 2, (box * S - g) / 2, (box * S + g) / 2, (box * S + g) / 2],
                      fill=c + (46,))
        # tana — gradient (yuqori yorqin, past to'q)
        body = Image.new("RGBA", (int(m), int(m)))
        bd = ImageDraw.Draw(body)
        for yy in range(int(m)):
            bd.line([(0, yy), (m, yy)], fill=_lerp(_lerp(c, (255, 255, 255), 0.25), _lerp(c, (0, 0, 0), 0.25),
                                                   yy / max(1, m - 1)) + (255,))
        bmask = Image.new("L", (int(m), int(m)), 0)
        ImageDraw.Draw(bmask).rounded_rectangle([0, 0, m - 1, m - 1], radius=m * 0.32, fill=255)
        img.paste(body, (int(x0), int(y0)), bmask)
        # yaltiroq dog'
        d.ellipse([x0 + m * 0.18, y0 + m * 0.12, x0 + m * 0.5, y0 + m * 0.34], fill=(255, 255, 255, 70))
        # ko'zlar
        ey = y0 + m * 0.44
        for ex in (x0 + m * 0.34, x0 + m * 0.66):
            if self._blink > 0:
                d.line([(ex - 3.2 * S, ey), (ex + 3.2 * S, ey)], fill=(12, 14, 18), width=int(2.4 * S))
            else:
                d.ellipse([ex - 3.3 * S, ey - 3.8 * S, ex + 3.3 * S, ey + 3.8 * S], fill=(16, 18, 24))
                d.ellipse([ex - 1.0 * S, ey - 3.0 * S, ex + 1.6 * S, ey - 0.6 * S], fill=(255, 255, 255, 220))
        return img.resize((box, box), Image.LANCZOS), box

    def _draw_mascot(self):
        if self._mascot_pos is None:
            self.canvas.itemconfigure(self._mascot_id, state="hidden")
            return
        img, box = self._mascot_image()
        self._mascot_photo = ImageTk.PhotoImage(img)
        self.canvas.itemconfigure(self._mascot_id, image=self._mascot_photo, state="normal")
        bob = math.sin(self._phase) * 2 if self._cur == WORK else 0
        self.canvas.coords(self._mascot_id, self._mascot_pos[0] - 7, self._mascot_pos[1] - 7 + bob)

    # ============================================================ poll / render
    def _schedule_poll(self):
        threading.Thread(target=self._poll_once, daemon=True).start()

    def _poll_once(self):
        state, err = self._get_state()
        self.root.after(0, lambda: self._apply(state, err))

    def _apply(self, state, err):
        if state is not None:
            self.state, self.err = state, ""
        else:
            self.err = err
        self._render()
        self.root.after(POLL_MS, self._schedule_poll)

    def _render(self):
        st = self.state
        pending = st.get("pending") or []
        tasks = st.get("tasks") or []
        connected = not self.err
        focused = self.entry is self.root.focus_get()

        if not connected:
            self._cur, self._title, self._sub = OFF, "Sentinel", self.err
        elif st.get("blocked"):
            self._cur, self._title, self._sub = BAD, "limit", st["blocked"]
        elif pending:
            self._cur, self._title, self._sub = WAIT, "tasdiq kutyapti", f"{len(pending)} ta so'rov"
        elif tasks:
            t = tasks[0]
            self._cur, self._title = WORK, f"ishlayapti ({len(tasks)})"
            self._sub = f"{t['elapsed']} · {t['steps']} amal · {t.get('last') or t.get('text', '')}"
        else:
            last = (st.get("reply") or "").replace("\n", " ")
            self._cur, self._title = READY, "tayyor"
            self._sub = (f"oxirgi: {last}" if last else f"{st.get('plan', 'obuna')} · {st.get('model', '')}")

        if pending or self.lock_open or focused:
            mode = "expanded"
        elif tasks:
            mode = "expanded" if self.hover else "compact"
        elif self.hover:
            mode = "peek"
        else:
            mode = "hidden"
        self.mode = mode
        self._compose()

    # ============================================================ animatsiya
    def _animate(self):
        self._phase += 0.5
        if self._wave > 0:
            self._wave -= 1
        if self._blink > 0:
            self._blink -= 1
        elif int(self._phase) % 40 == 0:
            self._blink = 2
        if self._mascot_pos is not None:
            self._draw_mascot()
        self.root.after(110, self._animate)

    # ============================================================ hodisalar
    def _on_enter(self, _e):
        if not self.hover and self.mode == "hidden":
            self._wave = 12
        self.hover = True
        if self._collapse_job:
            self.root.after_cancel(self._collapse_job)
            self._collapse_job = None
        self._render()

    def _on_leave(self, _e):
        self.hover = False
        if self._collapse_job:
            self.root.after_cancel(self._collapse_job)
        self._collapse_job = self.root.after(1300, self._maybe_collapse)

    def _maybe_collapse(self):
        self._collapse_job = None
        if not (self.lock_open or self.hover or (self.state.get("pending") or []) or (self.state.get("tasks") or [])
                or self.entry is self.root.focus_get()):
            self._render()

    def _on_click(self, e):
        for x0, y0, x1, y1, name in self._hits:
            if x0 <= e.x <= x1 and y0 <= e.y <= y1:
                self._action(name)
                return
        if self.mode in ("hidden", "peek"):      # bo'sh joyga bosish — ochib qotirish
            self.lock_open = True
            self._render()
        self._dx, self._dy = e.x_root - self.x, e.y_root - self.y

    def _action(self, name):
        if name == "close":
            self.root.destroy()
        elif name == "Ha" or name == "Yo'q":
            p = (self.state.get("pending") or [None])[0]
            if p:
                self._answer(p["id"], "yes" if name == "Ha" else "no")
        elif name == "send":
            self._send_task()
        elif name == "stop":
            self._stop()
        elif name == "bolt":
            self.strong = not self.strong
            self._compose()

    def _drag_move(self, e):
        if hasattr(self, "_dx"):
            self.x = e.x_root - self._dx
            self.y = max(0, e.y_root - self._dy)
            self._apply_geometry(self.w, self.h)

    # ============================================================ amallar
    def _send_task(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        q = next((p for p in (self.state.get("pending") or []) if p["kind"] == "question"), None)
        if q:
            self._answer(q["id"], text)
            return
        strong = self.strong
        self._flash("yuborilyapti…")
        threading.Thread(target=lambda: self._task_thread(text, strong), daemon=True).start()

    def _task_thread(self, text, strong):
        res = self._post("/api/task", {"text": text, "strong": strong})
        msg = res.get("error") or f"▶ {res.get('id', '')} boshlandi"
        self.root.after(0, lambda: self._flash(msg))

    def _answer(self, pid, value):
        self._flash("yuborilyapti…")
        threading.Thread(target=lambda: self._answer_thread(pid, value), daemon=True).start()

    def _answer_thread(self, pid, value):
        self._post("/api/answer", {"id": pid, "value": value})
        self.root.after(0, self._poll_once)

    def _stop(self):
        threading.Thread(target=lambda: self._post("/api/stop", {}), daemon=True).start()
        self._flash("to'xtatilyapti…")

    def _flash(self, text):
        self._sub = text
        if self.mode != "hidden":
            self._compose()

    def run(self):
        self.root.mainloop()


def main() -> int:
    try:
        cfg = Config.from_env()
    except Exception as exc:  # noqa: BLE001
        print(f".env o'qilmadi: {exc}", file=sys.stderr)
        return 1
    AgentPanel(Paths(cfg.agent_home)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
