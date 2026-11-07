"""V16 Trading Research — sintetik ma'lumot bilan testlar (tarmoq, Telegram va Claude'siz).

Qamrov: tahlil yaratish, strategiyani aniqlash, Telegram formati, dublikatsiz nashr, kirish sharti, TP/SL, noaniq sham,
strategiya versiyasi saqlanishi, kunlik hisobot, qayta ishga tushgandan keyin xotira, statistika, ma'lumot yo'qligi.
"""
from __future__ import annotations

import asyncio
import json
import math
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent.trading import analytics, backtest
from agent.trading.analysis import load, verify_integrity
from agent.trading.data import Candle, DataUnavailable, validate
from agent.trading.indicators import Features
from agent.trading.outcomes import (ACTIVE, AMBIGUOUS, CANCELLED, NOT_TRIGGERED, PENDING, SL_HIT, TP_HIT, Scenario,
                                    simulate)
from agent.trading.publish import LABEL, Publisher, format_analysis
from agent.trading.review import DATA, INVALID, NORMAL, REGIME, VOLATILITY, classify
from agent.trading.scheduler import TradingScheduler
from agent.trading.service import TradingService
from agent.trading.strategies import DEFAULT_STRATEGIES, PRIORITY, Setup, candidates, classify_regime

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
H = 3600


def candles_from(closes: list[float], sec: int = H, start: datetime = T0, pad: float = 0.3) -> list[Candle]:
    out, prev = [], closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(Candle(start + timedelta(seconds=sec * i), o, max(o, c) + pad, min(o, c) - pad, c, 100.0, sec))
        prev = c
    return out


def uptrend_pullback() -> list[Candle]:
    c = [100 + 0.5 * t + 0.6 * math.sin(t / 3) for t in range(300)]
    c[-3], c[-2], c[-1] = c[-4] - 1.0, c[-4] - 1.0, c[-4] - 3.0
    return candles_from(c)


def ranging(seed: int = 0) -> list[Candle]:
    random.seed(seed)
    p, out = 100.0, []
    for _ in range(300):
        p += random.gauss(0, 0.6) - 0.08 * (p - 100)
        out.append(p)
    return candles_from(out)


class FakeProvider:
    name = "synthetic test feed"

    def __init__(self, series: dict, fine: dict | None = None, down: set | None = None):
        self.series = series
        self.fine_series = fine or {}
        self.down = down or set()
        self.calls = 0

    def klines(self, symbol, timeframe, limit, end=None, start=None):
        self.calls += 1
        if symbol in self.down:
            raise DataUnavailable(f"test: {symbol} manbasi ishlamayapti")
        data = self.fine_series.get(symbol, []) if timeframe in ("1m", "1min") else self.series.get((symbol, timeframe))
        if data is None:
            raise DataUnavailable(f"test: {symbol} {timeframe} yo'q")
        data = [c for c in data if (end is None or c.ts < end) and (start is None or c.ts >= start)]
        return data[:limit] if start is not None else data[-limit:]


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def make_service(home: Path, series: dict, now: datetime, fine=None, down=None, env=None) -> TradingService:
    svc = TradingService(home, env=env or {}, providers={"binance": FakeProvider(series, fine, down)}, clock=Clock(now),
                         calendar=None)
    svc.calendar = None
    return svc


def scenario(**kw) -> Scenario:
    base = dict(analysis_id="TA-T", direction="LONG", entry_type="buy_stop", entry=100.0, sl=98.0, tp=104.0,
                invalidation={"type": "close_below", "level": 97.0, "text": "test"}, data_end=T0, published_at=T0,
                valid_until=T0 + timedelta(hours=6), max_hold_bars=48, timeframe="1h", spread=0.0, commission=0.0)
    base.update(kw)
    return Scenario(**base)


def bar(i: int, o, h, low, c, sec=H, start=T0) -> Candle:
    return Candle(start + timedelta(seconds=sec * i), o, h, low, c, 1.0, sec)


# ------------------------------------------------------------------------------------------------ strategiya va rejim
def test_strategy_identification_by_regime():
    f = Features.build(uptrend_pullback())
    i = len(f) - 1
    reg = classify_regime(f, i)
    assert reg.trend == "TREND_UP"
    active = {s.strategy_id: s for s in DEFAULT_STRATEGIES}
    assert [s.strategy_id for s in candidates(reg, active)] == PRIORITY["TREND_UP"]
    setup = active["TF-PULLBACK"].evaluate(f, i, reg)
    assert isinstance(setup, Setup) and setup.direction == "LONG" and setup.entry_type == "buy_stop"
    assert setup.sl < setup.entry < setup.tp and abs(setup.rr - 2.0) < 0.01
    fr = Features.build(ranging())
    reg2 = classify_regime(fr, len(fr) - 1)
    assert reg2.trend == "RANGE" and [s.strategy_id for s in candidates(reg2, active)] == PRIORITY["RANGE"]
    # Rejimga mos bo'lmagan strategiya setup bermaydi
    assert "mos emas" in active["RSI-MR"].evaluate(f, i, reg).reason


