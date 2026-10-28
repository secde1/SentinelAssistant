"""Ustki panel (oynacha) — kompyuter ekranining tepasida turuvchi kichik oyna, agentni kuzatish va boshqarish uchun.

coucou g'oyasi: ekran tepasida kichik panel, undan agent nima qilayotganini ko'rasiz va boshqarasiz —
Telegram'siz, kompyuterning o'zida. Agent xizmati (python -m agent) ishlab turganda ishlaydi; u bilan faqat
mahalliy (127.0.0.1) va token orqali gaplashadi. Yangi kutubxona kerak emas — tkinter + urllib (standart).

Ishga tushirish:  oynacha.cmd  (yoki)  .venv\\Scripts\\pythonw.exe -m agent.panel
"""
from __future__ import annotations

import json
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request

from .config import Config
from .workspace import Paths

BG = "#0e1116"       # fon
CARD = "#161b22"     # ichki karta/entry foni
FG = "#e6edf3"       # asosiy matn
DIM = "#8b949e"      # xira matn
ACCENT = "#2f81f7"   # ishlayapti (ko'k)
OK = "#3fb950"       # tayyor (yashil)
WARN = "#d29922"     # tasdiq kutyapti (sariq)
BAD = "#f85149"      # xato/limit/o'chiq (qizil)

POLL_MS = 1500


