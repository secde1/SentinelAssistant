"""Ustki panel (oynacha) — coucou uslubidagi ekran tepasidagi "orol".

coucou g'oyasi, bizning agentga moslab o'z dizaynimiz bilan (coucou'ning "Mochi" personaji/nomi/ikonkasi
mualliflik huquqida — ko'chirilmaydi; bizda o'z maskotimiz "Sentinel" — yumaloq yuzcha).

Ko'rinishi:
  • ekran tepa-o'rtasidan chiqadigan dumaloq burchakli qora "orol" (transparentcolor bilan burchaklari shaffof);
  • chapda rang bilan holatni bildiruvchi kichik maskot (ko'zlari bor, ishlaganda chayqaladi, goho ko'z qisadi);
  • odatda ixcham; sichqoncha tegsa yoki ish/tasdiq bo'lsa pastga "sirg'alib" kengayadi.
Holat ranglari (coucou semantikasi): kutyapti=to'q sariq, ishlayapti=ko'k, tayyor=yashil, o'chiq/limit=kulrang/qizil.

Agent xizmati ishlab turganda ishlaydi; u bilan faqat mahalliy (127.0.0.1) + token orqali gaplashadi.
Ishga tushirish:  oynacha.cmd   (yoki .venv\\Scripts\\pythonw.exe -m agent.panel)
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

KEY = "#ff00fe"      # shaffoflik kaliti (shu rang = ko'rinmas) — hech joyda ishlatilmaydi
ISLAND = "#0b0d10"   # "orol" foni (deyarli qora)
CARD = "#171b21"     # ichki karta/entry foni
FG = "#e9edf2"
DIM = "#8a93a0"
READY = "#35c46b"    # tayyor (yashil)
WORK = "#3b8bff"     # ishlayapti (ko'k)
WAIT = "#f0922b"     # tasdiq kutyapti (to'q sariq)
BAD = "#ff5c57"      # xato/limit (qizil)
OFF = "#6b7280"      # o'chiq (kulrang)

R = 19               # burchak radiusi
HEADER = 48          # ixcham balandlik
COMPACT_W = 310
WIDE_W = 648
PAD = 14
MASCOT = 26
POLL_MS = 1500


def _round_pts(x1, y1, x2, y2, r):
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
            x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class AgentPanel:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.state: dict = {}
        self.err = "ulanmoqda…"
        self.strong = False
        self.expanded = False
        self.lock_open = False      # foydalanuvchi ochiq qotirgan
        self.hover = False
        self._collapse_job = None
        self._card_key = None
        self._phase = 0.0
        self._blink = 0
        self._cur_color = OFF
        self._title = "Sentinel"
        self._sub = "ulanmoqda…"
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
            return None, "agent topilmadi — ishga tushganmi?"
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", headers={"X-Token": token})
            with urllib.request.urlopen(req, timeout=3) as r:
                return json.loads(r.read().decode("utf-8")), ""
        except urllib.error.URLError:
            return None, "agent bilan aloqa yo'q (o'chiqmi?)"
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)[:60]

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

    # ============================================================ oyna qurilishi
    def _build(self):
        self.root = tk.Tk()
        self.root.title("Sentinel")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", KEY)  # burchaklar shaffof (Windows)
            self._transparent = True
        except tk.TclError:
            self._transparent = False
        self.root.configure(bg=KEY if self._transparent else ISLAND)
        self.sw = self.root.winfo_screenwidth()

        self.canvas = tk.Canvas(self.root, bg=KEY if self._transparent else ISLAND,
                                highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)

        # kengaygan qism (entry, tugmalar, kartalar) — orolga joylashtiriladi
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

        # hodisalar: hover -> kengaytirish, drag, maskot bosilsa qotirish
        for w in (self.root, self.canvas):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", lambda e: setattr(self, "_moved", False))

        self.x = (self.sw - COMPACT_W) // 2
        self.y = 0
        self._moved = False
        self._apply_geometry(COMPACT_W, HEADER)
        self._draw_pill()
        self._place_header()

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

    # ============================================================ geometriya / kengayish
    def _apply_geometry(self, w, h):
        self.w, self.h = w, h
        self.x = max(0, min(self.x, self.sw - w))
        self.root.geometry(f"{int(w)}x{int(h)}+{int(self.x)}+{int(self.y)}")

    def _draw_pill(self):
        self.canvas.delete("pill")
        self.canvas.create_polygon(_round_pts(1, -R, self.w - 1, self.h - 2, R), smooth=True,
                                   fill=ISLAND, outline="#20262e", width=1, tags="pill")
        self.canvas.tag_lower("pill")

    def _set_expanded(self, want: bool):
        if want == self.expanded:
            return
        self.expanded = want
        if want:
            # avval kengligini o'zgartiramiz (markazga), keyin balandlik "sirg'aladi"
            cx = self.x + self.w / 2
            self.x = int(cx - WIDE_W / 2)
            self.body.update_idletasks()
            target = HEADER + self.body.winfo_reqheight() + PAD
            self._win_id = self.canvas.create_window(PAD, HEADER - 2, window=self.body, anchor="nw",
                                                     width=WIDE_W - 2 * PAD, tags="body")
            self._tween(WIDE_W, target)
        else:
            self.canvas.delete("body")
            cx = self.x + self.w / 2
            self.x = int(cx - COMPACT_W / 2)
            self._tween(COMPACT_W, HEADER)

    def _tween(self, w, h, step=0):
        steps = 6
        if step == 0:
            self._from = (self.w, self.h)
        t = (step + 1) / steps
        t = 1 - (1 - t) ** 2  # ease-out
        nw = self._from[0] + (w - self._from[0]) * t
        nh = self._from[1] + (h - self._from[1]) * t
        self._apply_geometry(nw, nh)
        self._draw_pill()
        self._place_header()
        if step + 1 < steps:
            self.root.after(14, lambda: self._tween(w, h, step + 1))

    # ============================================================ chizish
    def _place_header(self):
        """Maskot + sarlavha/ticker (ixcham qatorda doim ko'rinadi)."""
        self.canvas.delete("head")
        self._draw_mascot()
        tx = PAD + MASCOT + 12
        self.canvas.create_text(tx, HEADER / 2 - 9, text=self._title, anchor="w", fill=FG,
                                font=("Segoe UI Semibold", 11), tags="head")
        maxw = self.w - tx - 44
        self.canvas.create_text(tx, HEADER / 2 + 8, text=self._ellipsis(self._sub, maxw), anchor="w",
                                fill=DIM, font=("Segoe UI", 9), tags="head")
        # o'ng yuqorida yopish
        self.canvas.create_text(self.w - 16, HEADER / 2, text="✕", fill=DIM, font=("Segoe UI", 11),
                                tags=("head", "close"))
        self.canvas.tag_bind("close", "<Button-1>", lambda e: self.root.destroy())

    def _ellipsis(self, text, maxw):
        if maxw < 40:
            return ""
        est = int(maxw / 6.3)  # taxminiy belgi kengligi
        return text if len(text) <= est else text[: est - 1] + "…"

    def _draw_mascot(self):
        self.canvas.delete("mascot")
        c = self._cur_color
        x0, y0 = PAD, (HEADER - MASCOT) / 2
        bob = 0
        if c == WORK:
            bob = math.sin(self._phase) * 2
        y0 += bob
        x1, y1 = x0 + MASCOT, y0 + MASCOT
        # yumaloq "yuzcha" (squircle)
        self.canvas.create_polygon(_round_pts(x0, y0, x1, y1, 9), smooth=True, fill=c, outline="", tags="mascot")
        # ko'zlar (ko'z qissa — chiziq)
        ey = y0 + MASCOT * 0.42
        ex1, ex2 = x0 + MASCOT * 0.33, x0 + MASCOT * 0.67
        if self._blink > 0:
            for ex in (ex1, ex2):
                self.canvas.create_line(ex - 2.3, ey, ex + 2.3, ey, fill="#0b0d10", width=2, tags="mascot")
        else:
            for ex in (ex1, ex2):
                self.canvas.create_oval(ex - 2.4, ey - 2.8, ex + 2.4, ey + 2.8, fill="#0b0d10",
                                        outline="", tags="mascot")

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

        if not connected:
            self._cur_color, self._title, self._sub = OFF, "Sentinel", self.err
        elif st.get("blocked"):
            self._cur_color, self._title, self._sub = BAD, "Sentinel · limit", st["blocked"]
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

        want = self.lock_open or self.hover or bool(pending) or bool(tasks) or self.entry is self.root.focus_get()
        self._set_expanded(want)
        if self.expanded:
            self.model_lbl.configure(text=f"model: {st.get('model', '—')}  ·  {st.get('plan', '')}"
                                     + (f"  ·  {st.get('limits')}" if st.get("limits") else ""))
            self._fill_card(pending)
        self._draw_pill()
        self._place_header()

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
        self.body.update_idletasks()
        if self.expanded:  # kengaygan bo'lsa balandlikni yangilaymiz
            target = HEADER + self.body.winfo_reqheight() + PAD
            self._apply_geometry(self.w, target)
            self._draw_pill()

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
        if self._blink > 0:
            self._blink -= 1
        elif int(self._phase) % 38 == 0:
            self._blink = 2
        self._draw_mascot()
        self.root.after(110, self._animate)

    # ============================================================ hodisalar
    def _on_enter(self, _e):
        self.hover = True
        if self._collapse_job:
            self.root.after_cancel(self._collapse_job)
            self._collapse_job = None
        self._set_expanded(True)
        if self.expanded:
            self._fill_card(self.state.get("pending") or [])

    def _on_leave(self, _e):
        self.hover = False
        if self._collapse_job:
            self.root.after_cancel(self._collapse_job)
        self._collapse_job = self.root.after(1300, self._maybe_collapse)

    def _maybe_collapse(self):
        self._collapse_job = None
        keep = self.lock_open or self.hover or (self.state.get("pending") or []) or (self.state.get("tasks") or []) \
            or self.entry is self.root.focus_get()
        if not keep:
            self._set_expanded(False)

    def _on_click(self, e):
        # maskot ustiga bosilsa — ochiq qotirish/bo'shatish
        if e.x <= PAD + MASCOT + 6 and e.y <= HEADER:
            self.lock_open = not self.lock_open
            self._set_expanded(self.lock_open or self.hover)
        self._drag_start(e)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.x, e.y_root - self.y

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
        self._place_header()

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