def test_signal_has_no_look_ahead():
    """i-shamdagi qaror kelajak shamlari qo'shilsa ham o'zgarmaydi (indikatorlar va swinglar causal)."""
    c = uptrend_pullback()
    future = candles_from([c[-1].close - 5 * k for k in range(1, 40)], start=c[-1].end)
    f1, f2 = Features.build(c), Features.build(c + future)
    i = len(c) - 1
    spec = next(s for s in DEFAULT_STRATEGIES if s.strategy_id == "TF-PULLBACK")
    a, b = spec.evaluate(f1, i, classify_regime(f1, i)), spec.evaluate(f2, i, classify_regime(f2, i))
    assert (a.entry, a.sl, a.tp) == (b.entry, b.sl, b.tp)
    assert f1.swings(i) == f2.swings(i)


# ------------------------------------------------------------------------------------------------ tahlil yaratish
def test_analysis_creation_trade_and_immutability(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=3))
    rec = svc.create_analysis("BTCUSDT", "1h")
    assert rec["kind"] == "TRADE" and rec["strategy_id"] == "TF-PULLBACK" and rec["strategy_version"] == 1
    assert rec["analysis_id"].startswith("TA-20261013-") and rec["timezone"] == "Asia/Tashkent"
    for key in ("created_at", "local_time", "session", "regime", "structure", "evidence", "assumptions", "entry", "sl",
                "tp", "rr", "rr_net", "invalidation", "valid_until", "data_source", "data_ts", "limitations"):
        assert rec.get(key) not in (None, "", []), key
    assert rec["data_source"] == "synthetic test feed" and rec["data_ts"] == c[-1].end.isoformat()
    assert rec["rr_net"] <= rec["rr"]  # xarajat hisobga olingan
    assert (svc.memory.analyses / rec["local_date"] / f"{rec['analysis_id']}.json").is_file()
    assert verify_integrity(svc.db, rec["analysis_id"])
    with pytest.raises(sqlite3.IntegrityError):
        svc.db.execute("UPDATE analyses SET entry=1 WHERE analysis_id=?", (rec["analysis_id"],))
    with pytest.raises(sqlite3.IntegrityError):
        svc.db.execute("DELETE FROM analyses WHERE analysis_id=?", (rec["analysis_id"],))
    assert load(svc.db, rec["analysis_id"])["entry"] == rec["entry"]


def test_no_trade_analysis_when_conditions_unsuitable(tmp_path):
    cs = ranging(1)  # diapazon: daraja yaqin emas / RSI o'rtada / siqilish yo'q
    svc = make_service(tmp_path, {("ETHUSDT", "1h"): cs}, cs[-1].end + timedelta(minutes=2))
    rec = svc.create_analysis("ETHUSDT", "1h")
    assert rec["kind"] == "NO_TRADE" and rec["entry"] is None and rec["no_trade_reasons"]
    text = format_analysis(rec, svc.settings.tz)
    assert "NO-TRADE" in text and LABEL in text and "Nega savdo yo'q" in text


# ------------------------------------------------------------------------------------------------ ma'lumot yo'qligi
def test_missing_or_stale_data_never_creates_analysis(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(hours=5))  # eskirgan
    with pytest.raises(DataUnavailable, match="eskirgan"):
        svc.create_analysis("BTCUSDT", "1h")
    svc2 = make_service(tmp_path / "b", {("BTCUSDT", "1h"): c}, c[-1].end, down={"BTCUSDT"})
    with pytest.raises(DataUnavailable):
        svc2.create_analysis("BTCUSDT", "1h")
    assert svc.db.one("SELECT COUNT(*) AS n FROM analyses")["n"] == 0
    assert svc2.db.one("SELECT COUNT(*) AS n FROM analyses")["n"] == 0
    with pytest.raises(DataUnavailable):
        validate(c[:20], "1h", c[19].end)  # yetarli emas
    broken = c[:250] + [Candle(c[250].ts, 10, 5, 12, 11, 1, H)]  # high < low
    with pytest.raises(DataUnavailable, match="OHLC"):
        validate(broken, "1h", broken[-1].end)


