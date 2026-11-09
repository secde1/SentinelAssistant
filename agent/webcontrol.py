"""Veb-boshqaruv buyruqlari (control_commands jadvali). Dashboard (alohida jarayon) bu jadvalga yozadi, agent bajaradi.

Buyruqlar: mode <analysis|confirm|auto> | stop | flat | review <signal_id> | confirm <signal_id> | reject <signal_id>. Faqat DEMO; REAL hisobni DemoTrader baribir rad etadi.
Har buyruq natijasi jadvalda qoladi (jurnal). Noma'lum buyruq bajarilmaydi.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)
KNOWN = {"mode", "stop", "flat", "review", "confirm", "reject", "say", "zone"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class WebControl:
    def __init__(self, sv, notify=None, routine=None):
        self.sv, self.db, self.notify, self.routine = sv, sv.db, notify, routine
        self._bg: set = set()
        self.zone_trader = None  # app.py o'rnatadi

    async def process_pending(self) -> int:
        n = 0
        for row in self.db.query("SELECT * FROM control_commands WHERE status='pending' ORDER BY id LIMIT 10"):
            if self.db.execute("UPDATE control_commands SET status='running' WHERE id=? AND status='pending'", (row["id"],)).rowcount != 1:
                continue
            try:
                ok, msg = await self._run(row["cmd"], row["arg"] or "")
            except Exception as exc:  # noqa: BLE001
                log.exception("boshqaruv buyrug'i %s", row["cmd"])
                ok, msg = False, f"xato: {type(exc).__name__}: {str(exc)[:150]}"
            self.db.execute("UPDATE control_commands SET status=?, result=?, done_at=? WHERE id=?",
                            ("done" if ok else "failed", msg[:500], _now(), row["id"]))
            if self.notify is not None:
                await self.notify(f"🕹 Veb-boshqaruv: {row['cmd']} {row['arg'] or ''} -> {'OK' if ok else 'RAD'}: {msg[:300]}")
            n += 1
        return n

    async def _run(self, cmd: str, arg: str) -> tuple[bool, str]:
        sv = self.sv
        if cmd not in KNOWN:
            return False, f"noma'lum buyruq: {cmd}"
        if cmd == "mode":
            return sv.apply_mode(arg.strip().lower(), "veb-boshqaruv")
        if cmd == "stop":
            sv.set_trade_mode("confirm", "veb: to'xtatish")
            return True, "AUTO to'xtatildi (CONFIRMATION). Ochiq pozitsiyalar joyida."
        if cmd == "flat":
            if sv.trader is None:
                return False, "MT5 demo ulanmagan"
            res = await asyncio.to_thread(sv.flat_all)
            return True, "; ".join(res) or "ochiq pozitsiya yo'q"
        if cmd == "zone":  # DIR-1 zona vazifasini HOZIR bir marta ishga tushirish (sinov): bahs + hamma himoya + faqat DEMO
            if self.zone_trader is None:
                return False, "zona vazifasi ulanmagan"
            ok, why = self.zone_trader._enabled()
            if not ok:
                return False, "zona zdelkasi ishlamaydi: " + why
            t = asyncio.create_task(self.zone_trader.on_pass(manual=True, test=(arg.strip() in ("test", "force")), force=(arg.strip() == "force")), name="zona-sinov")
            self._bg.add(t)
            t.add_done_callback(self._bg.discard)
            return True, "DIR-1 zona vazifasi ishga tushdi — natija chatda va Signallar sahifasida"
        if cmd == "say":  # egasi chatga yozdi: uzoq davom etadi (LLM) — buyruqlar navbatini to'smaslik uchun fonda
            if self.routine is None:
                return False, "xodimlar bo'limi ulanmagan"
            t = asyncio.create_task(self.routine.handle_owner(arg), name="egasi-topshirigi")
            self._bg.add(t)
            t.add_done_callback(self._bg.discard)
            return True, "topshiriq qabul qilindi — natija chatda"
        if cmd in ("confirm", "reject"):
            # Egasi veb orqali HA/YO'Q: Telegram tugmasi bilan AYNAN bir xil yo'l (handle_callback) — barcha himoya o'zida.
            row = self.db.one("SELECT chat_id FROM signals WHERE signal_id=?", (arg.strip(),))
            if row is None:
                return False, "signal topilmadi"
            from .trading.signals import callback_data
            msg = await sv.handle_callback(callback_data(cmd, arg.strip()), sv.owner_user_id, row["chat_id"])
            return True, str(msg)[:250]
        # review: jamoa signalni muhokama qiladi; ruxsat bo'lsa va signal hali SENT bo'lsa — demo zdelka (barcha himoya bilan)
        row = self.db.one("SELECT * FROM signals WHERE signal_id=?", (arg.strip(),))
        if row is None:
            return False, "signal topilmadi"
        if sv.desk is None:
            return False, "xodimlar bo'limi ulanmagan"
        verdict = await sv.desk.review_signal(row)
        if not verdict.approve:
            return True, "bo'lim rad etdi: " + verdict.reason[:200]
        if not sv.demo_enabled or sv.cfg.get("sizing") != "risk":
            return True, "bo'lim ruxsat berdi, lekin demo savdo/sizing=risk yoqilmagan — zdelka ochilmadi"
        out = await sv.auto_confirm(row["signal_id"])
        return True, "bo'lim ruxsat berdi. " + (out or "signal allaqachon hal qilingan")[:250]

    async def run(self, every: float = 3.0) -> None:
        while True:
            try:
                await self.process_pending()
            except Exception:  # noqa: BLE001
                log.exception("boshqaruv sikli")
            await asyncio.sleep(every)
