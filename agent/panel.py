"""Ustki panel (oynacha) — coucou uslubidagi ekran tepasidagi "notch/island".

coucou kabi: ekranning tepa-o'rtasiga YOPISHGAN qora orol (notch). Yuqori cheti tekis (ekran chetiga tegib turadi),
faqat pastki burchaklari dumaloq. BO'SH turganda yashirinadi (ingichka qora chiziqcha qoladi); tepa chetga sichqoncha
tegsa "mo'ralab" chiqadi (maskot 👋 qiladi); ish/tasdiq bo'lsa o'zi tushadi; bosilsa to'liq ochiladi.

coucou qiymatlari (manbadan): orol foni qora; burchak radiusi 14 (ixcham) / 22 (kengaygan); kengaygan en 640.
Ranglar coucou palitrasi: kutyapti #F29B38, ishlayapti #38BDF8, tayyor #4ADE80, xato #F4505E.
coucou'ning "Mochi" personaji/nomi/ikonkasi KO'CHIRILMADI — o'z maskotimiz (yumaloq yuzcha) va "Sentinel" nomi.

Mahalliy (127.0.0.1) + token orqali. Ishga tushirish: oynacha.cmd
"""
from __future__ import annotations

import json
import math
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request

from .config import Config
from .workspace import Paths

KEY = "#ff00fe"      # shaffoflik kaliti (ko'rinmas)
ISLAND = "#000000"   # orol foni — qora (coucou kabi)
CARD = "#121418"
FG = "#f5f6f8"
DIM = "#8a8f98"
READY = "#4ade80"    # tayyor (yashil)  — coucou palitrasi
WORK = "#38bdf8"     # ishlayapti (ko'k)
WAIT = "#f29b38"     # tasdiq kutyapti (to'q sariq)
BAD = "#f4505e"      # xato/limit (qizil)
OFF = "#6b7280"      # o'chiq (kulrang)

WIDE_W = 640
PAD = 14
MASCOT = 24
HBAND = 46           # kengaygan/ixcham holatdagi yuqori "bosh" qatori
POLL_MS = 1500

# mode -> (kenglik, balandlik); "expanded" balandligi tarkibdan hisoblanadi
SIZES = {"hidden": (210, 7), "peek": (250, 40), "compact": (340, HBAND)}
RADIUS = {"hidden": 10, "peek": 14, "compact": 14, "expanded": 22}