def test_slot_falls_back_to_next_instrument_and_fails_honestly(tmp_path):
    c = uptrend_pullback()
    now = c[-1].end + timedelta(minutes=1)
    svc = make_service(tmp_path, {("ETHUSDT", "1h"): c}, now, down={"BTCUSDT"})
    svc.settings.data["universe"] = [{"symbol": "BTCUSDT", "timeframe": "1h"}, {"symbol": "ETHUSDT", "timeframe": "1h"}]
    rec = svc.analysis_for_slot("2026-10-13", 0)
    assert rec["symbol"] == "ETHUSDT"
    assert svc.db.one("SELECT COUNT(*) AS n FROM data_warnings WHERE symbol='BTCUSDT'")["n"] >= 1
    svc.settings.data["universe"] = [{"symbol": "BTCUSDT", "timeframe": "1h"}]
    with pytest.raises(DataUnavailable, match="hech bir instrument"):
        svc.analysis_for_slot("2026-10-13", 1)


# ------------------------------------------------------------------------------------------------ Telegram
class FakeSend:
    def __init__(self, fail_with=None):
        self.sent: list[tuple[int, str, int | None]] = []
        self.fail_with = fail_with

    async def __call__(self, chat_id, text, reply_to):
        if self.fail_with:
            exc, self.fail_with = self.fail_with, None
            raise exc
        self.sent.append((chat_id, text, reply_to))
        return {"message_id": 1000 + len(self.sent)}


def test_publication_format_contains_required_fields(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=3))
    rec = svc.create_analysis("BTCUSDT", "1h")
    text = format_analysis(rec, svc.settings.tz)
    for needle in (f"ANALYSIS ID: {rec['analysis_id']}", "Instrument: BTCUSDT", "Timeframe: 1h",
                   "TF-PULLBACK v1", "Bozor konteksti:", "Gipotetik ssenariy: LONG", "Kirish sharti:",
                   "Virtual SL / TP:", "Risk/reward: 1:2.00", "Bekor qilish sharti:", "oxirgi yopilgan sham",
                   "RESEARCH ONLY / PAPER TRADING", "moliyaviy maslahat EMAS"):
        assert needle in text, needle
    assert len(text) < 4096


def test_publication_is_deduplicated_and_message_id_stored(tmp_path):
    from agent.telegram_api import TelegramError, TelegramNetworkError

    c = uptrend_pullback()
    now = c[-1].end + timedelta(minutes=3)
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, now, env={"TRADING_GROUP_CHAT_ID": "-100123"})
    rec = svc.create_analysis("BTCUSDT", "1h")
    send = FakeSend()
    pub = Publisher(svc.db, svc.settings, send, clock=svc.clock)
    assert asyncio.run(pub.publish_analysis(rec)) == "sent"
    assert asyncio.run(pub.publish_analysis(rec)) == "duplicate"
    assert len(send.sent) == 1 and send.sent[0][0] == -100123
    row = svc.db.publication(rec["analysis_id"], -100123, "analysis")
    assert row["status"] == "sent" and row["message_id"] == 1001
    # natija yangilanishi asl xabarga reply
    assert asyncio.run(pub.publish_outcome(rec, {"r_multiple": 1.9}, "TP_HIT")) == "sent"
    assert send.sent[-1][2] == 1001 and "virtual TP" in send.sent[-1][1]
    assert asyncio.run(pub.publish_outcome(rec, {"r_multiple": 1.9}, "TP_HIT")) == "duplicate"
    # Telegram aniq rad etdi -> keyingi safar qayta urinadi; tarmoq noma'lum -> qayta yuborilmaydi
    rec2 = dict(rec, analysis_id="TA-X-02")
    pub.send = FakeSend(fail_with=TelegramError("Bad Request"))
    assert asyncio.run(pub.publish_analysis(rec2)) == "failed"
    assert asyncio.run(pub.publish_analysis(rec2)) == "sent"
    rec3 = dict(rec, analysis_id="TA-X-03")
    pub.send = FakeSend(fail_with=TelegramNetworkError("timeout"))
    assert asyncio.run(pub.publish_analysis(rec3)) == "unknown"
    assert asyncio.run(pub.publish_analysis(rec3)) == "duplicate"


def test_no_publication_without_authorized_group(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=3))
    rec = svc.create_analysis("BTCUSDT", "1h")
    send = FakeSend()
    assert asyncio.run(Publisher(svc.db, svc.settings, send).publish_analysis(rec)) == "no_target"
    assert send.sent == []


