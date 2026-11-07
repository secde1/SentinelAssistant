"""V23 nomzod strategiyalar: likvidlik tortishi, trend chizig'i (bounce/break), SNR rad etish. Aniq qurilgan sham
qatorlari bilan (swing nuqtalari qo'lda beriladi) — qoidalar, darajalar, bekor qilish, 'candidate' holati."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from agent.trading.data import Candle
from agent.trading.indicators import Features
from agent.trading.strategies import (DEFAULT_STRATEGIES, ENGINES, PRIORITY, NoSetup, Regime, Registry, Setup,
                                      candidates)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SPEC = {s.strategy_id: s for s in DEFAULT_STRATEGIES}
REGIME = Regime("TRANSITION", "NORMAL", {})


class F:
    """Features o'rnini bosuvchi: faqat engine'lar ishlatadigan maydonlar; swing nuqtalari qo'lda beriladi."""

    def __init__(self, n, close, hi, lo, atr=1.0, highs=(), lows=()):
        self.candles = [Candle(T0 + timedelta(hours=k), close(k), hi(k), lo(k), close(k), 100.0, 3600) for k in range(n)]
        self.close = [c.close for c in self.candles]
        self.high = [c.high for c in self.candles]
        self.low = [c.low for c in self.candles]
        self.atr14 = [atr] * n
        self.rsi14 = [50.0] * n
        self._h, self._l = list(highs), list(lows)

    def __len__(self):
        return len(self.candles)

    def swings(self, i, lookback=100):
        return ([p for p in self._h if p[0] >= i - lookback], [p for p in self._l if p[0] >= i - lookback])

    def set_last(self, o, h, lo, c):
        self.candles[-1] = Candle(self.candles[-1].ts, o, h, lo, c, 100.0, 3600)
        self.close[-1], self.high[-1], self.low[-1] = c, h, lo


def ev(sid, f):
    return SPEC[sid].evaluate(f, len(f) - 1, REGIME)


# ------------------------------------------------------------------------------------------------ holat va ro'yxat
def test_new_strategies_are_candidates_not_active(tmp_path):
    from agent.trading.db import TradingDB
    reg = Registry(TradingDB(tmp_path / "t.db"))
    reg.sync_defaults()
    new = {"LIQ-SWEEP", "TL-BOUNCE", "TL-BREAK", "SNR-REJ"}
    rows = {r["strategy_id"]: r["status"] for r in reg.all()}
    assert all(rows[s] == "candidate" for s in new)  # signal generatsiyasiga kirmaydi
    assert set(reg.active()) == {"TF-PULLBACK", "MA-CROSS", "VOL-BRK"}
    assert new <= set(ENGINES) and all(s in PRIORITY["RANGE"] for s in new)
    assert new.isdisjoint({c.strategy_id for c in candidates(REGIME, reg.active())})


# ------------------------------------------------------------------------------------------------ LIQ-SWEEP
def sweep_base(n=300):
    return F(n, close=lambda k: 100.0, hi=lambda k: 100.5, lo=lambda k: 99.5, atr=1.0,
             highs=[(250, 105.0)], lows=[(250, 95.0)])


def test_liq_sweep_short_after_stop_hunt_above_swing_high():
    f = sweep_base()
    f.set_last(o=103.5, h=105.5, lo=102.5, c=103.0)  # 105 dan yuqori soya, ichkarida bearish yopilish
    r = ev("LIQ-SWEEP", f)
    assert isinstance(r, Setup) and r.direction == "SHORT" and r.entry_type == "sell_stop"
    assert r.entry == pytest.approx(102.4) and r.sl == pytest.approx(105.7) and r.rr == pytest.approx(2.0, abs=0.01)
    assert r.evidence["swept_high"] == 105.0 and r.invalidation["type"] == "close_above"


def test_liq_sweep_long_after_stop_hunt_below_swing_low():
    f = sweep_base()
    f.set_last(o=96.5, h=97.5, lo=94.5, c=97.0)
    r = ev("LIQ-SWEEP", f)
    assert isinstance(r, Setup) and r.direction == "LONG" and r.entry_type == "buy_stop"
    assert r.sl == pytest.approx(94.3) and r.entry == pytest.approx(97.6)