def _notch_pts(w, h, r):
    """Yuqori cheti tekis, pastki burchaklari dumaloq (notch) ko'pburchak nuqtalari."""
    seg = 7
    pts = [0.0, 0.0, float(w), 0.0, float(w), float(h - r)]
    for i in range(1, seg + 1):               # pastki-o'ng yoy
        a = (math.pi / 2) * (i / seg)
        pts += [w - r + r * math.cos(a), h - r + r * math.sin(a)]
    for i in range(1, seg + 1):               # pastki-chap yoy
        a = math.pi / 2 + (math.pi / 2) * (i / seg)
        pts += [r + r * math.cos(a), h - r + r * math.sin(a)]
    return pts


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
        self._card_key = None
        self._phase = 0.0
        self._blink = 0
        self._wave = 0
        self._body_shown = False
        self._cur_color = OFF
        self._title = "Sentinel"
        self._sub = ""
        self._build()
        self._pin()
        self._animate()
        self._schedule_poll()

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

        self.body = tk.Frame(self.canvas, bg=ISLAND)
        self.model_lbl = tk.Label(self.body, text="", bg=ISLAND, fg=DIM, font=("Segoe UI", 8), anchor="w")
        self.model_lbl.pack(fill="x", padx=2)
        row = tk.Frame(self.body, bg=ISLAND)
        row.pack(fill="x", pady=(3, 0))
        self.entry = tk.Entry(row, bg=CARD, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 10))
        self.entry.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self._send_task())
        self.opus_btn = self._pill_btn(row, "⚡", self._toggle_strong, DIM)
        self.opus_btn.pack(side="left", padx=2)
        self._pill_btn(row, "➤", self._send_task, WORK).pack(side="left", padx=2)
        self._pill_btn(row, "⛔", self._stop, WAIT).pack(side="left", padx=2)
        self.card = tk.Frame(self.body, bg=ISLAND)
        self.card.pack(fill="x", pady=(6, 0))

        for w in (self.root, self.canvas):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._drag_move)

        self.x = (self.sw - SIZES["hidden"][0]) // 2
        self.y = 0
        self.w, self.h = SIZES["hidden"]
        self._apply_geometry(*SIZES["hidden"])
        self._draw()

    def _pill_btn(self, parent, text, cmd, color):
        return tk.Button(parent, text=text, command=cmd, bg=CARD, fg=color, relief="flat",
                         activebackground="#222730", activeforeground=FG, bd=0,
                         font=("Segoe UI", 11), width=3, cursor="hand2")

    def _pin(self):
        try:
            self.root.attributes("-topmost", False)
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after(3000, self._pin)

    # ============================================================ geometriya
    def _apply_geometry(self, w, h):
        self.w, self.h = int(w), int(h)
        self.x = max(0, min(self.x, self.sw - self.w))
        self.root.geometry(f"{self.w}x{self.h}+{int(self.x)}+{int(self.y)}")

    def _size_for(self, mode):
        if mode == "expanded":
            self._ensure_body(True)
            self.body.update_idletasks()
            return WIDE_W, HBAND + self.body.winfo_reqheight() + PAD
        self._ensure_body(False)
        return SIZES[mode]

    def _ensure_body(self, show):
        if show and not self._body_shown:
            self.canvas.create_window(PAD, HBAND - 2, window=self.body, anchor="nw",
                                      width=WIDE_W - 2 * PAD, tags="body")
            self._body_shown = True
        elif not show and self._body_shown:
            self.canvas.delete("body")
            self._body_shown = False

    def _transition(self, mode):
        tw, th = self._size_for(mode)
        same = (mode == self.mode and tw == self.w and th == self.h)
        self.mode = mode
        if same:
            self._draw()
            return
        cx = self.x + self.w / 2
        self.x = int(cx - tw / 2)
        self._tween(tw, th, 0, (self.w, self.h))

    def _tween(self, w, h, step, frm):
        steps = 6
        t = 1 - (1 - (step + 1) / steps) ** 2
        self._apply_geometry(frm[0] + (w - frm[0]) * t, frm[1] + (h - frm[1]) * t)
        self._draw()
        if step + 1 < steps:
            self.root.after(13, lambda: self._tween(w, h, step + 1, frm))

    # ============================================================ chizish
    def _draw(self):
        self.canvas.delete("pill")
        r = RADIUS.get(self.mode, 14)
        self.canvas.create_polygon(_notch_pts(self.w, self.h, r), fill=ISLAND, outline="", tags="pill")
        self.canvas.tag_lower("pill")
        self._place_head()

    def _place_head(self):
        self.canvas.delete("head")
        if self.mode == "hidden":
            for dx in (-7, 0, 7):                     # ingichka chiziqchada 3 nuqta
                self.canvas.create_oval(self.w / 2 + dx - 1.3, self.h / 2 - 1.3,
                                        self.w / 2 + dx + 1.3, self.h / 2 + 1.3,
                                        fill="#3a3f47", outline="", tags="head")
            return
        self._draw_mascot()
        tx = PAD + MASCOT + 12
        if self.mode == "peek":
            if self._wave > 0 and self._wave % 2:
                self.canvas.create_text(tx, self.h / 2, text="👋", anchor="w", font=("Segoe UI", 13), tags="head")
            else:
                self.canvas.create_text(tx, self.h / 2, text="Salom!", anchor="w", fill=FG,
                                        font=("Segoe UI Semibold", 11), tags="head")
            return
        self.canvas.create_text(tx, HBAND / 2 - 9, text=self._title, anchor="w", fill=FG,
                                font=("Segoe UI Semibold", 11), tags="head")
        self.canvas.create_text(tx, HBAND / 2 + 8, text=self._ellipsis(self._sub, self.w - tx - 42), anchor="w",
                                fill=DIM, font=("Segoe UI", 9), tags="head")
        self.canvas.create_text(self.w - 15, HBAND / 2, text="✕", fill=DIM, font=("Segoe UI", 11),
                                tags=("head", "close"))
        self.canvas.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())

    def _ellipsis(self, text, maxw):
        if maxw < 40:
            return ""
        est = int(maxw / 6.3)
        return text if len(text) <= est else text[: est - 1] + "…"

    def _draw_mascot(self):
        self.canvas.delete("mascot")
        c = self._cur_color
        hband = self.h if self.mode == "peek" else HBAND
        x0, y0 = PAD, (hband - MASCOT) / 2
        if c == WORK:
            y0 += math.sin(self._phase) * 2
        x1, y1 = x0 + MASCOT, y0 + MASCOT
        self.canvas.create_polygon(_notch_pts_round(x0, y0, x1, y1, 8), smooth=True, fill=c, outline="", tags="mascot")
        ey = y0 + MASCOT * 0.42
        for ex in (x0 + MASCOT * 0.33, x0 + MASCOT * 0.67):
            if self._blink > 0:
                self.canvas.create_line(ex - 2.3, ey, ex + 2.3, ey, fill=ISLAND, width=2, tags="mascot")
            else:
                self.canvas.create_oval(ex - 2.4, ey - 2.8, ex + 2.4, ey + 2.8, fill=ISLAND, outline="", tags="mascot")

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
            self._cur_color, self._title, self._sub = OFF, "Sentinel", self.err
        elif st.get("blocked"):
            self._cur_color, self._title, self._sub = BAD, "limit", st["blocked"]
        elif pending:
            self._cur_color, self._title, self._sub = WAIT, "tasdiq kutyapti", f"{len(pending)} ta so'rov"
        elif tasks:
            t = tasks[0]
            self._cur_color, self._title = WORK, f"ishlayapti ({len(tasks)})"
            self._sub = f"{t['elapsed']} · {t['steps']} amal · {t.get('last') or t.get('text', '')}"
        else:
            last = (st.get("reply") or "").replace("\n", " ")
            self._cur_color, self._title = READY, "tayyor"
            self._sub = (f"oxirgi: {last}" if last else f"{st.get('plan', 'obuna')} · {st.get('model', '')}")

        if pending or self.lock_open or focused:
            mode = "expanded"
        elif tasks:
            mode = "expanded" if self.hover else "compact"
        elif self.hover:
            mode = "peek"
        else:
            mode = "hidden"

        if mode == "expanded":
            self.model_lbl.configure(text=f"model: {st.get('model', '—')}  ·  {st.get('plan', '')}"
                                     + (f"  ·  {st.get('limits')}" if st.get("limits") else ""))
            self._fill_card(pending)
        self._transition(mode)

    def _fill_card(self, pending):
        if pending:
            key = ("pend", pending[0]["id"])
        else:
            acts = self.state.get("activity") or []
            key = ("det", acts[-1]["ts"] if acts else "", len(self.state.get("tasks") or []))
        if key == self._card_key:
            return
        self._card_key = key
        for w in self.card.winfo_children():
            w.destroy()
        if pending:
            self._card_pending(pending[0])
        else:
            self._card_details()

    def _card_pending(self, p):
        box = tk.Frame(self.card, bg=CARD)
        box.pack(fill="x")
        tk.Label(box, text=f"{p['label']} · {p['task_id']}", bg=CARD, fg=WAIT,
                 font=("Segoe UI Semibold", 9), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        tk.Message(box, text=p.get("text") or "(matn yo'q)", bg=CARD, fg=FG, width=WIDE_W - 2 * PAD - 24,
                   font=("Segoe UI", 10), anchor="w", justify="left").pack(fill="x", padx=10, pady=4)
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", padx=10, pady=(0, 9))
        if p["kind"] == "approval":
            tk.Button(row, text="✅ Ha", command=lambda: self._answer(p["id"], "yes"), bg="#1f6f3f", fg="white",
                      relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2",
                      activebackground="#27854c", padx=12, pady=3).pack(side="left")
            tk.Button(row, text="❌ Yo'q", command=lambda: self._answer(p["id"], "no"), bg="#7a2b29", fg="white",
                      relief="flat", bd=0, font=("Segoe UI Semibold", 10), cursor="hand2",
                      activebackground="#9a3734", padx=12, pady=3).pack(side="left", padx=8)
        elif p["kind"] == "question":
            ent = tk.Entry(row, bg=ISLAND, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 10))
            ent.pack(side="left", fill="x", expand=True, ipady=4)
            ent.bind("<Return>", lambda e: self._answer(p["id"], ent.get().strip()))
            tk.Button(row, text="Javob", command=lambda: self._answer(p["id"], ent.get().strip()),
                      bg=CARD, fg=WORK, relief="flat", bd=0, font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=6)
        else:
            tk.Label(row, text="🔒 Maxfiy ma'lumotni Telegram orqali yuboring (panelga yozilmaydi).",
                     bg=CARD, fg=DIM, font=("Segoe UI", 9), anchor="w").pack(fill="x")

    def _card_details(self):
        st = self.state
        for t in st.get("tasks") or []:
            tk.Label(self.card, text=f"▶ {t['id']} · {t['elapsed']} · {t['steps']} amal", bg=ISLAND, fg=WORK,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=2)
        acts = (st.get("activity") or [])[-5:]
        for a in acts:
            tk.Label(self.card, text=f"{a['ts']}  {a['text']}", bg=ISLAND, fg=DIM,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=2)
        if not acts and not (st.get("tasks")):
            tk.Label(self.card, text="Topshiriq yozing — Enter yoki ➤", bg=ISLAND, fg=DIM,
                     font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=2)

    # ============================================================ animatsiya
    def _animate(self):
        self._phase += 0.5
        if self._wave > 0:
            self._wave -= 1
        if self._blink > 0:
            self._blink -= 1
        elif int(self._phase) % 38 == 0:
            self._blink = 2
        if self.mode != "hidden":
            self._place_head()
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
        if e.y <= HBAND and e.x <= PAD + MASCOT + 8:      # maskot -> ochiq qotirish
            self.lock_open = not self.lock_open
        self._dx, self._dy = e.x_root - self.x, e.y_root - self.y
        self._render()

    def _drag_move(self, e):
        self.x = e.x_root - self._dx
        self.y = max(0, e.y_root - self._dy)
        self._apply_geometry(self.w, self.h)

    # ============================================================ amallar
    def _toggle_strong(self):
        self.strong = not self.strong
        self.opus_btn.configure(fg=WORK if self.strong else DIM)

    def _send_task(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
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
            self._place_head()

    def run(self):
        self.root.mainloop()


def _notch_pts_round(x1, y1, x2, y2, r):
    """To'liq dumaloq burchakli (maskot uchun) — smooth polygon nuqtalari."""
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
            x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


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
