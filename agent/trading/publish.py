"""Telegram nashri: tahlil, natija yangilanishi (asl xabarga reply), kunlik hisobot.

Dublikatsiz: yuborishdan OLDIN bazaga 'sending' yozuvi (ref, chat, kind — birlamchi kalit). Tarmoq uzilib, xabar
ketgan-ketmagani noma'lum qolsa — 'unknown' (avtomatik qayta yuborilmaydi, egasiga aytiladi). Telegram aniq rad etsa
— 'failed' (keyingi urinishda qayta yuboriladi). message_id saqlanadi — natija yangilanishi shu xabarga bog'lanadi.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Awaitable, Callable

from .strategies import round_price

log = logging.getLogger(__name__)

LABEL = "🧪 RESEARCH ONLY / PAPER TRADING — gipotetik ssenariy, real savdo va moliyaviy maslahat EMAS. Foyda kafolatlanmaydi."
STATUS_TEXT = {
    "ACTIVE_SIMULATION": "▶️ gipotetik kirish sharti bajarildi — simulyatsiya boshlandi",
    "TP_HIT": "✅ virtual TP", "SL_HIT": "❌ virtual SL", "EXPIRED": "⌛ muddati tugadi (TP/SL yo'q)",
    "NOT_TRIGGERED": "⏸ kirish sharti bajarilmadi", "CANCELLED": "🚫 kirishdan oldin bekor bo'ldi",
    "AMBIGUOUS_DATA": "❔ ma'lumot noaniq — natija hisoblanmaydi",
}

SendFn = Callable[[int, str, int | None], Awaitable[dict]]


def _p(x: float | None) -> str:
    if x is None:
        return "—"
    s = f"{x:,.6f}".rstrip("0").rstrip(".")
    return s.replace(",", " ")


def _local(iso: str | None, tz) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso)
    return f"{dt.astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC ({dt.astimezone(tz):%H:%M} Toshkent)"


def format_analysis(rec: dict, tz) -> str:
    reg = rec.get("regime") or {}
    atr = reg.get("atr14")
    atr_txt = _p(round_price(atr, rec.get("last_close") or atr)) if isinstance(atr, (int, float)) else "—"
    ctx = (f"{reg.get('trend')} / volatillik {reg.get('volatility')}; ADX {reg.get('adx14')}, ATR {atr_txt}, "
           f"oxirgi yopilish {_p(rec.get('last_close'))}")
    head = ["🧪 TADQIQOT / QOG'OZ SAVDO (paper trading)", f"ANALYSIS ID: {rec['analysis_id']}",
            f"Instrument: {rec['symbol']} | Timeframe: {rec['timeframe']} | Sessiya: {rec.get('session')}",
            f"Vaqt: {_local(rec['created_at'], tz)}"]
    data = f"Ma'lumot: {rec.get('data_source')}; oxirgi yopilgan sham {_local(rec.get('data_ts'), tz)}"
    if rec["kind"] == "NO_TRADE":
        reasons = rec.get("no_trade_reasons") or []
        body = ["Qaror: NO-TRADE (bozor sharoiti mos emas)", f"Bozor konteksti: {ctx}", f"Tuzilma: {rec.get('structure')}",
                "Nega savdo yo'q:"] + [f"  • {r}" for r in reasons[:4]] + [data]
        return "\n".join(head + body + [LABEL])
    ev = ", ".join(f"{k}={_p(v) if isinstance(v, (int, float)) else v}" for k, v in list(rec["evidence"].items())[:6])
    entry_word = {"buy_stop": "Buy stop", "buy_limit": "Buy limit", "sell_stop": "Sell stop", "sell_limit": "Sell limit",
                  "next_open": "Keyingi sham ochilishida (bozor)"}[rec["entry_type"]]
    body = [
        f"Strategiya: {rec.get('strategy_name') or rec['strategy_id']} — {rec['strategy_id']} v{rec['strategy_version']}",
        f"Bozor konteksti: {ctx}",
        f"Tuzilma: {rec.get('structure')}",
        f"Gipotetik ssenariy: {rec['direction']} ({entry_word})",
        f"Kirish sharti: {entry_word} {_p(rec['entry'])}; amal muddati {_local(rec['valid_until'], tz)} gacha",
        f"Virtual SL / TP: {_p(rec['sl'])} / {_p(rec['tp'])}",
        f"Risk/reward: 1:{rec['rr']:.2f} (xarajatdan keyin 1:{rec['rr_net']:.2f})",
        f"Bekor qilish sharti: {rec['invalidation']['text']} ({_p(rec['invalidation']['level'])})",
        f"Texnik dalil: {ev}",
        "Farazlar: " + "; ".join(rec.get("assumptions") or []),
        data,
        "Cheklov: " + rec["limitations"][2] if len(rec.get("limitations") or []) > 2 else "",
    ]
    return "\n".join(head + [b for b in body if b] + [LABEL])


def format_outcome(rec: dict, outcome: dict, status: str) -> str:
    r = outcome.get("r_multiple")
    extra = f" — {r:+.2f}R (xarajat bilan)" if r is not None and status in ("TP_HIT", "SL_HIT", "EXPIRED") else ""
    return (f"📊 {rec['analysis_id']} ({rec['symbol']} {rec['timeframe']}): {STATUS_TEXT.get(status, status)}{extra}.\n"
            "Paper trading natijasi; asl ssenariy o'zgartirilmagan.")


class Publisher:
    def __init__(self, db, settings, send: SendFn, notify_owner: Callable[[str], Awaitable] | None = None,
                 clock: Callable[[], datetime] | None = None):
        self.db = db
        self.settings = settings
        self.send = send
        self.notify_owner = notify_owner
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def target(self) -> int | None:
        if not (self.settings.get("publish") or {}).get("enabled", True):
            return None
        return self.settings.group_chat_id

    async def _send(self, ref: str, kind: str, text: str, reply_to: int | None = None) -> str:
        from ..telegram_api import TelegramError, TelegramNetworkError

        chat = self.target()
        if chat is None:
            return "no_target"
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        existing = self.db.publication(ref, chat, kind)
        if existing and existing["status"] in ("sent", "sending", "unknown", "skipped"):
            return "duplicate"
        if existing is None and not self.db.claim_publication(ref, chat, kind, h):
            return "duplicate"
        if existing and existing["status"] == "failed":
            self.db.execute("UPDATE publications SET status='sending', text_hash=? WHERE ref=? AND chat_id=? AND kind=?",
                            (h, ref, chat, kind))
        try:
            msg = await self.send(chat, text, reply_to)
        except TelegramNetworkError as exc:  # ketgan-ketmagani noma'lum — qayta yuborilmaydi (dublikat xavfi)
            self.db.finish_publication(ref, chat, kind, "unknown", error=str(exc)[:300])
            if self.notify_owner:
                await self.notify_owner(f"⚠️ Trading: {ref} ({kind}) yuborilishi noma'lum (tarmoq). Dublikat bo'lmasligi "
                                        "uchun qayta yuborilmadi — guruhni tekshiring.")
            return "unknown"
        except TelegramError as exc:
            self.db.finish_publication(ref, chat, kind, "failed", error=str(exc)[:300])
            return "failed"
        self.db.finish_publication(ref, chat, kind, "sent", message_id=(msg or {}).get("message_id"))
        return "sent"

    async def publish_analysis(self, rec: dict) -> str:
        if self.target() is None:
            return "no_target"
        if not (self.settings.get("publish") or {}).get("analyses", True):
            return "disabled"  # V22: tadqiqot tahlillari faqat bazada; guruhga signal tizimi yozadi
        if rec.get("kind") == "TRADE" and rec.get("valid_until") and \
                datetime.fromisoformat(rec["valid_until"]) <= self.clock():
            return "stale"  # eskirgan ssenariy kech e'lon qilinmaydi
        return await self._send(rec["analysis_id"], "analysis", format_analysis(rec, self.settings.tz))

    async def publish_outcome(self, rec: dict, outcome: dict, status: str) -> str:
        if not (self.settings.get("publish") or {}).get("outcome_updates", True):
            return "disabled"
        chat = self.target()
        orig = self.db.publication(rec["analysis_id"], chat, "analysis") if chat is not None else None
        if not orig or orig["status"] != "sent":
            return "not_published"
        return await self._send(rec["analysis_id"], f"outcome:{status}", format_outcome(rec, outcome, status),
                                reply_to=orig["message_id"])

    async def publish_report(self, report_id: str, text: str) -> str:
        if not (self.settings.get("publish") or {}).get("daily_report", True):
            return "disabled"
        return await self._send(report_id, "report", text)

    async def recover(self) -> list[str]:
        """Qayta ishga tushganda: 'sending' qolgan yozuvlar — natijasi noma'lum (dublikat bo'lmasligi uchun)."""
        rows = self.db.query("SELECT ref, chat_id, kind FROM publications WHERE status='sending'")
        for r in rows:
            self.db.finish_publication(r["ref"], r["chat_id"], r["kind"], "unknown",
                                       error="agent yuborish paytida to'xtagan — natija noma'lum")
        if rows and self.notify_owner:
            await self.notify_owner("⚠️ Trading: " + ", ".join(f"{r['ref']} ({r['kind']})" for r in rows[:5]) +
                                    " yuborilayotganda agent to'xtagan. Qayta yuborilmadi — guruhni tekshiring.")
        return [r["ref"] for r in rows]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