class AgentPanel:
    def __init__(self, paths: Paths):
        self.paths = paths
        self.state: dict = {}
        self.err = "ulanmoqda…"
        self.strong = False
        self.show_details = False
        self._card_key = None
        self._build()
        self._schedule_poll()

    # ------------------------------------------------------------ server bilan aloqa (mahalliy)
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

    # ------------------------------------------------------------ poll sikli
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

    # ------------------------------------------------------------ oyna
    def _build(self):
        self.root = tk.Tk()
        self.root.title("Sentinel")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", 0.97)
        except tk.TclError:
            pass
        self.root.configure(bg=BG)
        self.width = 760
        self.x = (self.root.winfo_screenwidth() - self.width) // 2
        self.top_y = 8
        self.root.geometry(f"{self.width}x58+{self.x}+{self.top_y}")

        # yuqori qator (doimiy)
        bar = tk.Frame(self.root, bg=BG)
        bar.pack(fill="x", padx=10, pady=8)
        self.bar = bar

        self.dot = tk.Canvas(bar, width=14, height=14, bg=BG, highlightthickness=0)
        self.dot.pack(side="left", padx=(2, 8))
        self._dot_id = self.dot.create_oval(2, 2, 12, 12, fill=OK, outline="")

        info = tk.Frame(bar, bg=BG)
        info.pack(side="left", fill="x", expand=True)
        self.title_lbl = tk.Label(info, text="Sentinel", bg=BG, fg=FG,
                                  font=("Segoe UI Semibold", 11), anchor="w")
        self.title_lbl.pack(fill="x")
        self.sub_lbl = tk.Label(info, text="ulanmoqda…", bg=BG, fg=DIM,
                                font=("Segoe UI", 9), anchor="w")
        self.sub_lbl.pack(fill="x")
        for w in (bar, info, self.title_lbl, self.sub_lbl):
            self._draggable(w)

        # o'ng tomon: kiritish va tugmalar
        right = tk.Frame(bar, bg=BG)
        right.pack(side="right")
        self.entry = tk.Entry(right, width=34, bg=CARD, fg=FG, insertbackground=FG,
                              relief="flat", font=("Segoe UI", 10))
        self.entry.pack(side="left", ipady=4, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self._send_task())
        self.opus_btn = self._btn(right, "⚡", self._toggle_strong, DIM, "Kuchli model (opus)")
        self.opus_btn.pack(side="left", padx=2)
        self._btn(right, "➤", self._send_task, ACCENT, "Topshiriq yuborish").pack(side="left", padx=2)
        self._btn(right, "⛔", self._stop, WARN, "To'xtatish").pack(side="left", padx=2)
        self._btn(right, "▾", self._toggle_details, DIM, "Tafsilot").pack(side="left", padx=2)
        self._btn(right, "✕", self.root.destroy, BAD, "Yopish").pack(side="left", padx=(2, 0))

        # pastki karta (tasdiq / tafsilot) — kerak bo'lganda
        self.card = tk.Frame(self.root, bg=BG)
        self.card.pack(fill="x", padx=10, pady=(0, 8))

        self._pin()  # doimiy ekran tepasida qolish

    def _pin(self):
        """Har 3 soniyada topmost'ni qayta tiklaydi — boshqa dastur ustidan bosib ketsa ham tepaga qaytadi."""
        try:
            self.root.attributes("-topmost", False)
            self.root.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.root.after(3000, self._pin)

    def _btn(self, parent, text, cmd, color, tip=""):
        b = tk.Button(parent, text=text, command=cmd, bg=CARD, fg=color, relief="flat",
                      activebackground="#21262d", activeforeground=FG, bd=0,
                      font=("Segoe UI", 11), width=3, cursor="hand2")
        return b

    def _draggable(self, widget):
        widget.bind("<Button-1>", self._drag_start)
        widget.bind("<B1-Motion>", self._drag_move)

    def _drag_start(self, e):
        self._dx, self._dy = e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y()

    def _drag_move(self, e):
        self.x = e.x_root - self._dx
        self.root.geometry(f"+{self.x}+{e.y_root - self._dy}")

    # ------------------------------------------------------------ amallar
    def _toggle_strong(self):
        self.strong = not self.strong
        self.opus_btn.configure(fg=ACCENT if self.strong else DIM)

    def _toggle_details(self):
        self.show_details = not self.show_details
        self._card_key = None
        self._render()

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
        self.title_lbl.configure(text=f"Sentinel · {text}")

    # ------------------------------------------------------------ chizish
    def _render(self):
        st = self.state
        pending = st.get("pending") or []
        tasks = st.get("tasks") or []
        connected = not self.err

        if not connected:
            color, title, sub = BAD, "Sentinel", self.err
        elif st.get("blocked"):
            color, title, sub = BAD, "Sentinel · limit", st["blocked"][:90]
        elif pending:
            color, title, sub = WARN, "Sentinel · tasdiq kutyapti", f"{len(pending)} ta so'rov"
        elif tasks:
            t = tasks[0]
            color, title = ACCENT, f"Sentinel · ishlayapti ({len(tasks)})"
            sub = f"{t['elapsed']} · {t['steps']} amal · {t.get('last') or t.get('text','')[:60]}"
        else:
            plan = st.get("plan", "obuna")
            last = (st.get("reply") or "").replace("\n", " ")
            color, title = OK, "Sentinel · tayyor"
            sub = f"{plan} · {st.get('model','')}" + (f" · oxirgi: {last[:60]}" if last else "")

        self.dot.itemconfigure(self._dot_id, fill=color)
        self.title_lbl.configure(text=title)
        self.sub_lbl.configure(text=sub or "—")

        # pastki karta: tasdiq birinchi o'rinda, aks holda tafsilot (toggle)
        key = ("pend", pending[0]["id"]) if pending else ("det", self.show_details)
        if key != self._card_key:
            self._card_key = key
            for w in self.card.winfo_children():
                w.destroy()
            if pending:
                self._render_pending(pending[0])
            elif self.show_details:
                self._render_details()
        self._resize()

    def _render_pending(self, p):
        box = tk.Frame(self.card, bg=CARD)
        box.pack(fill="x")
        head = f"{p['label']} · {p['task_id']}"
        tk.Label(box, text=head, bg=CARD, fg=WARN, font=("Segoe UI Semibold", 9), anchor="w").pack(fill="x", padx=10, pady=(8, 0))
        tk.Message(box, text=p.get("text") or "(matn yo'q)", bg=CARD, fg=FG, width=self.width - 40,
                   font=("Segoe UI", 10), anchor="w", justify="left").pack(fill="x", padx=10, pady=4)
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", padx=10, pady=(0, 8))
        if p["kind"] == "approval":
            tk.Button(row, text="✅ Ha", command=lambda: self._answer(p["id"], "yes"), bg=CARD, fg=OK,
                      relief="flat", bd=0, font=("Segoe UI", 10), cursor="hand2",
                      activebackground="#21262d").pack(side="left")
            tk.Button(row, text="❌ Yo'q", command=lambda: self._answer(p["id"], "no"), bg=CARD, fg=BAD,
                      relief="flat", bd=0, font=("Segoe UI", 10), cursor="hand2",
                      activebackground="#21262d").pack(side="left", padx=10)
        elif p["kind"] == "question":
            ent = tk.Entry(row, bg=BG, fg=FG, insertbackground=FG, relief="flat", font=("Segoe UI", 10))
            ent.pack(side="left", fill="x", expand=True, ipady=3)
            ent.bind("<Return>", lambda e: self._answer(p["id"], ent.get().strip()))
            tk.Button(row, text="Javob", command=lambda: self._answer(p["id"], ent.get().strip()),
                      bg=BG, fg=ACCENT, relief="flat", bd=0, font=("Segoe UI", 10), cursor="hand2").pack(side="left", padx=6)
        else:  # credential — maxfiy ma'lumot panelga yozilmaydi
            tk.Label(row, text="🔒 Maxfiy ma'lumotni Telegram orqali yuboring (panelga yozilmaydi).",
                     bg=CARD, fg=DIM, font=("Segoe UI", 9), anchor="w").pack(fill="x")

    def _render_details(self):
        st = self.state
        for t in st.get("tasks") or []:
            tk.Label(self.card, text=f"▶ {t['id']} · {t['elapsed']} · {t['steps']} amal · {t.get('last','')[:70]}",
                     bg=BG, fg=ACCENT, font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=4)
        acts = st.get("activity") or []
        if acts:
            tk.Label(self.card, text="Oxirgi amallar", bg=BG, fg=DIM,
                     font=("Segoe UI Semibold", 8), anchor="w").pack(fill="x", padx=4, pady=(6, 0))
            for a in acts:
                tk.Label(self.card, text=f"{a['ts']}  {a['text'][:80]}", bg=BG, fg=FG,
                         font=("Segoe UI", 9), anchor="w").pack(fill="x", padx=4)
        reply = (st.get("reply") or "").strip()
        if reply:
            tk.Label(self.card, text="Oxirgi javob", bg=BG, fg=DIM,
                     font=("Segoe UI Semibold", 8), anchor="w").pack(fill="x", padx=4, pady=(6, 0))
            tk.Message(self.card, text=reply[:600], bg=BG, fg=FG, width=self.width - 24,
                       font=("Segoe UI", 9), anchor="w", justify="left").pack(fill="x", padx=4)

    def _resize(self):
        self.root.update_idletasks()
        h = self.root.winfo_reqheight()
        self.root.geometry(f"{self.width}x{h}+{self.x}+{self.root.winfo_y()}")

    def run(self):
        self.root.mainloop()


def main() -> int:
    try:
        cfg = Config.from_env()
    except Exception as exc:  # noqa: BLE001
        print(f".env o'qilmadi: {exc}", file=sys.stderr)
        return 1
    paths = Paths(cfg.agent_home)
    AgentPanel(paths).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