@pytest.mark.parametrize("last,why", [
    ((106.0, 108.0, 105.5, 107.5), "haqiqiy buzilish: yopilish daraja ustida"),
    ((103.5, 104.9, 102.5, 103.0), "daraja tegilmadi"),
    ((103.0, 105.5, 102.5, 105.2), "bullish yopilish (rad etish yo'q)"),
    ((103.5, 108.0, 102.5, 103.0), "juda chuqur buzilish (>1.5 ATR)")])
def test_liq_sweep_rejects_non_sweeps(last, why):
    f = sweep_base()
    f.set_last(*last)
    assert isinstance(ev("LIQ-SWEEP", f), NoSetup), why


def test_liq_sweep_ignores_pool_already_taken_out_earlier():
    f = F(300, close=lambda k: 100.0, hi=lambda k: 106.0 if k == 270 else 100.5, lo=lambda k: 99.5, atr=1.0,
          highs=[(250, 105.0)], lows=[])
    f.set_last(o=103.5, h=105.5, lo=102.5, c=103.0)
    assert isinstance(ev("LIQ-SWEEP", f), NoSetup)  # 105 darajasi 270-shamda allaqachon buzilgan


# ------------------------------------------------------------------------------------------------ trend chizig'i
def tl_frame(close_fn=None, lows=((60, 86.0), (100, 90.0), (140, 94.0)), n=200):
    def line(j):
        return 90.0 + 0.1 * (j - 100)
    f = F(n, close=close_fn(line) if close_fn else (lambda k: line(k) + 2.0), hi=lambda k: line(k) + 2.5,
          lo=lambda k: line(k) + 1.5, atr=1.0, lows=list(lows))
    return f, line


def test_tl_bounce_long_from_rising_trend_line():
    f, line = tl_frame()
    L = line(199)
    f.set_last(o=L + 0.6, h=L + 1.6, lo=L + 0.1, c=L + 1.3)  # chiziqqa tegib, ustida yopilgan bullish sham
    r = ev("TL-BOUNCE", f)
    assert isinstance(r, Setup) and r.direction == "LONG" and r.entry_type == "buy_stop"
    assert r.entry == pytest.approx(L + 1.7) and r.sl == pytest.approx(L - 1.0) and r.evidence["touches"] == 3


def test_tl_bounce_short_from_falling_trend_line():
    def line(j):
        return 110.0 - 0.1 * (j - 100)
    f = F(200, close=lambda k: line(k) - 2.0, hi=lambda k: line(k) - 1.5, lo=lambda k: line(k) - 2.5, atr=1.0,
          highs=[(60, 114.0), (100, 110.0), (140, 106.0)])
    L = line(199)
    f.set_last(o=L - 0.6, h=L - 0.1, lo=L - 1.6, c=L - 1.3)
    r = ev("TL-BOUNCE", f)
    assert isinstance(r, Setup) and r.direction == "SHORT" and r.sl == pytest.approx(L + 1.0)


def test_tl_bounce_requires_touch_third_point_and_intact_line():
    f, line = tl_frame()
    L = line(199)
    f.set_last(o=L + 3, h=L + 4, lo=L + 2.5, c=L + 3.5)  # chiziqdan uzoqda — teginish yo'q
    assert isinstance(ev("TL-BOUNCE", f), NoSetup)
    f2, _ = tl_frame(lows=((100, 90.0), (140, 94.0)))  # uchinchi teginish yo'q
    f2.set_last(o=L + 0.6, h=L + 1.6, lo=L + 0.1, c=L + 1.3)
    assert isinstance(ev("TL-BOUNCE", f2), NoSetup)
    # 170-shamda chiziq yopilish bilan buzilgan
    f3, _ = tl_frame(close_fn=lambda line: (lambda k: line(k) + (-1.0 if k == 170 else 2.0)))
    f3.set_last(o=L + 0.6, h=L + 1.6, lo=L + 0.1, c=L + 1.3)
    assert isinstance(ev("TL-BOUNCE", f3), NoSetup)