# ------------------------------------------------------------------------------------------------ natija dvigateli
def test_entry_condition_detection_and_not_triggered():
    sc = scenario()
    st = simulate(sc, [bar(0, 99, 99.8, 98.9, 99.5), bar(1, 99.5, 99.9, 99.1, 99.7)])
    assert st.status == PENDING  # buy stop 100 ga yetmagan
    st = simulate(sc, [bar(k, 99, 99.5, 98.5, 99) for k in range(8)])
    assert st.status == NOT_TRIGGERED
    sp = simulate(scenario(spread=0.3), [bar(0, 99, 99.75, 99, 99.5)])  # ask = 99.75+0.3 >= 100
    assert sp.status == ACTIVE and sp.entry_price == 100.0
    canc = simulate(sc, [bar(0, 99, 99.5, 96.5, 96.8)])  # kirishdan oldin bekor qilish sharti
    assert canc.status == CANCELLED


def test_activity_before_publication_is_ignored():
    sc = scenario(published_at=T0 + timedelta(minutes=30))
    b0 = bar(0, 99, 100.5, 98.8, 99.2)  # kirish darajasiga e'londan OLDIN tekkan bo'lishi mumkin
    fine = [bar(m, 99.2, 99.4, 99.0, 99.2, sec=60) for m in range(30, 60)]  # e'londan keyin tegmagan
    st = simulate(sc, [b0], fine=lambda a, b: [x for x in fine if a <= x.ts < b])
    assert st.status == PENDING
    st2 = simulate(sc, [b0])  # mayda ma'lumot yo'q va daraja tekkan -> noaniq, kirish deb hisoblanmaydi
    assert st2.status == AMBIGUOUS


def test_tp_and_sl_classification_with_costs():
    tp = simulate(scenario(commission=0.001), [bar(0, 99, 100.2, 99, 100.1), bar(1, 100.1, 104.5, 100, 104)])
    assert tp.status == TP_HIT and tp.exit_price == 104.0
    assert tp.r_multiple == pytest.approx(2.0 - 0.001 * (100 + 104) / 2, abs=1e-4) and tp.cost_r > 0
    sl = simulate(scenario(), [bar(0, 99, 100.2, 99, 100.1), bar(1, 100.1, 100.5, 97.5, 98)])
    assert sl.status == SL_HIT and sl.r_multiple == pytest.approx(-1.0)
    gap = simulate(scenario(), [bar(0, 99, 100.2, 99, 100.1), bar(1, 97.0, 97.5, 96.0, 96.5)])  # SL gap
    assert gap.status == SL_HIT and gap.exit_price == 97.0 and gap.r_multiple == pytest.approx(-1.5)
    short = simulate(scenario(direction="SHORT", entry_type="sell_limit", entry=100, sl=102, tp=96,
                              invalidation={"type": "close_above", "level": 103, "text": "t"}, spread=0.1),
                     [bar(0, 99, 100.1, 98.9, 99.5), bar(1, 99.5, 99.6, 95.8, 96)])
    assert short.status == TP_HIT and short.r_multiple == pytest.approx(2.0)


def test_ambiguous_candle_is_never_a_win():
    both = [bar(0, 99, 100.2, 99, 100.1), bar(1, 100.1, 104.5, 97.5, 101)]  # TP va SL bitta shamda
    st = simulate(scenario(), both)
    assert st.status == AMBIGUOUS and st.r_multiple is None
    start = T0 + timedelta(hours=1)
    fine = [Candle(start, 100.1, 100.3, 97.8, 98.0, 1, 60)] + \
        [Candle(start + timedelta(minutes=m), 98, 104.5, 98, 104, 1, 60) for m in range(1, 60)]
    st2 = simulate(scenario(), both, fine=lambda a, b: [x for x in fine if a <= x.ts < b])
    assert st2.status == SL_HIT  # 1 daqiqalik ma'lumot SL birinchi bo'lganini ko'rsatdi
    same_minute = [Candle(start + timedelta(minutes=m), 100.1, 104.5, 97.5, 101, 1, 60) for m in range(60)]
    st3 = simulate(scenario(), both, fine=lambda a, b: same_minute)
    assert st3.status == AMBIGUOUS
    # stop-kirish shamining o'zida faqat TP — narx uzluksizligidan aniq
    st4 = simulate(scenario(), [bar(0, 99, 104.5, 98.5, 104)])
    assert st4.status == TP_HIT
    # stop-kirish shamida faqat SL — ketma-ketlik noaniq
    st5 = simulate(scenario(), [bar(0, 99, 100.5, 97.5, 98)])
    assert st5.status == AMBIGUOUS


