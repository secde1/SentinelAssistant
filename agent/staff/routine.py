"""Xodimlarning davriy ishlari (LLM'SIZ — bazadagi faktlardan hisoblanadi) va egasining topshiriqlarini bajarish.

Maqsad: bo'limning har xodimi ko'rinadigan ish qilsin. Davriy hisobotlar sof ma'lumot; hech biri buyurtma bermaydi.
Egasi topshirig'i (`handle_owner`): DIR-1 vazifalarni taqsimlaydi, xodimlar BAJARADI. Xodim FAQAT matn/tahlil qaytaradi —
xavf limitlari, lot/SL va REAL hisobni o'zgartirish yoki zdelka ochish ularning qo'lida emas (bunday topshiriqni sababi bilan rad etadi).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from . import context as C
from . import roster as R
from .desk import parse_json

log = logging.getLogger(__name__)

# rol -> (interval soniya, funksiya nomi). Boshlanish siljitilgan: hammasi birdan chiqmasin.
SCHEDULE = {
    "RISK-1": 1800, "HIST-MA": 7200, "HIST-TF": 7200, "HIST-VOL": 7200, "STRAT-1": 7200,
    "NEWS-1": 10800, "AUDIT-1": 21600, "DIR-1": 7200,
}
OWNER_LLM_PER_HOUR = 24
LIMITS = ("Cheklov: xavf limitlari (risk %, kunlik zarar, max pozitsiya), lot, SL va REAL hisob xodimlar tomonidan o'zgartirilmaydi. "
          "Xodimlar buyurtmani o'zlari yubormaydi. Zdelka DIR-1 ning zona vazifasi orqali AVTOMATIK ochiladi (har skanerdan keyin: signal -> bahs -> "
          "himoyalar -> faqat DEMO), egasining tasdig'i shart emas. Egasi savol bersa — savolga javob ber, zdelka ochma; holatni "
          "'DIR-1 ZONA ZDELKA VAZIFASI' ma'lumotidan aytib ber (nima uchun ochilmagani ham). Zdelkani qo'lda sinash faqat veb 'Boshqaruv' tugmasida.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StaffRoutine:
    def __init__(self, desk, db, cfg_fn, calendar=None):
        self.desk, self.db, self.cfg_fn, self.calendar = desk, db, cfg_fn, calendar
        self._due: dict[str, float] = {}
        self._owner_calls: list[float] = []
        t = time.time()
        for i, role in enumerate(SCHEDULE):  # birinchi hisobotlar ~1-4 daqiqada, bir-biridan ajratilgan
            self._due[role] = t + 60 + 25 * i

    # ------------------------------------------------------------------ davriy hisobotlar (LLM'siz)
    def report(self, role: str) -> str:
        cfg = self.cfg_fn()
        if role == "RISK-1":
            return "Himoyalar holati. " + C.risk_status(self.db, cfg)
        if role in ("HIST-MA", "HIST-TF", "HIST-VOL"):
            prefix = {"HIST-MA": "MA", "HIST-TF": "TF", "HIST-VOL": "VOL"}[role]
            s = C.strategy_stats(self.db, prefix)
            if not s:
                return f"{prefix}* strategiyasi bo'yicha oxirgi 7 kunda signal yo'q — yangi tarixiy xulosa yo'q."
            return "Tarixiy xulosa (7 kun): " + "; ".join(
                f"{x['strategy']}: {x['signals_7d']} signal (STRONG {x['strong']}, CONFIRM {x['confirm']}), paper {x['paper_n']} ta o'rtacha {x['paper_avg_r']} R, "
                f"DEMO {x['demo_n']} ta net {x['demo_net']}" for x in s) + (". Namuna kichik — xulosa ishonchsiz." if all(x["paper_n"] + x["demo_n"] < 30 for x in s) else "")
        if role == "STRAT-1":
            s = [x for x in C.strategy_stats(self.db) if x["paper_n"] >= 1]
            if not s:
                return "Strategiya reytingi: natijasi yopilgan paper zdelka hali yo'q — reyting tuzib bo'lmaydi."
            s.sort(key=lambda x: -(x["paper_avg_r"] or -9))
            return "Strategiya reytingi (paper o'rtacha R): " + "; ".join(f"{x['strategy']} {x['paper_avg_r']} R ({x['paper_n']} ta)" for x in s[:6]) + \
                ". Hech biri isbotlangan foydali emas (namuna kichik)."
        if role == "NEWS-1":
            if self.calendar is None:
                return "Kalendar ulanmagan."
            try:
                evs = self.calendar.near(datetime.now(timezone.utc), hours=12.0, currencies=("USD", "EUR", "GBP"))
            except Exception as exc:  # noqa: BLE001
                return f"Kalendar xatosi: {type(exc).__name__}"
            if evs is None:
                return "Kalendar ma'lumoti hozir yo'q (noma'lum, taxmin qilinmaydi)."
            return "Yaqin 12 soatda High hodisa: " + ("; ".join(f"{e['title']} ({e['country']}) {e['date']}" for e in evs[:6]) if evs else "yo'q")
        if role == "AUDIT-1":
            r = self.db.one("SELECT COUNT(*) n, COALESCE(SUM(net),0) s, COALESCE(SUM(net<0),0) l FROM live_trades WHERE closed_at >= ?", (C._iso(24),)) or {}
            return f"24 soatlik audit: {r.get('n', 0)} ta yopilgan, {r.get('l', 0)} tasi zarar, jami {r.get('s', 0):.2f}. Zararli zdelkalar alohida tahlil qilinadi."
        if role == "DIR-1":
            z = (self.db.one("SELECT COUNT(*) n, COALESCE(SUM(status='active'),0) a, COUNT(DISTINCT symbol) s FROM zones") or {})
            sg = (self.db.one("SELECT COUNT(*) n FROM signals WHERE created_at >= ?", (C._iso(2),)) or {}).get("n", 0)
            return (f"Smena hisoboti: zonalar {z.get('n', 0)} ({z.get('a', 0)} aktiv, {z.get('s', 0)} instrument), oxirgi 2 soatda {sg} signal, "
                    f"{(self.db.one('SELECT COUNT(*) n FROM position_snapshot') or {}).get('n', 0)} ochiq pozitsiya. " + C.risk_status(self.db, cfg).split("|")[0])
        return ""

    def tick(self) -> int:
        """Muddati kelgan davriy hisobotlarni chatga yozadi. Qaytaradi: yozilganlar soni."""
        n, now = 0, time.time()
        for role, every in SCHEDULE.items():
            if now < self._due.get(role, 0):
                continue
            self._due[role] = now + every
            try:
                text = self.report(role)
            except Exception as exc:  # noqa: BLE001
                log.exception("davriy ish %s", role)
                text = f"Hisobot tuzilmadi ({type(exc).__name__})"
            if text:
                self.desk.say(role, "report", text, None)
                n += 1
        return n

    # ------------------------------------------------------------------ egasi topshiriqlari
    def _budget(self, need: int) -> bool:
        cut = time.time() - 3600
        self._owner_calls = [t for t in self._owner_calls if t > cut]
        if len(self._owner_calls) + need > OWNER_LLM_PER_HOUR:
            return False
        self._owner_calls += [time.time()] * need
        return True

    async def handle_owner(self, text: str) -> None:
        """Egasi chatga yozdi: DIR-1 vazifalarni taqsimlaydi, xodimlar bajaradi, DIR-1 yakunlaydi. Xato bo'lsa — ochiq yoziladi."""
        d = self.desk
        text = (text or "").strip()[:500]
        ref = f"OWN-{int(time.time()) % 10_000_000}"
        d.say("OWNER", "owner", text, ref)
        if d.llm is None:
            d.say(R.DIRECTOR.id, "system", "Xodimlar LLM bilan ulanmagan — topshiriq bajarilmadi.", ref)
            return
        if not self._budget(6):
            d.say(R.DIRECTOR.id, "system", f"Soatlik topshiriq limiti ({OWNER_LLM_PER_HOUR} so'rov) tugagan — keyinroq qayta yozing. (Obuna kvotasini saqlash.)", ref)
            return
        try:
            ctx = C.pack(self.db, self.cfg_fn())
            roles = ", ".join(f"{m.id} ({m.title})" for m in R.ALL if m.id != R.DIRECTOR.id)
            raw = await d._ask(R.DIRECTOR, f"EGASI TOPSHIRIG'I: {text}\n\nMA'LUMOT:\n{ctx}\n\nXodimlar: {roles}\n{LIMITS}\n"
                               'Topshiriqni mos xodimlarga (1-4 ta) taqsimla. FAQAT JSON: {"assign":[{"role":"ZONE-1","task":"aniq vazifa"}],"note":"qisqa"}. '
                               "Egasi aytganini so'zsiz bajar: bahslashma, ortiqcha shart qo'yma.")
            plan = parse_json(raw) or {}
            assigns = [a for a in plan.get("assign", []) if isinstance(a, dict) and a.get("role") in R.BY_ID and a.get("role") != R.DIRECTOR.id][:4]
            if not assigns:
                assigns = [{"role": "DEBATE-A", "task": text}]
            d.say(R.DIRECTOR.id, "assign", "Vazifalar: " + "; ".join(f"{a['role']} — {str(a.get('task', ''))[:120]}" for a in assigns) +
                  (f". {str(plan.get('note', ''))[:200]}" if plan.get("note") else ""), ref)

            async def run(a):
                m = R.BY_ID[a["role"]]
                try:
                    out = await d._ask(m, f"MA'LUMOT (bazadan):\n{ctx}\n\nEGASI TOPSHIRIG'I: {text}\nSENING VAZIFANG: {a.get('task') or text}\n{LIMITS}\n"
                                       "Vazifani to'liq bajar, aniq natija ber (raqamlar, instrumentlar). Ma'lumotda yo'q narsani o'ylab topma.")
                    d.say(m.id, "task-result", out.strip(), ref)
                    return m.id, out.strip()
                except Exception as exc:  # noqa: BLE001
                    d.say(m.id, "system", f"Vazifa bajarilmadi ({type(exc).__name__}: {str(exc)[:100]})", ref)
                    return m.id, f"(bajarilmadi: {type(exc).__name__})"
            results = await asyncio.gather(*(run(a) for a in assigns))
            summary = "\n".join(f"{r}: {t[:600]}" for r, t in results)
            final = await d._ask(R.DIRECTOR, f"EGASI TOPSHIRIG'I: {text}\n\nXODIMLAR NATIJASI:\n{summary}\n"
                                 "Egasiga 3-5 gapda yakuniy javob ber: nima topildi/bajarildi, nima bajarilmadi (sababi bilan), keyingi qadam.")
            d.say(R.DIRECTOR.id, "owner-reply", final.strip(), ref)
        except Exception as exc:  # noqa: BLE001 — kvota/tarmoq: ochiq aytiladi
            log.exception("egasi topshirig'i")
            d.say(R.DIRECTOR.id, "system", f"Topshiriq yakunlanmadi ({type(exc).__name__}: {str(exc)[:120]}).", ref)

    async def run(self) -> None:
        await asyncio.sleep(45)
        while True:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("xodimlar davriy ishi")
            await asyncio.sleep(30)