def test_tl_break_short_when_rising_line_breaks_on_close():
    f, line = tl_frame()
    L = line(199)
    f.set_last(o=L + 0.5, h=L + 0.8, lo=L - 1.8, c=L - 1.0)  # yopilish chiziqdan 0.3 ATR dan ortiq pastda
    r = ev("TL-BREAK", f)
    assert isinstance(r, Setup) and r.direction == "SHORT" and r.entry_type == "sell_stop"
    assert r.entry == pytest.approx(L - 1.9) and r.sl == pytest.approx(L + 1.0)  # max(high, chiziq)+0.2
    assert isinstance(ev("TL-BOUNCE", f), NoSetup)  # bu qaytish emas


def test_tl_break_needs_decisive_close_not_just_wick():
    f, line = tl_frame()
    L = line(199)
    f.set_last(o=L + 0.5, h=L + 0.8, lo=L - 1.8, c=L + 0.1)  # soya chiziqdan pastda, lekin yopilish ustida
    assert isinstance(ev("TL-BREAK", f), NoSetup)


def test_flat_line_is_not_a_trend_line():
    f, _ = tl_frame(lows=((60, 90.0), (100, 90.0), (140, 90.0)))
    assert isinstance(ev("TL-BOUNCE", f), NoSetup) and isinstance(ev("TL-BREAK", f), NoSetup)


# ------------------------------------------------------------------------------------------------ SNR
def snr_frame():
    return F(260, close=lambda k: 103.0, hi=lambda k: 103.5, lo=lambda k: 102.5, atr=1.0,
             lows=[(70, 100.1), (120, 99.9), (170, 100.0)], highs=[(80, 110.0), (130, 110.2), (180, 109.9)])


def test_snr_long_rejection_at_support_zone():
    f = snr_frame()
    f.set_last(o=100.8, h=101.1, lo=99.9, c=101.0)
    r = ev("SNR-REJ", f)
    assert isinstance(r, Setup) and r.direction == "LONG" and r.entry == pytest.approx(101.2)
    assert r.sl == pytest.approx(99.4) and r.evidence["level"] == pytest.approx(100.0, abs=0.1)


def test_snr_short_rejection_at_resistance_zone():
    f = snr_frame()
    f.set_last(o=109.2, h=110.1, lo=108.9, c=109.0)
    r = ev("SNR-REJ", f)
    assert isinstance(r, Setup) and r.direction == "SHORT" and r.entry_type == "sell_stop"


def test_snr_needs_three_touches_and_a_real_rejection_candle():
    f = snr_frame()
    f.set_last(o=100.4, h=101.3, lo=100.3, c=101.0)  # zona ichida, lekin pastki soya yo'q (marubozu)
    assert isinstance(ev("SNR-REJ", f), NoSetup)
    two = F(260, close=lambda k: 103.0, hi=lambda k: 103.5, lo=lambda k: 102.5, atr=1.0, lows=[(70, 100.1), (120, 99.9)])
    two.set_last(o=100.8, h=101.1, lo=99.9, c=101.0)
    assert isinstance(ev("SNR-REJ", two), NoSetup)  # faqat 2 teginish
    f2 = snr_frame()
    f2.set_last(o=100.8, h=101.1, lo=99.9, c=99.7)  # daraja ostida yopilgan — rad etish emas
    assert isinstance(ev("SNR-REJ", f2), NoSetup)


# ------------------------------------------------------------------------------------------------ haqiqiy Features bilan
def test_engines_run_on_real_features_without_lookahead():
    closes = [100 + 6 * math.sin(t / 7) + 0.05 * t for t in range(400)]
    cs = []
    for k, c in enumerate(closes):
        o = closes[k - 1] if k else closes[0]
        cs.append(Candle(T0 + timedelta(hours=k), o, max(o, c) + 0.4, min(o, c) - 0.4, c, 100.0, 3600))
    full = Features.build(cs)
    for sid in ("LIQ-SWEEP", "TL-BOUNCE", "TL-BREAK", "SNR-REJ"):
        for i in range(260, 400, 7):
            cut = Features.build(cs[:i + 1])  # kelajak ma'lumotisiz
            a, b = SPEC[sid].evaluate(full, i, REGIME), SPEC[sid].evaluate(cut, i, REGIME)
            assert type(a) is type(b)
            if isinstance(a, Setup):
                assert (a.direction, a.entry, a.sl, a.tp) == (b.direction, b.entry, b.sl, b.tp)  # i dan keyingi shamlar ta'sir qilmaydi