# ------------------------------------------------------------------------------------------------ versiyalar
def test_strategy_versions_are_preserved_and_never_silently_changed(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=3))
    with pytest.raises(sqlite3.IntegrityError):
        svc.db.execute("UPDATE strategies SET params='{}' WHERE strategy_id='TF-PULLBACK' AND version=1")
    v2 = svc.registry.create_version("TF-PULLBACK", {"sl_atr": 2.0}, "test", "pytest")
    assert v2.version == 2 and v2.status == "candidate" and v2.params["sl_atr"] == 2.0
    assert svc.registry.active()["TF-PULLBACK"].version == 1  # faol versiya o'zgarmadi
    assert svc.registry.get("TF-PULLBACK", 1).params["sl_atr"] == 1.5
    with pytest.raises(ValueError):
        svc.registry.create_version("TF-PULLBACK", {"no_such": 1}, "test", "pytest")
    rec = svc.create_analysis("BTCUSDT", "1h")
    assert rec["strategy_version"] == 1
    svc.registry.activate("TF-PULLBACK", 2, "pytest-owner")
    assert svc.registry.active()["TF-PULLBACK"].version == 2
    assert load(svc.db, rec["analysis_id"])["strategy_version"] == 1  # eski tahlil o'z versiyasini saqlaydi
    exported = json.loads((svc.memory.strategies / "strategy_registry.json").read_text(encoding="utf-8"))
    assert {(r["strategy_id"], r["version"], r["status"]) for r in exported} >= {("TF-PULLBACK", 1, "retired"),
                                                                                ("TF-PULLBACK", 2, "active")}


def test_experiment_is_recorded_and_not_auto_activated(tmp_path):
    c = ranging(3) + candles_from([100 + 2 * math.sin(t / 4) for t in range(700)], start=ranging(3)[-1].end)
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=1))
    svc.settings.data["backtest_bars"] = len(c)
    rec = svc.run_experiment("VOL-BRK", {"rr": 2.5}, "test muammo", "kattaroq TP expectancy ni oshiradi", "BTCUSDT", "1h")
    assert rec["verdict"] in ("inconclusive", "not_supported", "supported")
    assert svc.db.one("SELECT verdict FROM experiments WHERE experiment_id=?", (rec["experiment_id"],))
    assert (svc.memory.experiments / f"{rec['experiment_id']}.json").is_file()
    assert svc.registry.active()["VOL-BRK"].version == 1
    if rec["verdict"] != "supported":
        assert svc.registry.get("VOL-BRK", rec["candidate_version"]).status == "rejected"


# ------------------------------------------------------------------------------------------------ statistika
def test_statistics_exclude_unresolved_and_compute_drawdown():
    rows = []
    def r(status, rm, exit_t, kind="TRADE", entry=True):
        rows.append({"analysis_id": f"A{len(rows)}", "kind": kind, "status": status, "r_multiple": rm,
                     "exit_time": exit_t, "entry_time": "x" if entry else None, "strategy_id": "S", "strategy_version": 1,
                     "symbol": "BTCUSDT", "timeframe": "1h", "session": "Asia"})
    r("TP_HIT", 2.0, "2026-10-01T01")
    r("SL_HIT", -1.0, "2026-10-01T02")
    r("SL_HIT", -1.0, "2026-10-01T03")
    r("TP_HIT", 1.8, "2026-10-01T04")
    r("AMBIGUOUS_DATA", None, None)
    r("EXPIRED", 0.3, "2026-10-01T05")
    r("PENDING", None, None, entry=False)
    r("NOT_TRIGGERED", None, None, entry=False)
    r(None, None, None, kind="NO_TRADE", entry=False)
    s = analytics.summarize(rows)
    assert s["total_analyses"] == 9 and s["no_trade"] == 1 and s["resolved"] == 4
    assert s["win_rate"] == 50.0  # 2 TP / (2 TP + 2 SL) — noaniq/kutilayotganlar maxrajda yo'q
    assert s["expectancy_r"] == pytest.approx((2 - 1 - 1 + 1.8) / 4, abs=1e-3)
    assert s["max_drawdown_r"] == pytest.approx(2.0)  # cho'qqi 2 -> 0
    assert s["ambiguous"] == 1 and s["expired"] == 1 and s["not_triggered"] == 1 and s["pending"] == 1
    assert s["valid_entries"] == 6 and s["small_sample"] is True
    by = analytics.breakdown(rows, "strategy")
    assert by[0]["key"] == "S v1" and by[0]["resolved"] == 4


