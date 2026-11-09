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
import time
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from . import lifecycle as lc
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
    "REFUSED": "⛔ IJRO RAD ETILDI — MT5 zdelka ochilmadi",
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


def mt5_name(symbol: str) -> str:
    """Signal simvoli -> MT5 qidiruv nomi (broker qo'shimchasi connector.resolve da topiladi): BTCUSDT -> BTCUSD, XAU/USD -> XAUUSD."""
    s = symbol.replace("/", "").replace("-", "").upper()
    return s[:-1] if s.endswith("USDT") else s


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
def format_signal(sig: dict, score: Score, tz, hist_note: str, source: str, data_ts: datetime, demo: bool = False) -> str:
    long = sig["direction"] == "LONG"
    side = "BUY" if long else "SELL"
    title = ("STRONG SIGNAL" if score.tier == "STRONG" else "ZONA SIGNALI (zona asosida; strategiya testidan o'tmagan)"
             if score.tier == "ZONE" else "SIGNAL (6-7/10, qo'shimcha tasdiq bor)")
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
        (f"⭐ Zona kuchi: {score.score}/{MAX_SCORE} (hisoblangan o'lcham — g'alaba ehtimoli emas)" if score.tier == "ZONE" else
         f"⭐ Score: {score.score}/{MAX_SCORE} (bajarilgan tekshiruv mezonlari soni — g'alaba ehtimoli emas)"), "",
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
        ("🤖 AUTO: tasdiq SHART EMAS — bahs va himoyalardan o'tsa agent MT5 DEMO'da o'zi ochadi (REAL hisobda hech qachon); natija shu xabarda "
         "yangilanadi. Moliyaviy maslahat emas, foyda kafolatlanmaydi." if score.tier == "ZONE" else
         "🧪 HA tugmasi: paper pozitsiya + MT5 DEMO hisobda zdelka (REAL hisobda hech qachon). Moliyaviy maslahat emas, foyda "
         "kafolatlanmaydi." if demo else
         "🧪 Faqat PAPER trading: HA tugmasi real order OCHMAYDI. Moliyaviy maslahat emas, foyda kafolatlanmaydi."),
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

    def __init__(self, svc, send: SendFn, edit: EditFn, owner_user_id: int, journal=None, trader=None, history=None):
        self.desk = None  # agent.staff.desk.Desk (Claude xodimlari); None -> bahssiz eski xulq
        self.notify_private = None  # async (text) -> egasining shaxsiy chati (app.py ulaydi)
        self.trader = trader  # DemoTrader (faqat DEMO hisob) — settings["signals"]["demo_orders"] yoqilgandagina ishlatiladi
        self.history = history  # MT5History (kunlik zarar chegarasi uchun)
        self.svc = svc
        self.db = svc.db
        self.send = send
        self.edit = edit
        self.owner_user_id = owner_user_id
        self.journal = journal
        self.lab_file = svc.memory.root / "lab" / "baseline.json"
        self._trace: dict[str, list[tuple]] = {}  # skaner izi: instrument -> [(bosqich, strategiya, natija, sabab)] (scan_log'ga yoziladi)

    # ------------------------------------------------------------------ sozlama
    @property
    def cfg(self) -> dict:
        return self.svc.settings.get("signals") or {}

    @property
    def mode(self) -> str:
        return str(self.cfg.get("mode", "off"))

    @property
    def demo_enabled(self) -> bool:
        return bool(self.cfg.get("demo_orders")) and self.trader is not None

    @property
    def trade_mode(self) -> str:
        return str(self.cfg.get("trade_mode", "confirm"))

    def _auto_tiers(self) -> set[str]:
        return {"STRONG"} if str(self.cfg.get("auto_min_tier", "CONFIRM")) == "STRONG" else {"STRONG", "CONFIRM"}

    def target_chat(self) -> int | None:
        """Signal yuboriladigan chat: settings["signals"]["target"] = private (egasining shaxsiy chati) | group."""
        st = self.svc.settings
        return st.private_chat_id if self.cfg.get("target") == "private" else st.group_chat_id

    def _allowed_chats(self) -> set[int]:
        st = self.svc.settings
        return {c for c in (st.group_chat_id, st.private_chat_id) if c}

    def _event(self, kind: str, text: str, **fields) -> None:
        if self.journal is not None:
            self.journal.event(kind, text, **fields)

    def log_event(self, signal_id: str, kind: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES(?,?,?,?)",
                        (signal_id, now_iso(self.svc.clock()), kind, detail[:500]))

    # ------------------------------------------------------------------ V32: ijro holati va ijro jurnali
    def _set_exec(self, signal_id: str, status: str, origin: str | None = None) -> None:
        """Ijro hayot sikli holati (signals.exec_status). Eski `status` ustuniga tegmaydi."""
        if origin:
            self.db.execute("UPDATE signals SET exec_status=?, origin=? WHERE signal_id=?", (status, origin, signal_id))
        else:
            self.db.execute("UPDATE signals SET exec_status=? WHERE signal_id=?", (status, signal_id))

    def _debate_text(self, signal_id: str, origin: str | None) -> str:
        if origin == lc.ORIGIN_FORCED:
            return "skipped (forced_test)"
        d = self.db.one("SELECT approve, votes FROM staff_decisions WHERE kind='signal' AND ref=? ORDER BY id DESC LIMIT 1", (signal_id,))
        if d is None:
            return "not_run"
        try:
            votes = json.loads(d["votes"] or "{}")
        except ValueError:
            votes = {}
        yes = sum(1 for v in votes.values() if v == "approve")
        return f"{'approve' if d['approve'] else 'reject'} {yes}/{len(votes)}"

    def audit(self, signal_id: str, decision: str, stage: str, reason: str = "", *, risk: str = "not_run", mt5: str = lc.MT5_NA,
              retcode: int | None = None, origin: str | None = None, detail: dict | None = None) -> None:
        """Har ijro urinishi uchun tuzilgan yozuv (execution_audit): signal, instrument, UTC vaqt, bahs, risk, qaror, to'xtagan bosqich,
        ANIQ sabab, MT5 so'rovi holati/kodi, kelib chiqishi. Rad etilgan zdelka hech qachon MT5 order_send deb yozilmaydi (mt5=NOT_SENT).
        Jurnal xatosi savdoni to'xtatmaydi."""
        try:
            row = self.db.one("SELECT symbol, origin FROM signals WHERE signal_id=?", (signal_id,)) or {}
            origin = origin or row.get("origin")
            self.db.execute(
                "INSERT INTO execution_audit(ts, signal_id, symbol, origin, debate_result, risk_result, decision, stage, reason, "
                "mt5_request, mt5_retcode, detail) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (now_iso(self.svc.clock()), signal_id, row.get("symbol"), origin, self._debate_text(signal_id, origin), risk, decision,
                 stage, (reason or "")[:500], mt5, retcode, json.dumps(detail, ensure_ascii=False) if detail else None))
        except Exception:  # noqa: BLE001
            log.exception("execution_audit yozilmadi (%s)", signal_id)

    # ------------------------------------------------------------------ skaner
    def _t(self, symbol: str, stage: str, outcome: str, reason: str, strategy: str | None = None) -> None:
        """Skaner izi: har bosqichda ANIQ sabab (kod shartiga mos). Hech qachon skanerni buzmaydi."""
        self._trace.setdefault(symbol, []).append((stage, strategy, outcome, str(reason)[:300]))

    def _flush_trace(self, out: dict, ms: float | None = None) -> None:
        """Izni scan_log jadvaliga yozadi (14 kun saqlanadi) + skan xulosasi (voronka hisoblagichlari)."""
        try:
            now = now_iso(self.svc.clock())
            for sym, items in self._trace.items():
                for stage, strat, oc, reason in items:
                    self.db.execute("INSERT INTO scan_log(ts, symbol, stage, strategy, outcome, reason) VALUES(?,?,?,?,?,?)", (now, sym, stage, strat, oc, reason))
            summary = {k: v for k, v in out.items() if k != "errors"}
            summary["n_errors"] = len(out.get("errors", []))
            if ms is not None:
                summary["ms"] = round(ms)
            self.db.execute("INSERT INTO scan_log(ts, symbol, stage, strategy, outcome, reason) VALUES(?,?,?,?,?,?)",
                            (now, "*", "summary", None, "ok", json.dumps(summary)))
            self.db.execute("DELETE FROM scan_log WHERE ts < ?", (now_iso(self.svc.clock() - timedelta(days=14)),))
        except Exception:  # noqa: BLE001 — kuzatuv skanerni to'xtatmasin
            log.exception("scan_log yozilmadi")
        finally:
            self._trace = {}

    def scan_symbol(self, symbol: str) -> Candidate | None:
        """Bitta instrument: 1H da faol strategiyalar -> ball. Ma'lumot muammosi DataUnavailable."""
        s = self.svc
        self._trace[symbol] = []
        b1 = s.market.history(symbol, "1h", 320, need=250)
        b4 = s.market.history(symbol, "4h", 320, need=250)
        b15 = s.market.history(symbol, "15m", 320, need=120)
        mkt = s.settings.instrument(symbol).get("market", "crypto")
        for b in (b1, b4, b15):
            # forex/metall/indeks: hafta oxiri va sessiya bo'shliqlari NORMAL (320 ta 1H sham doim kamida bitta dam olish kunini qamraydi) —
            # ularni xato deb rad etish bu instrumentlarni abadiy skanerdan chiqarib tashlardi. Kripto uchun bo'shliq — haqiqiy ma'lumot xatosi.
            warns = [w for w in b.warnings if not (mkt != "crypto" and "tushib qolgan" in w)]
            if warns:
                raise DataUnavailable(f"{symbol} {b.timeframe}: {'; '.join(warns)}")
            if b.warnings and not warns:
                self._t(symbol, "data", "ok", f"{b.timeframe}: sessiya bo'shlig'i e'tiborga olinmadi ({mkt}): {b.warnings[0][:60]}")
        f1, f4, f15 = Features.build(b1.candles), Features.build(b4.candles), Features.build(b15.candles)
        i = len(f1) - 1
        try:
            regime = classify_regime(f1, i)
        except ValueError as exc:
            raise DataUnavailable(f"{symbol}: {exc}") from None
        self._t(symbol, "regime", "ok", f"{regime.trend}/{regime.volatility} ADX {regime.readings.get('adx14')}")
        market = s.settings.instrument(symbol).get("market", "crypto")
        vkind = "volume" if market == "crypto" else "tick"
        spread = s.settings.spread_price(symbol, f1.close[i])
        comm = s.settings.commission_rate(symbol)
        data_end = b1.last_close_time
        min_rr = float(s.settings.get("min_rr", 1.5))
        best: Candidate | None = None
        specs = candidates(regime, s.registry.active())
        if not specs:
            self._t(symbol, "strategy", "reject", f"bu rejim ({regime.trend}) uchun faol strategiya yo'q")
        for spec in specs:
            res = spec.evaluate(f1, i, regime)
            if isinstance(res, NoSetup):
                self._t(symbol, "strategy", "reject", res.reason, spec.strategy_id)
                continue
            risk = abs(res.entry - res.sl)
            if risk <= 0:
                self._t(symbol, "strategy", "reject", "SL masofasi 0", spec.strategy_id)
                continue
            rr_net = res.rr - (comm * 2 * res.entry + spread) / risk
            sc = evaluate(res.direction == "LONG", f15, f1, f4, entry=res.entry, sl=res.sl, tp=res.tp, rr_net=rr_net,
                          min_rr=min_rr, volume_kind=vkind)
            cand = Candidate(symbol, "1h", res.direction, spec.strategy_id, spec.version, res.entry_type,
                             round_price(res.entry, f1.close[i]), round_price(res.sl, f1.close[i]),
                             round_price(res.tp, f1.close[i]), res.rr, round(rr_net, 2), res.invalidation,
                             data_end + timedelta(seconds=TF_SECONDS["1h"] * res.valid_bars), data_end, b1.source,
                             spread, comm, sc, res.evidence, res.structure)
            fails = [it.label for it in sc.items if it.ok is False]
            self._t(symbol, "score", "ok" if sc.tier in ("STRONG", "CONFIRM") else "reject",
                    f"{res.direction} {sc.score}/10 daraja={sc.tier}" + (f" BLOK: {sc.blocked}" if sc.blocked else "") +
                    (f"; bajarilmagan mezonlar: {', '.join(fails[:6])}" if fails else ""), spec.strategy_id)
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
        self._set_exec(sid, lc.WATCH if status == "WATCH" else lc.GENERATED, lc.ORIGIN_TEST if prefix == "TST" else None)
        return sig

    async def scan_once(self) -> dict:
        """Hamma instrumentlar. Natija: hisoblagich lug'ati (jurnal va testlar uchun)."""
        import asyncio
        mode = self.mode
        t0 = time.monotonic()
        out = {"scanned": 0, "no_setup": 0, "data_unavailable": 0, "watch": 0, "dropped": 0, "blocked": 0,
               "duplicate": 0, "sent": 0, "dry": 0, "auto": 0, "errors": []}
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
                self._t(symbol, "data", "reject", str(exc)[:200])
                continue
            except Exception as exc:  # noqa: BLE001 — bitta instrument boshqalarni to'xtatmasin
                log.exception("signal skaneri %s", symbol)
                out["errors"].append(f"{symbol}: {type(exc).__name__}: {exc}"[:150])
                self._t(symbol, "error", "reject", f"{type(exc).__name__}: {exc}"[:200])
                continue
            out["scanned"] += 1
            if cand is None:
                out["no_setup"] += 1
                self._t(symbol, "decision", "reject", "nomzod yo'q: hech bir faol strategiya setup bermadi")
                continue
            tier = cand.score.tier
            if tier == "BLOCKED":
                out["blocked"] += 1
                self._t(symbol, "decision", "reject", f"BLOK: {cand.score.blocked}", cand.strategy_id)
                continue
            if tier == "DROP":
                out["dropped"] += 1
                self._t(symbol, "decision", "reject", f"ball {cand.score.score}/10 < 4: tashlandi", cand.strategy_id)
                continue
            if tier == "WATCH":
                out["watch"] += 1
                dup_w = self._duplicate_watch(cand, now)
                if not dup_w:
                    self.store(cand, now, "WATCH")
                self._t(symbol, "decision", "reject", f"WATCH (ball {cand.score.score}/10; yuborish uchun kamida 6 va 4H/1H trend+hajm+R/R kerak)"
                        + (" — takroriy, saqlanmadi" if dup_w else " — kuzatuvga saqlandi"), cand.strategy_id)
                continue
            dup = self._duplicate(cand, now)
            if dup:
                self._t(symbol, "decision", "reject", f"takroriy/kuldaun: {dup}", cand.strategy_id)
                out["duplicate"] += 1
                self.db.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES(?,?,?,?)",
                                ("-", now_iso(now), "duplicate", f"{symbol} {cand.direction}: {dup}"))
                continue
            if mode == "dry":
                self.store(cand, now, "DRY")
                out["dry"] += 1
                self._t(symbol, "decision", "ok", f"DRY (yuborilmaydi): {cand.direction} {tier}", cand.strategy_id)
                continue
            sig = self.store(cand, now, "NEW")
            if await self.publish(sig["signal_id"], cand):
                out["sent"] += 1
                self._t(symbol, "decision", "ok", f"YUBORILDI {sig['signal_id']}: {cand.direction} {tier}", cand.strategy_id)
                refused = self.db.one("SELECT decision_note FROM signals WHERE signal_id=? AND status='REFUSED'", (sig["signal_id"],))
                if refused:  # ijro pre-tekshiruvi rad etdi: tugma yo'q, bahs/auto yo'q (sabab xabarda va jurnalda)
                    out["precheck_refused"] = out.get("precheck_refused", 0) + 1
                    self._t(symbol, "precheck", "reject", (refused["decision_note"] or "")[:200], cand.strategy_id)
                    continue
                if self.trade_mode == "auto" and self.demo_enabled and tier in self._auto_tiers():
                    if await self.staff_gate(sig):  # bo'lim bahsi: rad bo'lsa signal tugma bilan (egasiga) qoladi
                        await self.auto_confirm(sig["signal_id"])  # AUTO: egasining tugmasisiz (faqat DEMO, hamma himoya bilan)
                        out["auto"] += 1
                    else:
                        out["staff_rejected"] = out.get("staff_rejected", 0) + 1
                        self._t(symbol, "staff", "reject", f"bahs rad etdi ({sig['signal_id']})", cand.strategy_id)
        self._flush_trace(out, (time.monotonic() - t0) * 1000)
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
        if self.target_chat() is None:
            return "Signal chati ulanmagan (guruh: /trading_guruh; shaxsiy chat: private_chat_id)"
        best: Candidate | None = None
        for sym in ([symbol] if symbol else list(self.cfg.get("universe", []))):
            if self.svc.settings.instrument(sym).get("provider", "binance") not in self.svc.market.providers:
                continue
            try:
                c = await asyncio.to_thread(self.scan_symbol, sym)
            except DataUnavailable:
                continue
            except Exception:  # noqa: BLE001 — bitta instrument xatosi (masalan MT5) testni to'xtatmasin
                log.exception("test signal skaneri %s", sym)
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

    async def publish(self, signal_id: str, cand: Candidate | None = None, header: str | None = None, buttons: bool = True) -> bool:
        from ..telegram_api import TelegramError, TelegramNetworkError
        row = self.db.one("SELECT * FROM signals WHERE signal_id=?", (signal_id,))
        chat = self.target_chat()
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
                             row["data_source"], datetime.fromisoformat(row["data_ts"]),
                             demo=self.demo_enabled and not signal_id.startswith("TST-"))
        if header:
            text = header + "\n\n" + text
        pre_ok, pre_stage, pre_reason = True, "", ""
        if buttons and self._exec_applicable(signal_id):  # V32: tugmadan OLDIN to'liq ijro pre-tekshiruvi (lot, risk, spred, R/R, kotirovka)
            import asyncio
            try:
                pre_ok, pre_stage, pre_reason = await asyncio.to_thread(self.precheck, row, self.svc.clock())
            except Exception as exc:  # noqa: BLE001 — tekshirib bo'lmasa ijro ruxsat berilmaydi
                log.exception("signal %s pre-tekshiruvi", signal_id)
                pre_ok, pre_stage, pre_reason = False, "precheck_error", f"pre-tekshiruv xatosi: {type(exc).__name__}"
            if not pre_ok:
                text += f"\n\n⛔ IJRO MUMKIN EMAS (tugma yo'q): {pre_reason}\nXavf nazorati chetlab o'tilmaydi."
        try:
            msg = await self.send(chat, text, keyboard(signal_id, row["direction"]) if (buttons and pre_ok) else None, None)  # buttons=False: AUTO, egasidan so'ralmaydi
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
        if not pre_ok:
            self.db.execute("UPDATE signals SET status='REFUSED', decision_note=?, decided_at=? WHERE signal_id=? AND status='SENT'",
                            (pre_reason[:300], now_iso(self.svc.clock()), signal_id))
            self._set_exec(signal_id, lc.EXECUTION_REFUSED)
            self.log_event(signal_id, "precheck_refused", f"{pre_stage}: {pre_reason}")
            self.audit(signal_id, "PRECHECK_REFUSED", pre_stage, pre_reason, risk="refused", mt5=lc.MT5_NOT_SENT)
        return True

    def _exec_applicable(self, signal_id: str) -> bool:
        """Pre-tekshiruv faqat MT5 DEMO ijrosi (risk bo'yicha lot) ko'zda tutilgan signallarda."""
        return (self.demo_enabled and self.trader is not None and self.cfg.get("sizing") == "risk"
                and not signal_id.startswith("TST-"))

    def precheck(self, row: dict, now: datetime) -> tuple[bool, str, str]:
        """Ijro pre-tekshiruvi: _open_group bilan AYNAN bir xil hisob (`_group_plan`): kunlik zarar, guruhlar, takroriy pozitsiya, korrelyatsiya,
        joriy narx va kotirovka yangiligi, R/R, spred, minimal lot va maksimal risk. Buyurtma YUBORILMAYDI. (ok, bosqich, sabab)"""
        plan, reason, ctx = self._group_plan(row, now)
        return (True, "", "") if plan is not None else (False, ctx["stage"], reason)

    # ------------------------------------------------------------------ tugma
    async def handle_callback(self, data: str, user_id: int | None, chat_id: int | None) -> str:
        """Telegram callback. Qaytadi: answerCallbackQuery matni. Faqat egasi; holat o'zgarishi atomik."""
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
        if chat_id != row["chat_id"] or chat_id not in self._allowed_chats():
            self.log_event(signal_id, "denied", f"chat {chat_id} signal chati emas")
            return "Bu chatda tasdiqlab bo'lmaydi"
        if row["status"] != "SENT":
            if row["status"] == "REFUSED":
                return f"Ijro mumkin emas: {row['decision_note'] or 'xavf nazorati rad etdi'}"[:190]
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
        return await self._confirm_flow(row, now, user_id, auto=False)

    async def auto_confirm(self, signal_id: str, origin: str | None = None) -> str:
        """AUTO rejim: signalni egasi tugmasisiz tasdiqlaydi (decided_by=0). Qayta tekshiruv va hamma himoya HA bilan bir xil.
        origin=forced_test — egasi buyrug'i bilan majburiy sinov (avtomatik zdelka sifatida sanalmaydi)."""
        row = self.db.one("SELECT * FROM signals WHERE signal_id=?", (signal_id,))
        if row is None or row["status"] != "SENT":
            return ""
        now = self.svc.clock()
        if self.db.execute("UPDATE signals SET status='CONFIRMING', decided_at=?, decided_by=0 WHERE signal_id=? AND status='SENT'",
                           (now_iso(now), signal_id)).rowcount != 1:
            return ""
        self.log_event(signal_id, "auto_confirm", "AUTO rejim")
        return await self._confirm_flow(row, now, 0, auto=True, origin=origin)

    async def _confirm_flow(self, row: dict, now: datetime, by: int, auto: bool, origin: str | None = None) -> str:
        import asyncio
        signal_id = row["signal_id"]
        origin = origin or (lc.ORIGIN_TEST if signal_id.startswith("TST-") else (lc.ORIGIN_AUTO if auto else lc.ORIGIN_MANUAL))
        self._set_exec(signal_id, lc.RISK_VALIDATION_PENDING, origin)
        try:
            ok, reason = await asyncio.to_thread(self.revalidate, row, now)
        except Exception as exc:  # noqa: BLE001
            ok, reason = False, f"qayta tekshiruv xatosi: {type(exc).__name__}"
            log.exception("signal %s qayta tekshiruvi", signal_id)
        if not ok:
            self.db.execute("UPDATE signals SET status='INVALIDATED', decision_note=? WHERE signal_id=?",
                            (reason[:300], signal_id))
            self.log_event(signal_id, "confirm_refused", reason)
            self._set_exec(signal_id, lc.INVALIDATED)
            self.audit(signal_id, "EXECUTION_REFUSED", "revalidate", reason, risk="not_run", mt5=lc.MT5_NOT_SENT, origin=origin)
            await self._finalize_message(row, "INVALIDATED", reason)
            return f"Tasdiqlanmadi: {reason}"[:190]
        demo = self.demo_enabled and not signal_id.startswith("TST-")  # TEST signalda haqiqiy demo buyurtma ochilmaydi
        label, demo_note, answer, ok_d, xi = None, "", "Tasdiqlandi — PAPER pozitsiya ochildi", False, {}
        if demo:
            ok_d, demo_note = await asyncio.to_thread(self._open_demo, row, now, auto, xi)
        # paper ma'lumot to'plami: rad etilgan zdelka ijro qilinadigan statistikaga KIRMAYDI (COUNTERFACTUAL), sinov — alohida (TEST)
        dataset = (lc.DS_TEST if origin in (lc.ORIGIN_TEST, lc.ORIGIN_FORCED)
                   else lc.DS_EXECUTABLE if (not demo or ok_d) else lc.DS_COUNTERFACTUAL)
        self.open_paper(row, now, dataset)
        if demo:
            self.log_event(signal_id, "demo_opened" if ok_d else "demo_refused", demo_note)
            who = "🤖 AUTO — " if auto else "✅ TASDIQLANDI — "
            label = (who + "paper pozitsiya + MT5 DEMO zdelka" if ok_d else
                     "⛔ IJRO RAD ETILDI — MT5 DEMO zdelka OCHILMADI (kuzatuv alohida, statistikaga kirmaydi)")
            answer = ("Tasdiqlandi — PAPER + MT5 DEMO zdelka ochildi" if ok_d else f"Ijro rad etildi — MT5 demo ochilmadi: {demo_note}"[:190])
        if demo and not ok_d:
            self.db.execute("UPDATE signals SET status='REFUSED', decision_note=? WHERE signal_id=?", (demo_note[:300], signal_id))
            self._set_exec(signal_id, lc.EXECUTION_REFUSED)
            self.log_event(signal_id, "execution_refused", f"{xi.get('stage', '?')}: user {by}")
            self.audit(signal_id, "EXECUTION_REFUSED", xi.get("stage", "unknown"), demo_note, risk=xi.get("risk", "refused"),
                       mt5=xi.get("mt5", lc.MT5_NOT_SENT), retcode=xi.get("retcode"), origin=origin)
            await self._finalize_message(row, "REFUSED", reason + f"\n{demo_note}", label)
            return answer
        self.db.execute("UPDATE signals SET status='CONFIRMED', decision_note=? WHERE signal_id=?",
                        ((demo_note or "paper pozitsiya ochildi")[:300], signal_id))
        self._set_exec(signal_id, lc.EXECUTED if demo else lc.EXECUTION_READY)
        self.log_event(signal_id, "confirmed", f"user {by}")
        self.audit(signal_id, "EXECUTED" if demo else "PAPER_ONLY", "mt5_order_send" if demo else "paper",
                   demo_note if demo else "demo_orders o'chiq: faqat paper", risk="passed" if demo else "not_run",
                   mt5=xi.get("mt5", lc.MT5_SENT_OK) if demo else lc.MT5_NA, retcode=xi.get("retcode"), origin=origin)
        await self._finalize_message(row, "CONFIRMED", reason + (f"\n{demo_note}" if demo_note else ""), label)
        return answer

    def _daily_loss_pct(self, now: datetime) -> float | None:
        """Bugungi (Toshkent kuni) zarar, kun boshidagi balansning %: yopilgan natija + suzuvchi. None — tekshirib bo'lmaydi."""
        if self.history is None:
            return None
        start = now.astimezone(self.svc.settings.tz).replace(hour=0, minute=0, second=0, microsecond=0)
        deals = self.history.deals_between(start.astimezone(timezone.utc), now + timedelta(minutes=5))
        realized = sum(d.net for d in deals if d.entry in ("OUT", "OUT_BY", "INOUT"))
        floating = sum(p["profit"] + p["swap"] for p in self.history.open_positions())
        start_balance = self.history.balance() - realized
        if start_balance <= 0:
            raise DataUnavailable("balans o'qilmadi")
        return max(0.0, -(realized + floating)) / start_balance * 100

    @staticmethod
    def _mt5_state(res: dict) -> str:
        """DemoTrader.open natijasi -> MT5 so'rovi holati. order_check rad etsa order_send CHAQIRILMAGAN."""
        if res.get("ok"):
            return lc.MT5_SENT_OK
        return {"order_check": lc.MT5_CHECK_REJECTED, "order_send": lc.MT5_SENT_REJECTED}.get(res.get("stage"), lc.MT5_NOT_SENT)

    def _open_demo(self, row: dict, now: datetime, auto: bool = False, xi: dict | None = None) -> tuple[bool, str]:
        """HA bosilganda MT5 DEMO zdelka: kunlik zarar chegarasi, takroriy pozitsiya tekshiruvi, keyin DemoTrader.open
        (hisob DEMO ekani, SL majburiy va to'g'ri tomonda, lot va pozitsiyalar chegarasi, order_check -> order_send)."""
        from .mt5_trade import TradeRefused
        name = mt5_name(row["symbol"])
        xi = xi if xi is not None else {}
        if self.cfg.get("sizing") == "risk":
            return self._open_group(row, now, auto, xi)
        xi.update(stage="risk_guard", risk="not_run", mt5=lc.MT5_NOT_SENT)
        try:
            resolved = self.trader.c.resolve(name)
            limit = float(self.cfg.get("daily_loss_pct", 5.0))
            loss = self._daily_loss_pct(now)
            if loss is not None and loss >= limit:
                return False, f"kunlik zarar chegarasi: {loss:.2f}% >= {limit:g}% — yangi zdelka ochilmaydi"
            side = "buy" if row["direction"] == "LONG" else "sell"
            if any(p["symbol"] == resolved and p["side"] == side for p in self.trader.positions()):
                return False, f"{resolved} da {side.upper()} pozitsiya allaqachon ochiq — takroran kirilmadi"
            xi.update(stage="mt5_open", risk="passed")
            res = self.trader.open(name, side, float(self.cfg.get("demo_lot", 0.01)), sl=row["sl"], tp=row["tp"])
        except TradeRefused as exc:
            xi.update(stage="mt5_refused", mt5=lc.MT5_NOT_SENT)
            return False, f"MT5 demo rad etdi: {exc}"
        except DataUnavailable as exc:
            xi.update(stage="mt5_data", mt5=lc.MT5_NOT_SENT)
            return False, f"MT5 ma'lumot yo'q: {str(exc)[:120]}"
        except Exception as exc:  # noqa: BLE001
            log.exception("MT5 demo zdelka %s", row["signal_id"])
            xi.update(stage="mt5_error", mt5=lc.MT5_NOT_SENT)
            return False, f"MT5 demo xatosi: {type(exc).__name__}"
        xi.update(stage=res.get("stage") or "mt5_open", mt5=self._mt5_state(res), retcode=res.get("retcode"))
        if not res["ok"]:
            return False, f"MT5 demo rad etildi ({res.get('stage')}): retcode {res.get('retcode')} {res.get('comment', '')}"[:300]
        return True, (f"MT5 DEMO zdelka ochildi: {resolved} {side.upper()} {self.cfg.get('demo_lot', 0.01)} lot, order "
                      f"#{res.get('order')}, narx {res.get('price')}, SL {row['sl']}, TP {row['tp']} (retcode {res.get('retcode')})")

    # ------------------------------------------------------------------ V28: guruh (2 pozitsiya), boshqaruv, o'chirgich
    def _group_plan(self, row: dict, now: datetime) -> tuple[object | None, str, dict]:  # (GroupPlan | None, sabab, ctx)
        """Zdelka rejasi — BUYURTMA YUBORMAYDI. Himoyalar: kunlik zarar, guruhlar soni, takroriy kirish, korrelyatsiya, balans, joriy narx,
        kotirovka yangiligi, SL >= 1 ATR, R/R, spred, lot/risk (minimal lot chegarasi bilan). Bir xil funksiya pre-tekshiruv (`precheck`) va
        ijro (`_open_group`) uchun ishlatiladi. Qaytadi: (reja | None, rad sababi, ctx{stage, name, side, resolved}). Sabab matnlari avvalgidek."""
        from . import autotrade as at
        from .exposure import Position
        from .exposure import check as corr_check
        from .mt5_trade import TradeRefused
        cfg, name = self.cfg, mt5_name(row["symbol"])
        side = "buy" if row["direction"] == "LONG" else "sell"
        ctx = {"name": name, "side": side, "resolved": None, "stage": "risk_guard"}
        try:
            resolved = self.trader.c.resolve(name)
            ctx["resolved"] = resolved
            limit = float(cfg.get("daily_loss_pct", 5.0))
            loss = self._daily_loss_pct(now)
            if loss is not None and loss >= limit:
                return None, f"kunlik zarar chegarasi: {loss:.2f}% >= {limit:g}% — yangi zdelka ochilmaydi", ctx
            self._reconcile_groups(now)
            max_groups = int(cfg.get("max_groups", 1))
            if len(self.db.query("SELECT 1 FROM demo_groups WHERE status='OPEN'")) >= max_groups:
                return None, f"ochiq zdelka guruhlari chegarasi: {max_groups}", ctx
            positions = self.trader.positions()
            if any(p["symbol"] == resolved and p["side"] == side for p in positions):
                return None, f"{resolved} da {side.upper()} pozitsiya allaqachon ochiq — takroran kirilmadi", ctx
            risk_pct, legs_est = float(cfg.get("risk_pct", 1.0)), (2 if cfg.get("split", True) else 1)
            v = corr_check([Position(p["symbol"], "LONG" if p["side"] == "buy" else "SHORT", risk_pct / legs_est)
                            for p in positions], Position(resolved, row["direction"], risk_pct))
            if not v.allowed:
                return None, "korrelyatsiya himoyasi: " + v.reason, ctx
            if self.history is None:
                return None, "balans o'qilmadi (MT5 tarixi ulanmagan) — lot hisoblanmadi", ctx
            ctx["stage"] = "quote"
            spec = self.trader.symbol_spec(name)
            age, max_age = spec.get("quote_age_s"), float(cfg.get("max_quote_age_s", 600))
            if age is not None and age > max_age:  # eskirgan kotirovka (bozor yopiq / uzilish): eski narx bo'yicha lot/R/R hisoblanmaydi
                return None, f"kotirovka eskirgan: {age:.0f} s > {max_age:g} s (bozor yopiq yoki narx kelmayapti)", ctx
            ctx["stage"] = "risk_plan"
            price = spec["ask"] if side == "buy" else spec["bid"]
            atr = (json.loads(row["analysis"]).get("evidence") or {}).get("atr14")
            plan = at.plan_group(side=side, price=price, sl=row["sl"], tp=row["tp"], atr=atr, balance=self.history.balance(),
                                 spec=spec, risk_pct=risk_pct, min_sl_atr=float(cfg.get("min_sl_atr", 1.0)),
                                 min_rr=float(self.svc.settings.get("min_rr", 1.5)), tp1_r=float(cfg.get("tp1_r", 1.0)),
                                 split=bool(cfg.get("split", True)), max_lot=float(self.trader.max_lot), spread=spec["spread"],
                                 max_spread_sl=float(cfg.get("max_spread_sl", 0.10)),
                                 min_lot_fallback=bool(cfg.get("min_lot_fallback", False)),
                                 min_lot_max_risk_pct=float(cfg.get("min_lot_max_risk_pct", 8.0)))
            return plan, "", ctx
        except at.PlanRefused as exc:
            return None, f"zdelka rejasi: {exc}", ctx
        except TradeRefused as exc:
            ctx["stage"] = "mt5_data"
            return None, f"MT5 demo rad etdi: {exc}", ctx
        except DataUnavailable as exc:
            ctx["stage"] = "mt5_data"
            return None, f"MT5 ma'lumot yo'q: {str(exc)[:120]}", ctx
        except Exception as exc:  # noqa: BLE001
            log.exception("MT5 demo guruh rejasi %s", row["signal_id"])
            ctx["stage"] = "mt5_error"
            return None, f"MT5 demo xatosi: {type(exc).__name__}", ctx

    def _open_group(self, row: dict, now: datetime, auto: bool = False, xi: dict | None = None) -> tuple[bool, str]:
        """Signal -> 1% riskdan hisoblangan lot, 2 pozitsiya (A: yaqin TP, B: to'liq TP). Reja `_group_plan` (hamma himoya) dan; keyin
        faqat DemoTrader (faqat DEMO) orqali buyurtma. `xi` — ijro jurnali uchun: bosqich, risk natijasi, MT5 so'rovi holati/kodi."""
        from .mt5_trade import TradeRefused
        xi = xi if xi is not None else {}
        plan, reason, ctx = self._group_plan(row, now)
        if plan is None:  # MT5 ga hech narsa yuborilmadi
            xi.update(stage=ctx["stage"], risk="refused", mt5=lc.MT5_NOT_SENT, retcode=None)
            return False, reason
        xi.update(stage="mt5_open", risk="passed", mt5=lc.MT5_NOT_SENT, retcode=None)
        name, side, resolved = ctx["name"], ctx["side"], ctx["resolved"]
        opened, lines = [], []
        try:
            for leg in plan.legs:
                try:
                    res = self.trader.open(name, side, leg.lot, sl=plan.sl, tp=leg.tp, comment=f"{row['signal_id']}{leg.tag}")
                except TradeRefused as exc:
                    res = {"ok": False, "stage": "refused", "comment": str(exc)}
                xi.update(stage=res.get("stage") or "mt5_open", mt5=self._mt5_state(res), retcode=res.get("retcode"))
                if not res["ok"]:
                    lines.append(f"{leg.tag}: OCHILMADI ({res.get('stage')}: {res.get('retcode')} {res.get('comment', '')})"[:200])
                    break
                opened.append({"tag": leg.tag, "lot": leg.lot, "tp": leg.tp, "ticket": res.get("order"), "price": res.get("price")})
                lines.append(f"{leg.tag}: {leg.lot} lot, TP {leg.tp}, order #{res.get('order')}, narx {res.get('price')}")
        except Exception as exc:  # noqa: BLE001
            log.exception("MT5 demo guruh %s", row["signal_id"])
            xi.update(stage="mt5_error")
            return False, f"MT5 demo xatosi: {type(exc).__name__}"
        if not opened:
            return False, "MT5 demo rad etildi: " + "; ".join(lines)
        self.db.execute("INSERT OR REPLACE INTO demo_groups(signal_id, symbol, side, tickets, legs, sl, risk_money, risk_actual, "
                        "mode, opened_at, status, note) VALUES(?,?,?,?,?,?,?,?,?,?,'OPEN',?)",
                        (row["signal_id"], resolved, side, json.dumps([o["ticket"] for o in opened]), json.dumps(opened), plan.sl,
                         plan.risk_money, plan.risk_actual, "auto" if auto else "confirm", now_iso(now),
                         "; ".join(plan.notes)))
        txt = (f"MT5 DEMO guruh ochildi: {resolved} {side.upper()}, SL {plan.sl} ({plan.dist:.6g} masofa), risk "
               f"~{plan.risk_actual:g} (reja {plan.risk_money:g}). " + " | ".join(lines))
        if len(opened) < len(plan.legs):
            txt += " ⚠️ guruh to'liq ochilmadi"
        if plan.notes:
            txt += " | " + "; ".join(plan.notes)
        return True, txt

    def _reconcile_groups(self, now: datetime) -> int:
        """Ochiq guruhlarning pozitsiyalari MT5'da qolmagan bo'lsa — guruh yopilgan deb belgilanadi."""
        open_tickets = {p["ticket"] for p in (self.history.open_positions() if self.history else self.trader.positions())}
        closed = 0
        for g in self.db.query("SELECT * FROM demo_groups WHERE status='OPEN'"):
            if not (set(json.loads(g["tickets"])) & open_tickets):
                self.db.execute("UPDATE demo_groups SET status='CLOSED', closed_at=? WHERE signal_id=?", (now_iso(now), g["signal_id"]))
                closed += 1
        return closed

    def _close_group(self, g: dict, reason: str) -> list[str]:
        out = []
        open_now = {p["ticket"] for p in self.trader.positions()}
        for t in json.loads(g["tickets"]):
            if t in open_now:
                res = self.trader.close(int(t))
                out.append(f"#{t}: {'yopildi' if res.get('ok') else 'YOPILMADI ' + str(res.get('comment'))}")
        self.db.execute("UPDATE demo_groups SET status='CLOSED', closed_at=?, note=COALESCE(note,'') || ? WHERE signal_id=?",
                        (now_iso(self.svc.clock()), f" | {reason}", g["signal_id"]))
        return out

    async def manage(self, now: datetime) -> list[str]:
        """Ochiq guruhlarni boshqarish: yopilganlarni belgilash, vaqt chegarasi (time_stop_h) bo'yicha yopish, o'chirgich."""
        import asyncio
        if self.trader is None or not self.demo_enabled or self.cfg.get("sizing") != "risk":
            return []
        acts: list[str] = []
        await asyncio.to_thread(self._reconcile_groups, now)
        limit = timedelta(hours=float(self.cfg.get("time_stop_h", 48)))
        for g in self.db.query("SELECT * FROM demo_groups WHERE status='OPEN'"):
            if now - datetime.fromisoformat(g["opened_at"]) >= limit:
                try:
                    res = await asyncio.to_thread(self._close_group, g, f"vaqt chegarasi ({limit.total_seconds() / 3600:g} soat)")
                except Exception as exc:  # noqa: BLE001
                    log.exception("guruh yopilmadi %s", g["signal_id"])
                    res = [f"xato: {type(exc).__name__}"]
                self.log_event(g["signal_id"], "time_stop", "; ".join(res))
                acts.append(f"time_stop:{g['signal_id']}")
                srow = self.db.one("SELECT * FROM signals WHERE signal_id=?", (g["signal_id"],))
                if srow:
                    await self._reply(srow, f"⏱ {g['signal_id']}: vaqt chegarasi ({limit.total_seconds() / 3600:g} soat) — qolgan "
                                            f"pozitsiyalar yopildi. {'; '.join(res)}")
        tripped = await self._check_breaker(now)
        if tripped:
            acts.append("breaker")
        try:
            await self.audit_closed_losses(now)
        except Exception:  # noqa: BLE001 — audit asosiy boshqaruvni to'xtatmasin
            log.exception("zarar auditi")
        return acts

    async def audit_closed_losses(self, now: datetime) -> int:
        """Yopilgan zararli guruhlar uchun AUDIT-1 xato tahlili (bir marta, oxirgi 3 kun). Natija bazaga va egasining shaxsiy chatiga."""
        if self.desk is None or not self.cfg.get("staff_audit", True):
            return 0
        done = 0
        since = now_iso(now - timedelta(days=3))
        for g in self.db.query("SELECT * FROM demo_groups WHERE status='CLOSED' AND closed_at>=?", (since,)):
            if self.db.one("SELECT 1 FROM staff_decisions WHERE kind='audit' AND ref=?", (g["signal_id"],)):
                continue
            tickets = json.loads(g["tickets"])
            rows = self.db.query(f"SELECT position_id, net, reason, r_multiple FROM live_trades WHERE position_id IN "
                                 f"({','.join('?' * len(tickets))})", tickets)
            if len(rows) != len(tickets) or sum(r["net"] or 0 for r in rows) >= 0:
                continue  # natija hali yozilmagan yoki foyda
            sig = self.db.one("SELECT * FROM signals WHERE signal_id=?", (g["signal_id"],)) or {}
            facts = (f"signal {g['signal_id']} {g['symbol']} {g['side']} SL {g['sl']} ochilgan {g['opened_at']} yopilgan {g['closed_at']}; "
                     f"rejalashtirilgan risk {g['risk_money']}, haqiqiy {g['risk_actual']}; pozitsiyalar: {json.dumps(rows)}; "
                     f"signal: daraja {sig.get('tier')} ball {sig.get('score')} kirish {sig.get('entry')} TP {sig.get('tp')} "
                     f"strategiya {sig.get('strategy_id')}; tahlil: {(sig.get('analysis') or '')[:1500]}")
            text = await self.desk.audit_loss(g["signal_id"], facts)
            if text and self.notify_private is not None:
                await self.notify_private(f"🔎 AUDIT-1 | zarar tahlili {g['signal_id']}\n{text[:1500]}")
            done += 1
            if done >= 2:
                break
        return done

    def group_nets(self, since: str | None = None) -> list[float]:
        """Yopilgan guruhlar natijasi (yangi bo'lib tugatilgan tartibda eskidan yangiga). Pozitsiyalar natijasi live_trades dan;
        hali yozilmagan (monitor tasdiqlamagan) guruh o'tkazib yuboriladi."""
        q = "SELECT * FROM demo_groups WHERE status='CLOSED'" + (" AND opened_at>=?" if since else "") + " ORDER BY closed_at"
        nets = []
        for g in self.db.query(q, (since,) if since else ()):
            tickets = json.loads(g["tickets"])
            rows = self.db.query(f"SELECT net FROM live_trades WHERE position_id IN ({','.join('?' * len(tickets))})", tickets)
            if len(rows) == len(tickets):
                nets.append(sum(r["net"] for r in rows))
        return nets

    async def _check_breaker(self, now: datetime) -> bool:
        """Aylanma o'chirgich: ketma-ket breaker_losses guruh zarar yoki cho'qqidan breaker_dd_pct pasayish -> AUTO o'chadi."""
        from . import autotrade as at
        if self.trade_mode != "auto":
            return False
        nets = self.group_nets(self.cfg.get("auto_since"))
        losses = at.consecutive_losses(list(reversed(nets)))
        dd = 0.0
        if self.history is not None and nets:
            try:
                dd = at.drawdown_pct(nets, self.history.balance() - sum(nets))
            except DataUnavailable:
                dd = 0.0
        reason = None
        if losses >= int(self.cfg.get("breaker_losses", 3)):
            reason = f"ketma-ket {losses} ta zdelka guruhi zararda yopildi"
        elif dd >= float(self.cfg.get("breaker_dd_pct", 10.0)):
            reason = f"yig'ma natija cho'qqisidan {dd:.1f}% pasayish"
        if not reason:
            return False
        self.set_trade_mode("confirm", f"AUTO O'CHIRGICH: {reason}")
        chat = self.svc.settings.private_chat_id
        if chat:
            with suppress(Exception):
                await self.send(chat, f"🛑 SENTINEL | AUTO O'CHIRILDI\n{reason}.\nRejim CONFIRMATION ga qaytdi (tugma bilan tasdiq). "
                                      "Qayta yoqish: /trading_mode auto (hisoblagich yangilanadi).", None, None)
        self.log_event("-", "breaker", reason)
        return True

    def flat_all(self) -> list[str]:
        """Faqat o'zimiz (SENTINAL magic) ochgan hamma pozitsiyani yopish. Qo'lda yoki EA ochganlariga tegilmaydi."""
        out = []
        for p in self.trader.positions():
            res = self.trader.close(int(p["ticket"]))
            out.append(f"#{p['ticket']} {p['symbol']}: " + ("yopildi" if res.get("ok") else f"YOPILMADI ({res.get('comment')})"))
        self._reconcile_groups(self.svc.clock())
        return out

    def apply_mode(self, mode: str, note: str = "") -> tuple[bool, str]:
        """Rejimni o'zgartirish (Telegram va veb uchun bir xil qoida). mode: analysis | confirm | auto."""
        cfg = self.svc.settings.data.setdefault("signals", {})
        if mode not in ("analysis", "confirm", "auto"):
            return False, f"noma'lum rejim: {mode}"
        if mode == "auto" and not (self.demo_enabled and cfg.get("sizing") == "risk"):
            return False, "AUTO yoqilmadi: demo_orders yoqilgan va sizing=risk bo'lishi kerak"
        cfg["mode"] = "dry" if mode == "analysis" else "live"
        self.set_trade_mode("auto" if mode == "auto" else "confirm", note)
        return True, mode

    async def staff_gate(self, sig: dict) -> bool:
        """Bo'lim (DIR-1 + bahschilar) signalni muhokama qiladi. True — ochishga ruxsat (himoyalar baribir tekshiriladi).
        Bo'lim ulanmagan yoki staff_gate o'chiq bo'lsa — eski xulq (kuchli signal to'g'ridan-to'g'ri)."""
        if self.desk is None or not self.cfg.get("staff_gate", True):
            return True
        row = self.db.one("SELECT * FROM signals WHERE signal_id=?", (sig["signal_id"],))
        self._set_exec(sig["signal_id"], lc.DEBATE_PENDING)
        verdict = await self.desk.review_signal(row)
        self.log_event(sig["signal_id"], "staff_" + ("approve" if verdict.approve else "reject"), verdict.reason[:300])
        # bahs ma'qullashi = faqat ruxsat; zdelka OCHILGAN degani EMAS (EXECUTED faqat MT5 order_send dan keyin)
        self._set_exec(sig["signal_id"], lc.DEBATE_APPROVED if verdict.approve else lc.DEBATE_REJECTED)
        self.audit(sig["signal_id"], "DEBATE_APPROVED" if verdict.approve else "DEBATE_REJECTED", "debate", verdict.reason[:300],
                   mt5=lc.MT5_NOT_SENT)
        return verdict.approve

    def set_trade_mode(self, mode: str, note: str = "") -> None:
        cfg = self.svc.settings.data.setdefault("signals", {})
        cfg["trade_mode"] = mode
        if mode == "auto":
            cfg["auto_since"] = now_iso(self.svc.clock())  # o'chirgich hisoblagichi shundan boshlanadi
        self.svc.settings.save()
        self._event("trading_signals", f"Savdo rejimi: {mode}" + (f" ({note})" if note else ""), mode=mode)

    def _claim(self, signal_id: str, status: str, note: str, by: int | None = None) -> bool:
        ok = self.db.execute("UPDATE signals SET status=?, decision_note=?, decided_at=?, decided_by=? WHERE signal_id=? "
                             "AND status='SENT'", (status, note, now_iso(self.svc.clock()), by, signal_id)).rowcount == 1
        if ok:
            self.log_event(signal_id, status.lower(), note)
            if status == "EXPIRED":
                self._set_exec(signal_id, lc.EXPIRED)
                self.audit(signal_id, "EXPIRED", "expired", note, mt5=lc.MT5_NOT_SENT)
            elif status == "INVALIDATED":
                self._set_exec(signal_id, lc.INVALIDATED)
                self.audit(signal_id, "INVALIDATED", "invalidated", note, mt5=lc.MT5_NOT_SENT)
            elif status == "REJECTED" and note.startswith("bahs"):  # zona vazifasi: bahs rad etdi
                self._set_exec(signal_id, lc.DEBATE_REJECTED)
                self.audit(signal_id, "DEBATE_REJECTED", "debate", note, mt5=lc.MT5_NOT_SENT)
            elif status == "REJECTED":  # egasi YO'Q tugmasini bosdi
                self._set_exec(signal_id, lc.EXECUTION_REFUSED, lc.ORIGIN_MANUAL)
                self.audit(signal_id, "EXECUTION_REFUSED", "owner_reject", note, mt5=lc.MT5_NOT_SENT, origin=lc.ORIGIN_MANUAL)
        return ok

    async def _finalize_message(self, row: dict, status: str, note: str, label: str | None = None) -> None:
        """Asl xabarni yangilash (tugmalar olib tashlanadi — edit_message_text reply_markup'ni tozalaydi)."""
        if not row.get("message_id") or not row.get("chat_id"):
            return
        text = (row.get("text") or row["signal_id"]) + f"\n\n{label or STATUS_LABEL[status]}" + (f"\n{note}" if note else "")
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
        mkt = s.settings.instrument(row["symbol"]).get("market", "crypto")
        warns = [w for w in b15.warnings if not (mkt != "crypto" and "tushib qolgan" in w)]  # forex/indeks: hafta oxiri/sessiya bo'shlig'i normal
        if warns:
            return False, "ma'lumot sifati: " + "; ".join(warns)
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

    def open_paper(self, row: dict, now: datetime, dataset: str = lc.DS_EXECUTABLE) -> None:
        """Simulyatsion pozitsiya: signaldagi kirish turi va narxi bilan (stop/limit/next_open), tasdiq vaqtidan keyingi
        15M shamlardan boshlab kuzatiladi. Eski narx bo'yicha 'to'ldirish' YO'Q."""
        start = datetime.fromtimestamp((int(now.timestamp()) // FIFTEEN + 1) * FIFTEEN, tz=timezone.utc)
        s = self.svc
        self.db.execute(
            "INSERT OR IGNORE INTO paper_positions(signal_id, symbol, direction, entry_type, entry_signal, sl, tp, "
            "confirmed_at, data_end, valid_until, status, spread, commission, max_hold, invalidation, notified, dataset) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["signal_id"], row["symbol"], row["direction"], row["entry_type"], row["entry"], row["sl"], row["tp"],
             now_iso(now), now_iso(start), row["valid_until"], "PENDING", json.loads(row["analysis"]).get("spread", 0.0),
             json.loads(row["analysis"]).get("commission", 0.0), int(s.settings.get("max_hold_bars", 48)),
             row["invalidation"], "PENDING", dataset))
        self.log_event(row["signal_id"], "paper_opened", f"[{dataset}] {row['entry_type']} {row['entry']} SL {row['sl']} TP {row['tp']}")

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
        if pos.get("dataset") == lc.DS_COUNTERFACTUAL:  # rad etilgan signal: egasiga "paper natija" xabari YUBORILMAYDI
            self.db.execute("UPDATE paper_positions SET notified=? WHERE signal_id=?", (pos["status"], signal_id))
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
                            "WHERE signal_id NOT LIKE 'TST-%' AND COALESCE(dataset,'EXECUTABLE')='EXECUTABLE' GROUP BY status")
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
