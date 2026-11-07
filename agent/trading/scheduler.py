"""Trading jadvali: 10 ta tahlil sloti, natija yangilash, kunlik tadqiqot, kunlik/haftalik hisobot.

Holat bazada (jobs): qayta ishga tushganda davom etadi. Agent o'chiq paytdagi tahlil slotlari 'missed' deb yoziladi
va O'TGAN vaqt uchun tahlil o'ylab topilmaydi (kelajak ma'lumotini ishlatib bo'lmaydi). Hisobot — siyosatga ko'ra
qayta ishga tushganda yaratiladi. Xatolar qayta urinish bilan (slot oynasi ichida).
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable

from ..config import daily_time
from .data import DataUnavailable
from .db import utcnow
from .publish import Publisher, format_analysis
from .research import research_prompt
from .service import TradingService

log = logging.getLogger(__name__)


def _at(day: str, hm: str, tz) -> datetime:
    h, m = daily_time(hm) or (0, 0)
    d = date.fromisoformat(day)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=tz).astimezone(timezone.utc)


class TradingScheduler:
    def __init__(self, service: TradingService, publisher: Publisher, notify_owner: Callable[[str], Awaitable],
                 submit_research: Callable[[str], Awaitable[str | None]] | None = None, journal=None,
                 can_submit: Callable[[], str | None] | None = None):
        self.svc = service
        self.pub = publisher
        self.notify_owner = notify_owner
        self.submit_research = submit_research
        self.can_submit = can_submit or (lambda: None)  # obuna limiti tugagan bo'lsa — sababi (yuborilmaydi)
        self.journal = journal
        self._last_outcomes = datetime.min.replace(tzinfo=timezone.utc)
        self.signals = None  # SignalService (app.py da o'rnatiladi)
        self.monitor = None  # PositionMonitor (V24)
        self._last_monitor = datetime.min.replace(tzinfo=timezone.utc)
        self._monitor_started = False
        self._last_signals = datetime.min.replace(tzinfo=timezone.utc)

    @property
    def settings(self):
        return self.svc.settings

    # ------------------------------------------------------------------ hayot sikli
    async def run(self) -> None:
        try:
            await self.recover(self.svc.clock())
        except Exception:  # noqa: BLE001
            log.exception("trading jadvali tiklanmadi")
        while True:
            try:
                await self.tick(self.svc.clock())
            except Exception:  # noqa: BLE001
                log.exception("trading jadvali qadami")
            await asyncio.sleep(30)

    def _event(self, event_type: str, text: str, **fields) -> None:
        if self.journal is not None:
            self.journal.event(event_type, text, **fields)

    async def recover(self, now: datetime) -> dict:
        """Qayta ishga tushish: to'xtab qolgan vazifalar, o'tkazib yuborilgan slotlar, noma'lum nashrlar, hisobot."""
        db, tz = self.svc.db, self.settings.tz
        window = timedelta(minutes=int(self.settings["retry"]["slot_window_min"]))
        stuck = db.query("SELECT job_key FROM jobs WHERE status='running'")
        for j in stuck:
            db.update_job(j["job_key"], status="pending", last_error="agent ish paytida to'xtagan")
        missed = []
        today = self.settings.local(now).date()
        for d in (today - timedelta(days=1), today):
            day = d.isoformat()
            for idx, hm in enumerate(self.settings["analysis_slots"]):
                when = _at(day, hm, tz)
                if when < self.svc.installed_at:
                    continue  # modul hali o'rnatilmagan edi
                key = f"analysis:{day}:{idx + 1:02d}"
                job = db.ensure_job(key, "analysis", when.isoformat())
                if job["status"] in ("pending",) and now > when + window:
                    db.update_job(key, status="missed", finished_at=utcnow(),
                                  last_error="agent o'chiq bo'lgan — o'tgan vaqt uchun tahlil yaratilmaydi")
                    missed.append(key)
        if missed:
            self._event("trading_missed", f"Trading: {len(missed)} ta tahlil sloti o'tkazib yuborildi (agent o'chiq)",
                        jobs=missed)
        unknown = await self.pub.recover()
        policy = self.settings["missed_policy"]
        yday = (today - timedelta(days=1)).isoformat()
        if policy.get("report") == "run_on_startup" and not db.one("SELECT 1 FROM reports WHERE report_id=?",
                                                                    (f"daily-{yday}",)):
            if db.one("SELECT 1 FROM analyses WHERE local_date=?", (yday,)):
                await self._report(yday, now, late=True)
        return {"stuck": [j["job_key"] for j in stuck], "missed": missed, "unknown_publications": unknown}

    async def tick(self, now: datetime) -> None:
        local_day = self.settings.local(now).strftime("%Y-%m-%d")
        await self._analysis_slots(local_day, now)
        await self._signals(now)
        await self._monitor(now)
        if (now - self._last_outcomes).total_seconds() >= int(self.settings["outcome_poll_sec"]):
            self._last_outcomes = now
            await self._outcomes()
        await self._daily_job(local_day, now, "research", self.settings["research_at"], self._research)
        await self._research_followup(local_day, now)
        await self._library_refresh(now)
        await self._daily_job(local_day, now, "report", self.settings["report_at"],
                              lambda: self._report(local_day, now))
        if self.settings.local(now).weekday() == 6:
            await self._daily_job(local_day, now, "weekly", self.settings["report_at"],
                                  lambda: self._weekly(local_day))

    # ------------------------------------------------------------------ MT5 pozitsiya monitoringi (V24)
    async def _monitor(self, now: datetime) -> None:
        m = self.monitor
        if m is None:
            return
        try:
            done = m.startup_tasks(now)  # bir martalik: shaxsiy chatga TEST, qayta yuborish
            if done:
                self._event("mt5_monitor", "Monitor bir martalik vazifalar: " + ", ".join(done))
            if m.cfg.get("enabled", True) and \
                    (now - self._last_monitor).total_seconds() >= int(m.cfg.get("poll_sec", 60)):
                self._last_monitor = now
                if not self._monitor_started:
                    self._monitor_started = True
                    m.downtime_alert(now)
                res = await asyncio.to_thread(m.poll_once, now)
                if res.opened or res.modified or res.closed or res.backfilled or res.error:
                    self._event("mt5_monitor", f"MT5 monitor: ochildi {res.opened}, o'zgardi {res.modified}, yopildi "
                                               f"{res.closed}, tarixdan {res.backfilled}" + (f", xato: {res.error}" if res.error else ""))
            await m.q.flush()  # navbat har qadamda: Telegram tiklansa, kutayotgan xabarlar yuboriladi
        except Exception as exc:  # noqa: BLE001 — monitor xatosi boshqa vazifalarni to'xtatmasin
            log.exception("MT5 monitor")
            with suppress(Exception):  # soatiga bitta MONITORING ERROR (shaxsiy chat)
                m.q.enqueue(f"pv:monerr:{now:%Y%m%d%H}", "alert", "private",
                            f"⚠️ SENTINEL | MONITORING ERROR\nMT5 monitor ichki xato: {type(exc).__name__}: {str(exc)[:160]}")

    # ------------------------------------------------------------------ signallar (V22)
    async def _signals(self, now: datetime) -> None:
        sv = self.signals
        if sv is None or sv.mode == "off":
            return
        if (now - self._last_signals).total_seconds() < int((self.settings.get("signals") or {}).get("scan_sec", 900)):
            return
        self._last_signals = now
        try:
            res = await sv.scan_once()
            await sv.track()
            if res["sent"] or res["dry"] or res["errors"]:
                self._event("trading_signals", f"Signal skaneri ({sv.mode}): " + ", ".join(
                    f"{k}={v}" for k, v in res.items() if k != "errors" and v), errors=res["errors"][:5])
        except Exception:  # noqa: BLE001 — skaner xatosi boshqa vazifalarni to'xtatmasin
            log.exception("signal skaneri")

    # ------------------------------------------------------------------ tahlil slotlari
    async def _analysis_slots(self, day: str, now: datetime) -> None:
        db, tz = self.svc.db, self.settings.tz
        retry = self.settings["retry"]
        window = timedelta(minutes=int(retry["slot_window_min"]))
        for idx, hm in enumerate(self.settings["analysis_slots"][:int(self.settings["daily_target"])]):
            when = _at(day, hm, tz)
            if when + window < self.svc.installed_at:
                continue  # o'rnatilishdan oldingi slot
            key = f"analysis:{day}:{idx + 1:02d}"
            job = db.ensure_job(key, "analysis", when.isoformat())
            if job["status"] not in ("pending",) or now < when:
                continue
            if now > when + window:
                db.update_job(key, status="missed", finished_at=utcnow(), last_error=job["last_error"] or
                              "slot oynasi o'tib ketdi")
                continue
            if job["attempts"] and job["started_at"] and \
                    now < datetime.fromisoformat(job["started_at"]) + timedelta(seconds=int(retry["delay_sec"])):
                continue
            await self.run_analysis_job(key, day, idx)

    async def run_analysis_job(self, key: str, day: str, idx: int) -> dict | None:
        db = self.svc.db
        job = db.job(key)
        attempts = (job["attempts"] or 0) + 1
        # vaqt — xizmat soatidan (qayta urinish oralig'i shu soat bilan o'lchanadi)
        db.update_job(key, status="running", attempts=attempts, started_at=self.svc.clock().isoformat(timespec="seconds"))
        try:
            rec = await asyncio.to_thread(self.svc.analysis_for_slot, day, idx)
        except DataUnavailable as exc:
            final = attempts >= int(self.settings["retry"]["attempts"])
            db.update_job(key, status="failed" if final else "pending", last_error=str(exc)[:500],
                          finished_at=utcnow() if final else None)
            self._event("trading_data", f"Trading slot {key}: ma'lumot yo'q ({attempts}-urinish)", error=str(exc)[:300])
            return None
        except Exception as exc:  # noqa: BLE001
            final = attempts >= int(self.settings["retry"]["attempts"])
            db.update_job(key, status="failed" if final else "pending", last_error=f"{type(exc).__name__}: {exc}"[:500])
            log.exception("trading tahlil sloti %s", key)
            return None
        db.update_job(key, status="done", finished_at=utcnow(), result=rec["analysis_id"])
        self._event("trading_analysis", f"Trading tahlil {rec['analysis_id']}: {rec['symbol']} {rec['timeframe']} "
                                        f"{rec['kind']}", analysis=rec["analysis_id"], kind=rec["kind"])
        await self.publish(rec)
        return rec

    async def publish(self, rec: dict) -> str:
        status = await self.pub.publish_analysis(rec)
        if status == "no_target":
            log.info("trading: guruh ulanmagan — %s faqat bazada", rec["analysis_id"])
        return status

    async def run_now(self, symbol: str | None = None, timeframe: str | None = None) -> dict:
        """Egasi so'ragan qo'shimcha tahlil (/trading_tahlil)."""
        if symbol:
            rec = await asyncio.to_thread(self.svc.create_analysis, symbol, timeframe or "1h")
        else:
            day = self.svc.local_today()
            n = self.svc.db.one("SELECT COUNT(*) AS n FROM analyses WHERE local_date=?", (day,))["n"]
            rec = await asyncio.to_thread(self.svc.analysis_for_slot, day, n)
        status = await self.publish(rec)
        rec["_publication"] = status
        return rec

    # ------------------------------------------------------------------ natijalar
    async def _outcomes(self) -> None:
        changes = await asyncio.to_thread(self.svc.update_outcomes)
        for row, status in changes:
            from .analysis import load
            rec = load(self.svc.db, row["analysis_id"])
            outcome = self.svc.db.outcome(row["analysis_id"]) or {}
            self._event("trading_outcome", f"Trading {row['analysis_id']}: {status}", analysis=row["analysis_id"],
                        status=status, r=outcome.get("r_multiple"))
            if status != "PENDING":
                await self.pub.publish_outcome(rec, outcome, status)

    # ------------------------------------------------------------------ kunlik vazifalar
    async def _daily_job(self, day: str, now: datetime, kind: str, at: str, fn) -> None:
        if not daily_time(at or ""):
            return
        when = _at(day, at, self.settings.tz)
        key = f"{kind}:{day}"
        job = self.svc.db.ensure_job(key, kind, when.isoformat())
        if job["status"] != "pending" or now < when:
            return
        if job["attempts"] and job["started_at"]:  # qayta urinishlar orasida 10 daqiqa
            last = datetime.fromisoformat(job["started_at"])
            if (last.tzinfo and now < last + timedelta(minutes=10)):
                return
        policy = self.settings["missed_policy"].get(kind, "run_if_same_day")
        if now - when > timedelta(hours=2) and policy == "skip":
            self.svc.db.update_job(key, status="missed", finished_at=now.isoformat(timespec="seconds"))
            return
        self.svc.db.update_job(key, status="running", attempts=(job["attempts"] or 0) + 1,
                               started_at=now.isoformat(timespec="seconds"))
        try:
            result = await fn()
            self.svc.db.update_job(key, status="done", finished_at=self.svc.clock().isoformat(timespec="seconds"),
                                   result=str(result or "")[:200])
        except Exception as exc:  # noqa: BLE001
            attempts = (job["attempts"] or 0) + 1
            self.svc.db.update_job(key, status="failed" if attempts >= 3 else "pending",
                                   last_error=f"{type(exc).__name__}: {exc}"[:500])
            log.warning("trading %s: %s", key, exc)

    async def _report(self, day: str, now: datetime, late: bool = False) -> str:
        text, _data = await asyncio.to_thread(self.svc.daily_report, day)
        if late:
            text = "(Kechikkan hisobot — agent o'z vaqtida ishlamagan edi)\n" + text
        await self.pub.publish_report(f"daily-{day}", text)
        await self.notify_owner(text)
        return f"daily-{day}"

    async def _weekly(self, day: str) -> str:
        text, _ = await asyncio.to_thread(self.svc.weekly_report, day)
        await self.pub.publish_report(f"weekly-{day}", text)
        await self.notify_owner(text)
        return f"weekly-{day}"

    async def _library_refresh(self, now: datetime) -> None:
        """Strategiyalar kutubxonasidagi tarixiy sinov natijalari (har N kunda, xarajat bilan)."""
        last = self.svc.db.get_meta("library_refreshed")
        days = int(self.settings.get("library_refresh_days", 7))
        if last:
            try:
                ts = datetime.fromisoformat(last)
                if (ts.tzinfo and now - ts < timedelta(days=days)) or getattr(self, "_lib_running", False):
                    return
            except ValueError:
                pass
        self._lib_running = True
        try:
            done = []
            for item in self.settings.get("library_universe") or []:
                try:
                    await asyncio.to_thread(self.svc.refresh_library, item["symbol"], item["timeframe"])
                    done.append(f"{item['symbol']} {item['timeframe']}")
                except DataUnavailable as exc:
                    self.svc.db.warn(item["symbol"], item["timeframe"], "library_data", str(exc))
            if done:
                self._event("trading_library", "Strategiyalar tarixiy sinovi yangilandi: " + ", ".join(done))
        finally:
            self._lib_running = False

    async def _research_followup(self, day: str, now: datetime) -> None:
        """Yuborilgan tadqiqot 45 daqiqada bitta ham manba yozmagan bo'lsa (limit, xato) — qayta urinish (max 3)."""
        db = self.svc.db
        job = db.job(f"research:{day}")
        if not job or job["status"] != "done" or not job["result"] or not job["finished_at"]:
            return
        if (job["attempts"] or 0) >= 3:
            return
        try:
            finished = datetime.fromisoformat(job["finished_at"])
        except ValueError:
            return
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        if now - finished < timedelta(minutes=45):
            return
        got = db.one("SELECT COUNT(*) AS n FROM research_sources WHERE task_id=?", (job["result"],))["n"]
        if got:
            return
        blocked = self.can_submit()
        if blocked:
            return  # limit tiklanishini kutamiz
        db.update_job(f"research:{day}", status="pending",
                      last_error=f"{job['result']} hech qanday manba yozmadi — qayta urinish")
        self._event("trading_research", f"Trading tadqiqoti qayta yuboriladi ({job['result']} natijasiz)",
                    task=job["result"])

    async def _research(self) -> str | None:
        if self.submit_research is None:
            return None
        blocked = self.can_submit()
        if blocked:
            raise RuntimeError(f"tadqiqot yuborilmadi: {blocked[:120]}")
        day = self.svc.local_today()
        prompt = research_prompt(self.settings, day)
        return await self.submit_research(prompt)


__all__ = ["TradingScheduler", "format_analysis"]