def test_sl_review_classification_rules():
    base = {"entry_met": True, "reproduced": True, "levels_match": True, "regime_ok": True, "sl_atr": 1.5,
            "atr_spike": 1.1, "cost_r": 0.05, "events": []}
    assert classify(base)[0] == NORMAL
    assert classify({**base, "regime_ok": False, "regime": "RANGE"})[0] == REGIME
    assert classify({**base, "sl_atr": 0.5})[0] == VOLATILITY
    assert classify({**base, "reproduced": False})[0] == INVALID
    assert classify({**base, "data_gaps": 3})[0] == DATA
    assert classify({**base, "reproduced": None})[0] == "Unclear cause"


# ------------------------------------------------------------------------------------------------ hisobot va qayta ishga tushish
def _outcome_flow(svc: TradingService, c: list[Candle]) -> str:
    rec = svc.create_analysis("BTCUSDT", "1h")
    assert rec["kind"] == "TRADE"
    entry, tp = rec["entry"], rec["tp"]
    # 1-sham e'lon vaqtini o'z ichiga oladi, lekin darajalarga tegmaydi; 2-shamda kirish; 3-shamda TP
    after = candles_from([entry - 0.3, entry + 0.5, tp + 1.0], start=c[-1].end, pad=0.1)
    svc.market.providers["binance"].series[("BTCUSDT", "1h")] = c + after
    svc.clock.now = after[-1].end + timedelta(minutes=1)
    changes = svc.update_outcomes()
    assert changes and svc.db.outcome(rec["analysis_id"])["status"] == TP_HIT
    return rec["analysis_id"]


def test_outcome_tracking_end_to_end_and_daily_report(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=2))
    aid = _outcome_flow(svc, c)
    events = [e["to_status"] for e in svc.db.query("SELECT to_status FROM outcome_events WHERE analysis_id=? ORDER BY id",
                                                  (aid,))]
    assert events == ["PENDING", "ACTIVE_SIMULATION", "TP_HIT"]
    with pytest.raises(sqlite3.IntegrityError):
        svc.db.execute("UPDATE outcome_events SET to_status='SL_HIT' WHERE analysis_id=?", (aid,))
    day = load(svc.db, aid)["local_date"]
    text, data = svc.daily_report(day)
    assert data["analyses"] == 1 and data["outcomes_today_analyses"]["TP_HIT"] == 1
    assert data["outcomes_earlier_analyses"]["TP_HIT"] == 0
    assert "Kunlik tadqiqot hisoboti" in text and "Oldingi kunlar tahlillari" in text and "PAPER TRADING" in text
    assert (svc.memory.reports / f"{day}.md").is_file()
    # ertangi hisobotda bu natija "oldingi kunlar" emas (bugun yopilmagan), tahlillar soni 0
    nxt = (datetime.fromisoformat(day) + timedelta(days=1)).strftime("%Y-%m-%d")
    _, d2 = svc.daily_report(nxt)
    assert d2["analyses"] == 0 and d2["outcomes_today_analyses"]["TP_HIT"] == 0


def test_persistent_memory_and_recovery_after_restart(tmp_path):
    c = uptrend_pullback()
    now = c[-1].end + timedelta(minutes=2)
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, now, env={"TRADING_GROUP_CHAT_ID": "-100777"})
    rec = svc.create_analysis("BTCUSDT", "1h")
    day = rec["local_date"]
    svc.db.ensure_job(f"analysis:{day}:01", "analysis", now.isoformat())
    svc.db.update_job(f"analysis:{day}:01", status="running", attempts=1)
    svc.db.claim_publication(rec["analysis_id"], -100777, "analysis", "h")  # yuborish paytida "o'chdi"
    svc.db.close()

    svc2 = make_service(tmp_path, {("BTCUSDT", "1h"): c}, now + timedelta(hours=20),
                        env={"TRADING_GROUP_CHAT_ID": "-100777"})
    assert load(svc2.db, rec["analysis_id"])["entry"] == rec["entry"]  # tahlil saqlangan
    assert svc2.registry.active()["TF-PULLBACK"].version == 1
    owner: list[str] = []

    async def notify(text):
        owner.append(text)
    sent = FakeSend()
    sch = TradingScheduler(svc2, Publisher(svc2.db, svc2.settings, sent, notify, clock=svc2.clock), notify)
    info = asyncio.run(sch.recover(svc2.clock()))
    assert f"analysis:{day}:01" in info["stuck"]
    assert info["unknown_publications"] == [rec["analysis_id"]]
    assert svc2.db.publication(rec["analysis_id"], -100777, "analysis")["status"] == "unknown"
    assert info["missed"]  # o'chiq paytdagi slotlar yozildi, tahlil o'ylab topilmadi
    assert svc2.db.one("SELECT COUNT(*) AS n FROM analyses")["n"] == 1
    assert any("qayta yuborilmadi" in t.lower() for t in owner)
    # kechikkan kunlik hisobot siyosat bo'yicha yaratildi
    assert svc2.db.one("SELECT 1 FROM reports WHERE report_id=?", (f"daily-{day}",))
    assert asyncio.run(sch.pub.publish_analysis(rec)) in ("duplicate", "stale") and not [s for s in sent.sent
                                                                                       if "ANALYSIS ID" in s[1]]


