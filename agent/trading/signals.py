"""SENTINEL signal tizimi (V22): skaner -> ball -> Telegram signal (callback tugmalar) -> faqat PAPER savdo.

Xavfsizlik (kod darajasida):
  • broker/birja/MT5 ga buyurtma YO'Q: "HA" faqat paper_positions jadvaliga yozadi (simulyatsiya);
  • tugmani faqat egasi (owner_user_id) va faqat shu signal yuborilgan guruhda bosa oladi; boshqalar — hech narsa o'zgarmaydi;
  • har signal bir marta hal qilinadi: holat atomik UPDATE ... WHERE status='SENT' bilan o'zgaradi (qayta bosish, ikki
    tugma bir vaqtda — faqat birinchisi o'tadi);
  • muddati o'tgan, bekor qilish sharti buzilgan yoki narxi ancha o'zgargan signal tasdiqlanmaydi;
  • dublikat: bir instrument + yo'nalish uchun faol signal yoki cooldown ichidagi signal qayta yuborilmaydi;
  • ma'lumot yetishmasa yoki eskirgan bo'lsa signal yaratilmaydi; hech qachon narx/indikator to'qilmaydi.
Rejimlar (settings["signals"]["mode"]): off — hech narsa; dry — skanerlaydi va bazaga yozadi, Telegramga YUBORMAYDI; live.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from .data import TF_SECONDS, DataUnavailable
from .indicators import Features
from .outcomes import PENDING, Scenario, simulate
from .signal_score import MAX_SCORE, Score, evaluate, trend_of
from .strategies import NoSetup, candidates, classify_regime, round_price

log = logging.getLogger(__name__)

ACTIVE_STATES = ("NEW", "SENDING", "SENT", "CONFIRMING", "CONFIRMED")
CB_PREFIX = "sentinel"
FIFTEEN = TF_SECONDS["15m"]
STATUS_LABEL = {
    "REJECTED": "❌ RAD ETILDI — pozitsiya ochilmadi",
    "EXPIRED": "⌛ MUDDATI O'TDI — tasdiqlanmadi",
    "INVALIDATED": "🚫 BEKOR BO'LDI — signal kuchini yo'qotdi",
    "CONFIRMED": "✅ TASDIQLANDI — PAPER pozitsiya ochildi (simulyatsiya, real order emas)",
}
OUTCOME_TEXT = {
    "ACTIVE_SIMULATION": "▶️ kirish sharti bajarildi — paper pozitsiya ochildi",
    "TP_HIT": "✅ virtual TP", "SL_HIT": "❌ virtual SL", "EXPIRED": "⌛ muddati tugadi (TP/SL yo'q)",
    "NOT_TRIGGERED": "⏸ kirish sharti muddat ichida bajarilmadi", "CANCELLED": "🚫 kirishdan oldin bekor bo'ldi",
    "AMBIGUOUS_DATA": "❔ ma'lumot noaniq — natija hisoblanmaydi",
}

SendFn = Callable[[int, str, dict | None, int | None], Awaitable[dict]]
EditFn = Callable[[int, int, str], Awaitable[None]]


def now_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _p(x: float | None) -> str:
    return "—" if x is None else f"{x:,.6f}".rstrip("0").rstrip(".").replace(",", " ")


def callback_data(action: str, signal_id: str) -> str:
    data = f"{CB_PREFIX}:{action}:{signal_id}"
    assert len(data.encode()) <= 64, "callback_data 64 baytdan oshmasligi kerak"
    return data


def parse_callback(data: str) -> tuple[str, str] | None:
    parts = (data or "").split(":")
    if len(parts) == 3 and parts[0] == CB_PREFIX and parts[1] in ("confirm", "reject") and parts[2]:
        return parts[1], parts[2]
    return None


def keyboard(signal_id: str, direction: str) -> dict:
    word = "SELL" if direction == "SHORT" else "BUY"
    return {"inline_keyboard": [[{"text": f"✅ HA — {word}", "callback_data": callback_data("confirm", signal_id)},
                                 {"text": "❌ YO'Q", "callback_data": callback_data("reject", signal_id)}]]}


# -------------------------------------------------------------------------------------------- tarixiy sinov izohi
_LAB_KEYS = {"BTCUSDT": "BTCUSDm", "ETHUSDT": "ETHUSDm", "XAU/USD": "XAUUSDm", "EUR/USD": "EURUSDm"}


def history_note(lab_file: Path, symbol: str, strategy_id: str, timeframe: str) -> str:
    """5 yillik tarixiy sinov natijasi (research/ laboratoriyasi). Yo'q bo'lsa — "mavjud emas" (taxmin qilinmaydi)."""
    key = _LAB_KEYS.get(symbol)
    try:
        d = json.loads(Path(lab_file).read_text(encoding="utf-8"))
        r = d[f"{key}|{timeframe}|{strategy_id}|net"]["all"]
        return (f"{strategy_id} {symbol} {timeframe}: 5 yillik tarixiy sinov, xarajatdan keyin E={r['expectancy']:+.3f}R, "
                f"{r['n']} savdo, 95% CI [{r['ci_lo']:+.2f}; {r['ci_hi']:+.2f}] — ishonchli foyda isboti EMAS")
    except (OSError, KeyError, ValueError, TypeError):
        return f"{strategy_id} {symbol} {timeframe}: tarixiy sinov natijasi mavjud emas"


# -------------------------------------------------------------------------------------------- xabar formati
def format_signal(sig: dict, score: Score, tz, hist_note: str, source: str, data_ts: datetime) -> str:
    long = sig["direction"] == "LONG"
    side = "BUY" if long else "SELL"
    title = "STRONG SIGNAL" if score.tier == "STRONG" else "SIGNAL (6-7/10, qo'shimcha tasdiq bor)"
    entry_word = {"buy_stop": "buy stop", "buy_limit": "buy limit", "sell_stop": "sell stop", "sell_limit": "sell limit",
                  "next_open": "keyingi sham ochilishida"}[sig["entry_type"]]
    by = {i.key: i for i in score.items}

    def row(label: str, key: str) -> str:
        it = by[key]
        mark = "✅" if it.ok else ("❔" if it.ok is None else "▫️")
        return f"• {label}: {it.detail} {mark}"
    reasons = [f"{n}. {it.label}: {it.detail}" for n, it in enumerate(score.passed()[:3], 1)]
    local = data_ts.astimezone(tz)
    lines = [
        f"🚨 SENTINEL | {title}", "",
        f"💎 Symbol: {sig['symbol']}", f"📊 Direction: {side}",
        f"⭐ Score: {score.score}/{MAX_SCORE} (bajarilgan tekshiruv mezonlari soni — g'alaba ehtimoli emas)", "",
        f"ENTRY: {_p(sig['entry'])} ({entry_word})", f"STOP LOSS: {_p(sig['sl'])}",
        f"TAKE PROFIT 1: {_p(sig['tp'])}",
        f"Risk/Reward: 1:{sig['rr_net']:.2f} (xarajatdan keyin)", "",
        "📈 MARKET ANALYSIS:",
        row("4H", "h4_trend"), row("1H", "h1_trend"), row("15M", "m15_ema"), row("RSI (1H)", "rsi"),
        row("MACD (1H)", "macd"), row("Volume", "volume"), row("Market Structure", "structure"),
        row("S/R", "sr"), row("Breakout", "breakout"), "",
        "🎯 SIGNAL REASONS:", *reasons, "",
        f"⚠️ INVALIDATION:\n{sig['invalidation']['text']} ({_p(sig['invalidation']['level'])}). Muddat: "
        f"{sig['valid_until'].astimezone(tz):%d.%m %H:%M} gacha.", "",
        f"📉 Tarixiy sinov: {hist_note}", "",
        f"🕒 Time: UTC+5 (ma'lumot: {local:%Y-%m-%d %H:%M})",
        f"📡 Source: real market data ({source}); signal ID: {sig['signal_id']}",
        "🧪 Faqat PAPER trading: HA tugmasi real order OCHMAYDI. Moliyaviy maslahat emas, foyda kafolatlanmaydi.",
    ]
    return "\n".join(lines)


@dataclass
class Candidate:
    symbol: str
    timeframe: str
    direction: str
    strategy_id: str
    strategy_version: int
    entry_type: str
    entry: float
    sl: float
    tp: float
    rr: float
    rr_net: float
    invalidation: dict
    valid_until: datetime
    data_ts: datetime
    source: str
    spread: float
    commission: float
    score: Score
    evidence: dict
    structure: str


class SignalService:
    """Skaner + signal hayot sikli. Telegram bilan faqat send/edit funksiyalari orqali gaplashadi (test uchun soxta)."""

    def __init__(self, svc, send: SendFn, edit: EditFn, owner_user_id: int, journal=None):
        self.svc = svc
        self.db = svc.db
        self.send = send
        self.edit = edit
        self.owner_user_id = owner_user_id
        self.journal = journal
        self.lab_file = svc.memory.root / "lab" / "baseline.json"

    # ------------------------------------------------------------------ sozlama
    @property
    def cfg(self) -> dict:
        return self.svc.settings.get("signals") or {}

    @property
    def mode(self) -> str:
        return str(self.cfg.get("mode", "off"))

    def _event(self, kind: str, text: str, **fields) -> None:
        if self.journal is not None:
            self.journal.event(kind, text, **fields)

    def log_event(self, signal_id: str, kind: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES(?,?,?,?)",
                        (signal_id, now_iso(self.svc.clock()), kind, detail[:500]))

    # ------------------------------------------------------------------ skaner
    def scan_symbol(self, symbol: str) -> Candidate | None:
        """Bitta instrument: 1H da faol strategiyalar -> ball. Ma'lumot muammosi DataUnavailable."""
        s = self.svc
        b1 = s.market.history(symbol, "1h", 320, need=250)
        b4 = s.market.history(symbol, "4h", 320, need=250)
        b15 = s.market.history(symbol, "15m", 320, need=120)
        for b in (b1, b4, b15):
            if b.warnings:
                raise DataUnavailable(f"{symbol} {b.timeframe}: {'; '.join(b.warnings)}")
        f1, f4, f15 = Features.build(b1.candles), Features.build(b4.candles), Features.build(b15.candles)
        i = len(f1) - 1
        try:
            regime = classify_regime(f1, i)
        except ValueError as exc:
            raise DataUnavailable(f"{symbol}: {exc}") from None
        market = s.settings.instrument(symbol).get("market", "crypto")
        vkind = "volume" if market == "crypto" else "tick"
        spread = s.settings.spread_price(symbol, f1.close[i])
        comm = s.settings.commission_rate(symbol)
        data_end = b1.last_close_time
        min_rr = float(s.settings.get("min_rr", 1.5))
        best: Candidate | None = None
        for spec in candidates(regime, s.registry.active()):
            res = spec.evaluate(f1, i, regime)
            if isinstance(res, NoSetup):
                continue
            risk = abs(res.entry - res.sl)
            if risk <= 0:
                continue
            rr_net = res.rr - (comm * 2 * res.entry + spread) / risk
            sc = evaluate(res.direction == "LONG", f15, f1, f4, entry=res.entry, sl=res.sl, tp=res.tp, rr_net=rr_net,
                          min_rr=min_rr, volume_kind=vkind)
            cand = Candidate(symbol, "1h", res.direction, spec.strategy_id, spec.version, res.entry_type,
                             round_price(res.entry, f1.close[i]), round_price(res.sl, f1.close[i]),
                             round_price(res.tp, f1.close[i]), res.rr, round(rr_net, 2), res.invalidation,
                             data_end + timedelta(seconds=TF_SECONDS["1h"] * res.valid_bars), data_end, b1.source,
                             spread, comm, sc, res.evidence, res.structure)
            if best is None or sc.score > best.score.score:
                best = cand
        return best

    def _duplicate(self, c: Candidate, now: datetime) -> str | None:
        """Faol (hal qilinmagan yoki tasdiqlangan) yoki cooldown ichidagi signal bor-yo'qligi. TEST signallar sanalmaydi."""
        active = self.db.one(f"SELECT signal_id FROM signals WHERE symbol=? AND direction=? AND status IN "
                             f"({','.join('?' * len(ACTIVE_STATES))}) AND signal_id NOT LIKE 'TST-%' AND (valid_until IS NULL OR valid_until>?)",
                             (c.symbol, c.direction, *ACTIVE_STATES, now_iso(now)))
        if active:
            return f"{active['signal_id']} hali faol"
        cd = timedelta(hours=float(self.cfg.get("cooldown_h", 4)))
        recent = self.db.one("SELECT signal_id FROM signals WHERE symbol=? AND direction=? AND tier IN ('STRONG','CONFIRM') "
                             "AND signal_id NOT LIKE 'TST-%' AND created_at>? AND status!='DRY'", (c.symbol, c.direction, now_iso(now - cd)))
        if recent:
            return f"{recent['signal_id']} cooldown ichida ({cd.total_seconds() / 3600:g} soat)"
        return None

    def _new_id(self, now: datetime, prefix: str = "SIG") -> str:
        day = now.astimezone(self.svc.settings.tz).strftime("%Y%m%d")
        return f"{prefix}-{day}-{self.db.next_counter(prefix.lower() + ':' + day):04d}"

    def store(self, c: Candidate, now: datetime, status: str, prefix: str = "SIG") -> dict:
        sid = self._new_id(now, prefix)
        sig = {"signal_id": sid, "symbol": c.symbol, "timeframe": c.timeframe, "direction": c.direction,
               "entry_type": c.entry_type, "entry": c.entry, "sl": c.sl, "tp": c.tp, "rr_net": c.rr_net,
               "invalidation": c.invalidation, "valid_until": c.valid_until}
        analysis = {"items": [{"key": i.key, "label": i.label, "ok": i.ok, "detail": i.detail} for i in c.score.items],
                    "blocked": c.score.blocked, "missing": c.score.missing, "evidence": c.evidence,
                    "structure": c.structure, "spread": c.spread, "commission": c.commission}
        self.db.execute(
            "INSERT INTO signals(signal_id, created_at, symbol, timeframe, direction, strategy_id, strategy_version, "
            "entry_type, entry, sl, tp, rr, rr_net, score, tier, status, valid_until, data_ts, data_source, analysis, "
            "invalidation) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, now_iso(now), c.symbol, c.timeframe, c.direction, c.strategy_id, c.strategy_version, c.entry_type,
             c.entry, c.sl, c.tp, c.rr, c.rr_net, c.score.score, c.score.tier, status, now_iso(c.valid_until),
             now_iso(c.data_ts), c.source, json.dumps(analysis, ensure_ascii=False), json.dumps(c.invalidation)))
        self.log_event(sid, "created", f"{c.strategy_id} {c.direction} score {c.score.score} tier {c.score.tier} -> {status}")
        return sig

    async def scan_once(self) -> dict:
        """Hamma instrumentlar. Natija: hisoblagich lug'ati (jurnal va testlar uchun)."""
        import asyncio
        mode = self.mode
        out = {"scanned": 0, "no_setup": 0, "data_unavailable": 0, "watch": 0, "dropped": 0, "blocked": 0,
               "duplicate": 0, "sent": 0, "dry": 0, "errors": []}
        if mode == "off":
            return out
        now = self.svc.clock()
        for symbol in self.cfg.get("universe", []):
            provider = self.svc.settings.instrument(symbol).get("provider", "binance")
            if provider not in self.svc.market.providers:
                out["data_unavailable"] += 1
                out["errors"].append(f"{symbol}: '{provider}' sozlanmagan")
                continue
            try:
                cand = await asyncio.to_thread(self.scan_symbol, symbol)
            except DataUnavailable as exc:
                out["data_unavailable"] += 1
                out["errors"].append(f"{symbol}: {str(exc)[:120]}")
                continue
            except Exception as exc:  # noqa: BLE001 — bitta instrument boshqalarni to'xtatmasin
                log.exception("signal skaneri %s", symbol)
                out["errors"].append(f"{symbol}: {type(exc).__name__}: {exc}"[:150])
                continue
            out["scanned"] += 1
            if cand is None:
                out["no_setup"] += 1
                continue
            tier = cand.score.tier
            if tier == "BLOCKED":
                out["blocked"] += 1
                continue
            if tier == "DROP":
                out["dropped"] += 1
                continue
            if tier == "WATCH":
                out["watch"] += 1
                if not self._duplicate_watch(cand, now):
                    self.store(cand, now, "WATCH")
                continue
            dup = self._duplicate(cand, now)
            if dup:
                out["duplicate"] += 1
                self.db.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES(?,?,?,?)",
                                ("-", now_iso(now), "duplicate", f"{symbol} {cand.direction}: {dup}"))
                continue
            if mode == "dry":
                self.store(cand, now, "DRY")
                out["dry"] += 1
                continue
            sig = self.store(cand, now, "NEW")
            if await self.publish(sig["signal_id"], cand):
                out["sent"] += 1
        return out

    def _duplicate_watch(self, c: Candidate, now: datetime) -> bool:
        """Kuzatuv ro'yxatiga bir xil (instrument, yo'nalish) 4 soatda bir martadan ko'p yozilmaydi."""
        return bool(self.db.one("SELECT 1 FROM signals WHERE symbol=? AND direction=? AND status='WATCH' AND created_at>?",
                                (c.symbol, c.direction, now_iso(now - timedelta(hours=4)))))

    # ------------------------------------------------------------------ yuborish
    async def send_test(self, symbol: str | None = None) -> str:
        """Tugmalarni sinash: HAQIQIY bozor ma'lumotidan chiqqan eng yaxshi setup 'TST-' ID bilan, aniq TEST belgisi bilan
        guruhga yuboriladi (statistikaga kirmaydi). Setup yo'q bo'lsa — hech narsa to'qilmaydi."""
        import asyncio
        if self.svc.settings.group_chat_id is None:
            return "Guruh ulanmagan (/trading_guruh)"
        best: Candidate | None = None
        for sym in ([symbol] if symbol else list(self.cfg.get("universe", []))):
            if self.svc.settings.instrument(sym).get("provider", "binance") not in self.svc.market.providers:
                continue
            try:
                c = await asyncio.to_thread(self.scan_symbol, sym)
            except DataUnavailable:
                continue
            if c is not None and c.score.tier != "BLOCKED" and (best is None or c.score.score > best.score.score):
                best = c
        if best is None:
            return "Hozir hech bir instrumentda haqiqiy setup yo'q — test signal yaratilmadi (narx to'qilmaydi)"
        sig = self.store(best, self.svc.clock(), "NEW", prefix="TST")
        header = (f"🧪 TEST — bu real signal EMAS, tugmalarni sinash. Haqiqiy bozor ma'lumotidan chiqqan setup "
                  f"({best.score.score}/10, daraja {best.score.tier}). HA/YO'Q faqat paper yozuv; statistikaga kirmaydi.")
        ok = await self.publish(sig["signal_id"], best, header=header)
        return (f"Test signal yuborildi: {sig['signal_id']} ({best.symbol} {best.direction}, {best.score.score}/10)"
                if ok else f"Test signal yuborilmadi ({sig['signal_id']}); logni tekshiring")

    async def publish(self, signal_id: str, cand: Candidate | None = None, header: str | None = None) -> bool:
        from ..telegram_api import TelegramError, TelegramNetworkError
        row = self.db.one("SELECT * FROM signals WHERE signal_id=?", (signal_id,))
        chat = self.svc.settings.group_chat_id
        if row is None or chat is None:
            return False
        if self.db.execute("UPDATE signals SET status='SENDING', chat_id=? WHERE signal_id=? AND status='NEW'",
                           (chat, signal_id)).rowcount != 1:
            return False  # boshqa oqim allaqachon yuborayapti/yubordi
        a = json.loads(row["analysis"])
        score = _score_from_row(row, a)
        sig = {**row, "invalidation": json.loads(row["invalidation"]),
               "valid_until": datetime.fromisoformat(row["valid_until"])}
        text = format_signal(sig, score, self.svc.settings.tz,
                             history_note(self.lab_file, row["symbol"], row["strategy_id"], row["timeframe"]),
                             row["data_source"], datetime.fromisoformat(row["data_ts"]))
        if header:
            text = header + "\n\n" + text
        try:
            msg = await self.send(chat, text, keyboard(signal_id, row["direction"]), None)
        except TelegramNetworkError as exc:  # ketgan-ketmagani noma'lum — qayta yuborilmaydi (dublikat xavfi)
            self.db.execute("UPDATE signals SET status='UNKNOWN', text=? WHERE signal_id=?", (text, signal_id))
            self.log_event(signal_id, "send_unknown", str(exc)[:200])
            log.error("signal %s yuborilishi noma'lum: %s", signal_id, exc)
            return False
        except TelegramError as exc:
            self.db.execute("UPDATE signals SET status='FAILED', text=? WHERE signal_id=?", (text, signal_id))
            self.log_event(signal_id, "send_failed", str(exc)[:200])
            log.error("signal %s yuborilmadi: %s", signal_id, exc)
            return False
        self.db.execute("UPDATE signals SET status='SENT', message_id=?, text=? WHERE signal_id=?",
                        ((msg or {}).get("message_id"), text, signal_id))
        self.log_event(signal_id, "sent", f"chat {chat}")
        self._event("signal", f"Signal {signal_id} yuborildi: {row['symbol']} {row['direction']} {row['score']}/10",
                    signal=signal_id)
        return True

    # ------------------------------------------------------------------ tugma
    async def handle_callback(self, data: str, user_id: int | None, chat_id: int | None) -> str:
        """Telegram callback. Qaytadi: answerCallbackQuery matni. Faqat egasi; holat o'zgarishi atomik."""
        import asyncio
        parsed = parse_callback(data)
        if parsed is None:
            return "Noto'g'ri tugma"
        action, signal_id = parsed
        row = self.db.one("SELECT * FROM signals WHERE signal_id=?", (signal_id,))
        if user_id != self.owner_user_id:
            self.log_event(signal_id, "denied", f"user {user_id} egasi emas")
            self._event("unauthorized", "Signal tugmasini egasi bosmadi", user_id=user_id, chat_id=chat_id, signal=signal_id)
            return "Faqat egasi tasdiqlay oladi"
        if row is None:
            return "Signal topilmadi"
        if chat_id != row["chat_id"] or chat_id != self.svc.settings.group_chat_id:
            self.log_event(signal_id, "denied", f"chat {chat_id} signal guruhi emas")
            return "Bu guruhda tasdiqlab bo'lmaydi"
        if row["status"] != "SENT":
            return {"CONFIRMED": "Allaqachon tasdiqlangan", "REJECTED": "Allaqachon rad etilgan",
                    "EXPIRED": "Muddati o'tgan", "INVALIDATED": "Signal bekor bo'lgan",
                    "CONFIRMING": "Tasdiqlanmoqda..."}.get(row["status"], f"Hozirgi holat: {row['status']}")
        now = self.svc.clock()
        if now > datetime.fromisoformat(row["valid_until"]):
            if self._claim(signal_id, "EXPIRED", "muddati o'tgan"):
                await self._finalize_message(row, "EXPIRED", "amal muddati tugagan")
            return "Muddati o'tgan — tasdiqlanmadi"
        if action == "reject":
            if not self._claim(signal_id, "REJECTED", "egasi rad etdi", by=user_id):
                return "Allaqachon hal qilingan"
            await self._finalize_message(row, "REJECTED", "egasi YO'Q tugmasini bosdi")
            return "Rad etildi — pozitsiya ochilmadi"
        # confirm: avval holatni band qilamiz (qayta bosishdan himoya), keyin narx va shartlarni qayta tekshiramiz
        if self.db.execute("UPDATE signals SET status='CONFIRMING', decided_at=?, decided_by=? WHERE signal_id=? AND "
                           "status='SENT'", (now_iso(now), user_id, signal_id)).rowcount != 1:
            return "Allaqachon hal qilingan"
        try:
            ok, reason = await asyncio.to_thread(self.revalidate, row, now)
        except Exception as exc:  # noqa: BLE001
            ok, reason = False, f"qayta tekshiruv xatosi: {type(exc).__name__}"
            log.exception("signal %s qayta tekshiruvi", signal_id)
        if not ok:
            self.db.execute("UPDATE signals SET status='INVALIDATED', decision_note=? WHERE signal_id=?",
                            (reason[:300], signal_id))
            self.log_event(signal_id, "confirm_refused", reason)
            await self._finalize_message(row, "INVALIDATED", reason)
            return f"Tasdiqlanmadi: {reason}"[:190]
        self.open_paper(row, now)
        self.db.execute("UPDATE signals SET status='CONFIRMED', decision_note='paper pozitsiya ochildi' WHERE signal_id=?",
                        (signal_id,))
        self.log_event(signal_id, "confirmed", f"user {user_id}")
        await self._finalize_message(row, "CONFIRMED", reason)
        return "Tasdiqlandi — PAPER pozitsiya ochildi"

    def _claim(self, signal_id: str, status: str, note: str, by: int | None = None) -> bool:
        ok = self.db.execute("UPDATE signals SET status=?, decision_note=?, decided_at=?, decided_by=? WHERE signal_id=? "
                             "AND status='SENT'", (status, note, now_iso(self.svc.clock()), by, signal_id)).rowcount == 1
        if ok:
            self.log_event(signal_id, status.lower(), note)
        return ok

    async def _finalize_message(self, row: dict, status: str, note: str) -> None:
        """Asl xabarni yangilash (tugmalar olib tashlanadi — edit_message_text reply_markup'ni tozalaydi)."""
        if not row.get("message_id") or not row.get("chat_id"):
            return
        text = (row.get("text") or row["signal_id"]) + f"\n\n{STATUS_LABEL[status]}" + (f"\n{note}" if note else "")
        try:
            await self.edit(row["chat_id"], row["message_id"], text)
        except Exception as exc:  # noqa: BLE001 — xabarni yangilab bo'lmasa ham holat bazada to'g'ri
            log.error("signal %s xabari yangilanmadi: %s", row["signal_id"], exc)
            self.log_event(row["signal_id"], "edit_failed", str(exc)[:200])

    # ------------------------------------------------------------------ qayta tekshiruv va paper pozitsiya
    def revalidate(self, row: dict, now: datetime) -> tuple[bool, str]:
        """Tasdiq paytida: bozor ma'lumoti hali yaroqli va signal eskirmaganmi. (ok, sabab)"""
        s = self.svc
        b15 = s.market.history(row["symbol"], "15m", 60, need=20)
        b1 = s.market.history(row["symbol"], "1h", 60, need=30)
        if b15.warnings:
            return False, "ma'lumot sifati: " + "; ".join(b15.warnings)
        last = b15.candles[-1]
        price = last.close
        f1 = Features.build(b1.candles)
        atr = f1.atr14[-1]
        long = row["direction"] == "LONG"
        inv = json.loads(row["invalidation"])
        if (price <= row["sl"]) if long else (price >= row["sl"]):
            return False, f"narx ({_p(price)}) allaqachon SL ({_p(row['sl'])}) dan o'tgan"
        if (price >= row["tp"]) if long else (price <= row["tp"]):
            return False, f"narx ({_p(price)}) allaqachon TP ({_p(row['tp'])}) ga yetgan"
        lvl = inv.get("level")
        if lvl is not None and ((last.close < lvl) if inv.get("type") == "close_below" else (last.close > lvl)):
            return False, f"bekor qilish sharti bajarilgan ({inv.get('text')})"
        tol = float(self.cfg.get("tolerance_atr", 1.0))
        if atr == atr and abs(price - row["entry"]) > tol * atr:
            return False, (f"narx ancha o'zgargan: hozir {_p(price)}, signal kirishi {_p(row['entry'])} "
                           f"(chegara {tol:g} ATR = {_p(tol * atr)})")
        return True, f"narx {_p(price)} ({last.end:%H:%M} UTC) — signal hali yaroqli"

    def open_paper(self, row: dict, now: datetime) -> None:
        """Simulyatsion pozitsiya: signaldagi kirish turi va narxi bilan (stop/limit/next_open), tasdiq vaqtidan keyingi
        15M shamlardan boshlab kuzatiladi. Eski narx bo'yicha 'to'ldirish' YO'Q."""
        start = datetime.fromtimestamp((int(now.timestamp()) // FIFTEEN + 1) * FIFTEEN, tz=timezone.utc)
        s = self.svc
        self.db.execute(
            "INSERT OR IGNORE INTO paper_positions(signal_id, symbol, direction, entry_type, entry_signal, sl, tp, "
            "confirmed_at, data_end, valid_until, status, spread, commission, max_hold, invalidation, notified) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["signal_id"], row["symbol"], row["direction"], row["entry_type"], row["entry"], row["sl"], row["tp"],
             now_iso(now), now_iso(start), row["valid_until"], "PENDING", json.loads(row["analysis"]).get("spread", 0.0),
             json.loads(row["analysis"]).get("commission", 0.0), int(s.settings.get("max_hold_bars", 48)),
             row["invalidation"], "PENDING"))
        self.log_event(row["signal_id"], "paper_opened", f"{row['entry_type']} {row['entry']} SL {row['sl']} TP {row['tp']}")

    # ------------------------------------------------------------------ kuzatuv (paper natijasi, muddat, trend)
    async def track(self) -> int:
        """Ochiq paper pozitsiyalar va yuborilgan, lekin hal qilinmagan signallar. Qaytadi: yuborilgan yangilanishlar soni."""
        import asyncio
        sent = 0
        now = self.svc.clock()
        # 1. hal qilinmagan signallar: muddat / bekor bo'lish / 4H trend o'zgarishi
        for row in self.db.query("SELECT * FROM signals WHERE status='SENT'"):
            if now > datetime.fromisoformat(row["valid_until"]):
                if self._claim(row["signal_id"], "EXPIRED", "muddati o'tdi"):
                    await self._finalize_message(row, "EXPIRED", "amal muddati tugadi, tasdiqlanmadi")
                    await self._reply(row, f"⌛ {row['signal_id']} ({row['symbol']} {row['direction']}) bekor bo'ldi: "
                                           "amal muddati tugadi.")
                    sent += 1
                continue
            try:
                state = await asyncio.to_thread(self._market_state, row)
            except DataUnavailable:
                continue
            if state["invalidated"]:
                if self._claim(row["signal_id"], "INVALIDATED", state["invalidated"]):
                    await self._finalize_message(row, "INVALIDATED", state["invalidated"])
                    await self._reply(row, f"🚫 {row['signal_id']} ({row['symbol']} {row['direction']}) bekor bo'ldi: "
                                           f"{state['invalidated']}")
                    sent += 1
        # 2. paper pozitsiyalar
        for pos in self.db.query("SELECT * FROM paper_positions WHERE status IN ('PENDING','ACTIVE_SIMULATION')"):
            try:
                changed = await asyncio.to_thread(self._advance, pos)
            except DataUnavailable as exc:
                log.warning("paper %s: %s", pos["signal_id"], exc)
                continue
            if changed:
                sent += await self._notify_position(pos["signal_id"])
        # 3. trend o'zgarishi (tasdiqlangan, hali ochiq pozitsiya): bir marta ogohlantirish
        for pos in self.db.query("SELECT p.*, s.analysis, s.message_id, s.chat_id FROM paper_positions p JOIN signals s ON "
                                 "s.signal_id=p.signal_id WHERE p.status IN ('PENDING','ACTIVE_SIMULATION') AND "
                                 "p.trend_warned=0"):
            try:
                st = await asyncio.to_thread(self._trend_now, pos["symbol"])
            except DataUnavailable:
                continue
            want = "TREND_UP" if pos["direction"] == "LONG" else "TREND_DOWN"
            opposite = "TREND_DOWN" if pos["direction"] == "LONG" else "TREND_UP"
            if st == opposite and self.db.execute("UPDATE paper_positions SET trend_warned=1 WHERE signal_id=? AND "
                                                  "trend_warned=0", (pos["signal_id"],)).rowcount == 1:
                self.log_event(pos["signal_id"], "trend_changed", f"4H endi {st} (kutilgan {want})")
                await self._reply(pos, f"⚠️ {pos['signal_id']} ({pos['symbol']} {pos['direction']}): 4H trend teskariga "
                                       f"o'zgardi ({st}). Paper pozitsiya ochiq — risk oshdi.")
                sent += 1
        return sent

    def _trend_now(self, symbol: str) -> str | None:
        b4 = self.svc.market.history(symbol, "4h", 320, need=250)
        return trend_of(Features.build(b4.candles))

    def _market_state(self, row: dict) -> dict:
        """SENT signal uchun: bekor qilish sharti yoki SL/TP ga yetib bo'lgan narx (kirishsiz)."""
        b15 = self.svc.market.history(row["symbol"], "15m", 60, need=20)
        last = b15.candles[-1]
        long = row["direction"] == "LONG"
        inv = json.loads(row["invalidation"])
        lvl = inv.get("level")
        out = {"invalidated": None}
        if lvl is not None and ((last.close < lvl) if inv.get("type") == "close_below" else (last.close > lvl)):
            out["invalidated"] = f"bekor qilish sharti bajarildi: {inv.get('text')} ({_p(lvl)}), hozirgi yopilish {_p(last.close)}"
        elif (last.close <= row["sl"]) if long else (last.close >= row["sl"]):
            out["invalidated"] = f"narx SL ({_p(row['sl'])}) dan o'tib ketdi (hozir {_p(last.close)})"
        elif (last.close >= row["tp"]) if long else (last.close <= row["tp"]):
            out["invalidated"] = f"narx TP ({_p(row['tp'])}) ga kirishsiz yetib bo'ldi (hozir {_p(last.close)})"
        return out

    def _advance(self, pos: dict) -> bool:
        s = self.svc
        start = datetime.fromisoformat(pos["data_end"])
        sc = Scenario(pos["signal_id"], pos["direction"], pos["entry_type"], pos["entry_signal"], pos["sl"], pos["tp"],
                      json.loads(pos["invalidation"]), start, datetime.fromisoformat(pos["confirmed_at"]),
                      datetime.fromisoformat(pos["valid_until"]), int(pos["max_hold"]), "15m",
                      float(pos["spread"] or 0.0), float(pos["commission"] or 0.0))
        bars = s.market.after(pos["symbol"], "15m", start, limit=1000)
        st = simulate(sc, bars, None, fine=lambda a, b: s.market.fine(pos["symbol"], a, b))
        fields = dict(status=st.status, entry_time=st.entry_time.isoformat() if st.entry_time else None,
                      entry_price=st.entry_price, exit_time=st.exit_time.isoformat() if st.exit_time else None,
                      exit_price=st.exit_price, r_multiple=st.r_multiple, cost_r=st.cost_r,
                      last_bar_ts=st.last_bar_ts.isoformat() if st.last_bar_ts else None, note=st.note)
        if st.status == pos["status"] and fields["entry_price"] == pos["entry_price"]:
            self.db.execute("UPDATE paper_positions SET last_bar_ts=? WHERE signal_id=?",
                            (fields["last_bar_ts"], pos["signal_id"]))
            return False
        sets = ", ".join(f"{k}=?" for k in fields)
        self.db.execute(f"UPDATE paper_positions SET {sets} WHERE signal_id=?", (*fields.values(), pos["signal_id"]))
        self.log_event(pos["signal_id"], "paper_" + st.status.lower(), f"entry {st.entry_price} exit {st.exit_price} "
                                                                     f"R {st.r_multiple}")
        return True

    async def _notify_position(self, signal_id: str) -> int:
        pos = self.db.one("SELECT p.*, s.message_id, s.chat_id FROM paper_positions p JOIN signals s ON "
                          "s.signal_id=p.signal_id WHERE p.signal_id=?", (signal_id,))
        if pos is None or pos["status"] == pos["notified"] or pos["status"] == PENDING:
            return 0
        if self.db.execute("UPDATE paper_positions SET notified=? WHERE signal_id=? AND notified!=?",
                           (pos["status"], signal_id, pos["status"])).rowcount != 1:
            return 0
        r = pos["r_multiple"]
        extra = f" — {r:+.2f}R (xarajat bilan)" if r is not None and pos["status"] in ("TP_HIT", "SL_HIT", "EXPIRED") else ""
        await self._reply(pos, f"📊 {signal_id} ({pos['symbol']} {pos['direction']}): "
                               f"{OUTCOME_TEXT.get(pos['status'], pos['status'])}{extra}.\nPaper trading natijasi; real order yo'q.")
        return 1

    async def _reply(self, row: dict, text: str) -> None:
        chat, mid = row.get("chat_id"), row.get("message_id")
        if not chat:
            return
        try:
            await self.send(chat, text, None, mid)
        except Exception as exc:  # noqa: BLE001
            log.error("signal xabari yuborilmadi: %s", exc)

    # ------------------------------------------------------------------ statistika
    def stats(self, since: str | None = None) -> dict:
        q = " AND signal_id NOT LIKE 'TST-%'" + (" AND created_at>=?" if since else "")
        a = (since,) if since else ()
        by_status = {r["status"]: r["n"] for r in self.db.query(
            f"SELECT status, COUNT(*) n FROM signals WHERE 1=1{q} GROUP BY status", a)}
        pos = self.db.query("SELECT status, COUNT(*) n, AVG(r_multiple) avg_r, SUM(r_multiple) sum_r FROM paper_positions "
                            "WHERE signal_id NOT LIKE 'TST-%' GROUP BY status")
        done = [p for p in pos if p["status"] in ("TP_HIT", "SL_HIT", "EXPIRED")]
        n = sum(p["n"] for p in done)
        tot = sum((p["sum_r"] or 0.0) for p in done)
        return {"signals": by_status, "paper": {p["status"]: p["n"] for p in pos}, "closed": n,
                "total_r": round(tot, 2), "avg_r": round(tot / n, 3) if n else None}


def _score_from_row(row: dict, a: dict) -> Score:
    from .signal_score import Item
    items = [Item(i["key"], i["label"], i["ok"], i["detail"]) for i in a["items"]]
    return Score(row["score"], items, row["tier"], a.get("blocked"), a.get("missing", []))


__all__ = ["SignalService", "Candidate", "callback_data", "parse_callback", "keyboard", "format_signal", "history_note"]