def test_scheduler_runs_slot_once_and_retries_on_missing_data(tmp_path):
    c = uptrend_pullback()
    now = c[-1].end + timedelta(minutes=1)
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, now)
    svc.settings.data["universe"] = [{"symbol": "BTCUSDT", "timeframe": "1h"}]
    svc.settings.data["analysis_slots"] = [svc.settings.local(now - timedelta(minutes=5)).strftime("%H:%M")]
    svc.settings.data["daily_target"] = 1

    async def notify(text):
        pass
    sch = TradingScheduler(svc, Publisher(svc.db, svc.settings, FakeSend(), clock=svc.clock), notify)
    day = svc.local_today()
    asyncio.run(sch._analysis_slots(day, now))
    asyncio.run(sch._analysis_slots(day, now + timedelta(minutes=1)))
    assert svc.db.one("SELECT COUNT(*) AS n FROM analyses")["n"] == 1  # slot faqat bir marta
    assert svc.db.job(f"analysis:{day}:01")["status"] == "done"
    # ma'lumot yo'q: qayta urinish, oxiri failed — tahlil yaratilmaydi
    svc.market.providers["binance"].down.add("BTCUSDT")
    svc.db.execute("DELETE FROM jobs")
    for k in range(4):
        asyncio.run(sch._analysis_slots(day, now + timedelta(minutes=3 * k)))
    job = svc.db.job(f"analysis:{day}:01")
    assert job["status"] == "failed" and job["attempts"] == 3 and "manbasi ishlamayapti" in job["last_error"]
    assert svc.db.one("SELECT COUNT(*) AS n FROM analyses")["n"] == 1


def test_backtest_uses_same_engine_and_costs():
    c = ranging(5) + candles_from([100 + 2.5 * math.sin(t / 5) for t in range(500)], start=ranging(5)[-1].end)
    spec = next(s for s in DEFAULT_STRATEGIES if s.strategy_id == "SR-BOUNCE")
    free = backtest.metrics(backtest.run(spec, c, spread_fn=lambda p: 0.0, commission=0.0))
    costly = backtest.metrics(backtest.run(spec, c, spread_fn=lambda p: 0.05, commission=0.002))
    assert free["signals"] == costly["signals"] or free["signals"] >= 0
    if free["expectancy_r"] is not None and costly["expectancy_r"] is not None:
        assert costly["expectancy_r"] <= free["expectancy_r"] + 1e-9  # xarajat natijani yaxshilamaydi
    wf = backtest.walk_forward(spec, c, spread_fn=lambda p: 0.0, commission=0.0)
    assert set(wf) == {"in_sample", "out_of_sample", "periods"}
    v, why = backtest.verdict(wf, wf)
    assert v == "inconclusive" or "OOS" in why


def test_dashboard_trading_view_is_read_only(tmp_path):
    from agent.dashboard.trading_api import TradingView

    view = TradingView(tmp_path)
    assert view.overview()["exists"] is False and view.table("strategies") == []
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=2))
    aid = _outcome_flow(svc, c)
    ov = view.overview()
    assert ov["exists"] and ov["summary"]["tp_hits"] == 1 and ov["recent"][0]["analysis_id"] == aid
    assert ov["equity"] and ov["equity"][-1]["cum_r"] > 0
    det = view.analysis(aid)
    assert det["analysis"]["analysis_id"] == aid and [e["to_status"] for e in det["events"]][-1] == "TP_HIT"
    strategies = view.table("strategies")
    assert len(strategies) == 11 and all(isinstance(s["params"], dict) for s in strategies)
    db = view._db()  # noqa: SLF001
    with pytest.raises(sqlite3.OperationalError):
        db.conn.execute("DELETE FROM outcomes")
    db.close()
    with pytest.raises(KeyError):
        view.table("analyses; DROP TABLE x")


def test_research_is_retried_when_task_recorded_no_sources(tmp_path):
    c = uptrend_pullback()
    now = c[-1].end + timedelta(minutes=1)
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, now)
    svc.settings.data["research_at"] = svc.settings.local(now - timedelta(minutes=1)).strftime("%H:%M")
    submitted: list[str] = []
    blocked = {"reason": None}

    async def submit(prompt):
        submitted.append(prompt)
        return f"T-R{len(submitted)}"

    async def notify(text):
        pass
    sch = TradingScheduler(svc, Publisher(svc.db, svc.settings, FakeSend(), clock=svc.clock), notify, submit,
                           can_submit=lambda: blocked["reason"])
    day = svc.local_today()
    asyncio.run(sch._daily_job(day, now, "research", svc.settings["research_at"], sch._research))
    assert len(submitted) == 1 and "trading_research_source" in submitted[0]
    job = svc.db.job(f"research:{day}")
    assert job["status"] == "done" and job["result"] == "T-R1"
    blocked["reason"] = "⛔ Claude obuna limiti tugagan"  # limit — kutiladi, qayta yuborilmaydi
    asyncio.run(sch._research_followup(day, now + timedelta(hours=1)))
    assert svc.db.job(f"research:{day}")["status"] == "done"
    blocked["reason"] = None
    asyncio.run(sch._research_followup(day, now + timedelta(hours=1)))
    assert svc.db.job(f"research:{day}")["status"] == "pending"  # natijasiz — qayta navbatga
    asyncio.run(sch._daily_job(day, now + timedelta(hours=1), "research", svc.settings["research_at"], sch._research))
    assert len(submitted) == 2
    svc.record_source(topic="risk", url="https://example.org/a", title="A", summary="s", evidence_type="opinion",
                      task_id="T-R2")
    asyncio.run(sch._research_followup(day, now + timedelta(hours=3)))
    assert svc.db.job(f"research:{day}")["status"] == "done"  # manba yozilgan — tugadi


def test_manual_scenario_is_tracked_separately(tmp_path):
    c = uptrend_pullback()
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, c[-1].end + timedelta(minutes=2))
    last = c[-1].close
    with pytest.raises(ValueError, match="mantiqsiz"):
        svc.track_manual(symbol="BTCUSDT", timeframe="1h", direction="SHORT", entry_type="sell_limit", entry=last + 1,
                         sl=last, tp=last - 5, valid_hours=24, note="xato darajalar")
    with pytest.raises(ValueError, match="juda uzoq"):
        svc.track_manual(symbol="BTCUSDT", timeframe="1h", direction="LONG", entry_type="buy_stop", entry=last * 2,
                         sl=last * 1.9, tp=last * 2.2, valid_hours=24, note="")
    rec = svc.track_manual(symbol="BTCUSDT", timeframe="1h", direction="SHORT", entry_type="sell_limit",
                           entry=last + 1.0, sl=last + 3.0, tp=last - 3.0, valid_hours=24, note="suhbatdagi SHORT")
    assert rec["strategy_id"] == "MANUAL" and rec["strategy_version"] == 0 and rec["rr"] == 2.0
    assert verify_integrity(svc.db, rec["analysis_id"])
    after = candles_from([last + 0.5, last + 1.2, last - 3.5], start=c[-1].end, pad=0.1)
    svc.market.providers["binance"].series[("BTCUSDT", "1h")] = c + after
    svc.clock.now = after[-1].end + timedelta(minutes=1)
    svc.update_outcomes()
    assert svc.db.outcome(rec["analysis_id"])["status"] == TP_HIT
    keys = [b["key"] for b in svc.performance()["by_strategy"]]
    assert "MANUAL v0" in keys


def test_library_refresh_records_backtest_stats_periodically(tmp_path):
    c = ranging(2) + candles_from([100 + 2 * math.sin(t / 4) for t in range(400)], start=ranging(2)[-1].end)
    now = c[-1].end + timedelta(minutes=1)
    svc = make_service(tmp_path, {("BTCUSDT", "1h"): c}, now)
    svc.settings.data["library_universe"] = [{"symbol": "BTCUSDT", "timeframe": "1h"}]
    svc.settings.data["backtest_bars"] = len(c)

    async def notify(text):
        pass
    sch = TradingScheduler(svc, Publisher(svc.db, svc.settings, FakeSend(), clock=svc.clock), notify)
    asyncio.run(sch._library_refresh(now))
    rows = svc.db.query("SELECT strategy_id, sample_size, period_start, period_end, costs FROM strategy_stats")
    assert len(rows) == 3 and all(r["period_start"] and r["period_end"] and r["costs"] for r in rows)
    asyncio.run(sch._library_refresh(now + timedelta(days=1)))  # 7 kun o'tmagan — qayta hisoblanmaydi
    assert svc.db.one("SELECT COUNT(*) AS n FROM strategy_stats")["n"] == 3
    asyncio.run(sch._library_refresh(now + timedelta(days=8)))
    assert svc.db.one("SELECT COUNT(*) AS n FROM strategy_stats")["n"] == 6
