"""V21 tadqiqot laboratoriyasi: strategiyalarni 5 yillik tarixda sinash (faqat tarixiy ma'lumot, savdo YO'Q).

Mavjud V16 dvigatellari ishlatiladi (strategies.ENGINES, outcomes.simulate): look-ahead yo'q, kirish i+1 dan. Bu fayl
backtest.run ning nusxasi, farqi — har savdoga teg yopishtiriladi (rejim, H4 yo'nalishi, sessiya, soat), shunda zarar
qayerdan kelayotgani ko'rinadi. Mavjud kod o'zgartirilmaydi.
"""
from __future__ import annotations

import bisect
import csv
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.trading.data import TF_SECONDS, Candle  # noqa: E402
from agent.trading.indicators import Features  # noqa: E402
from agent.trading.outcomes import AMBIGUOUS, EXPIRED, FINAL, SL_HIT, TP_HIT, Scenario, simulate  # noqa: E402
from agent.trading.strategies import DEFAULT_STRATEGIES, NoSetup, classify_regime  # noqa: E402

HIST = ROOT / "data" / "trading_memory" / "history"
STRATEGIES = {s.strategy_id: s for s in DEFAULT_STRATEGIES}
TF_NAME = {900: "15m", 3600: "1h", 14400: "4h", 86400: "1d"}


def load(symbol: str, tf: str) -> list[Candle]:
    sec = TF_SECONDS[tf]
    out = []
    with open(HIST / f"{symbol}_{tf}.csv", newline="") as f:
        for r in csv.DictReader(f):
            out.append(Candle(datetime.fromisoformat(r["ts"]), float(r["open"]), float(r["high"]), float(r["low"]),
                              float(r["close"]), float(r["volume"]), sec))
    return out


def session(dt: datetime) -> str:
    h = dt.astimezone(timezone.utc).hour
    if 7 <= h < 12:
        return "London"
    if 12 <= h < 16:
        return "Overlap"
    if 16 <= h < 21:
        return "NewYork"
    return "Asia/Off"


class HTF:
    """Yuqori taymfreym (H4) yo'nalishi: signal vaqtigacha YOPILGAN oxirgi H4 shami bo'yicha."""

    def __init__(self, candles: list[Candle]):
        self.f = Features.build(candles)
        self.ends = [c.end for c in candles]

    def trend(self, t: datetime) -> str:
        k = bisect.bisect_right(self.ends, t) - 1  # t gacha yopilgan oxirgi sham
        if k < 210:
            return "NA"
        try:
            return classify_regime(self.f, k).trend
        except ValueError:
            return "NA"


@dataclass
class Trade:
    ts: datetime
    direction: str
    status: str
    r: float | None
    regime: str = ""
    htf: str = ""  # ALIGNED | CONFLICT | NEUTRAL | NA
    session: str = ""
    hour: int = 0
    risk_pct: float = 0.0  # SL masofasi, narxning %
    extra: dict = field(default_factory=dict)


def spread_price(spec: dict, price: float, mult: float) -> float:
    return (spec["spread"] if "spread" in spec else price * spec["spread_bps"] / 1e4) * mult


def run_tagged(spec, candles: list[Candle], htf: HTF | None, cost: dict, *, mult: float = 1.0, start: int = 220,
               end: int | None = None, max_hold: int = 48) -> list[Trade]:
    f = Features.build(candles)
    end = len(candles) - 1 if end is None else end
    sec = candles[0].seconds
    trades: list[Trade] = []
    i = max(start, 220)
    while i < end:
        try:
            regime = classify_regime(f, i)
        except ValueError:
            i += 1
            continue
        res = spec.evaluate(f, i, regime)
        if isinstance(res, NoSetup):
            i += 1
            continue
        data_end = candles[i].end
        sc = Scenario("LAB", res.direction, res.entry_type, res.entry, res.sl, res.tp, res.invalidation, data_end,
                      data_end, data_end + timedelta(seconds=sec * res.valid_bars), max_hold, TF_NAME[sec],
                      spread_price(cost, res.entry, mult), cost.get("commission", 0.0))
        future = candles[i + 1:min(end, i + 2 + res.valid_bars + max_hold) + 1]
        st = simulate(sc, future)
        if st.status not in FINAL:
            break
        ht = "NA"
        if htf is not None:
            t = htf.trend(data_end)
            ht = "NA" if t == "NA" else ("NEUTRAL" if t in ("RANGE", "TRANSITION") else
                                         "ALIGNED" if (t == "TREND_UP") == (res.direction == "LONG") else "CONFLICT")
        trades.append(Trade(candles[i].ts, res.direction, st.status, st.r_multiple, regime.trend, ht,
                            session(candles[i].ts), candles[i].ts.hour, abs(res.entry - res.sl) / res.entry * 100))
        close_ts = st.exit_time or (st.events[-1]["ts"] if st.events else data_end)
        j = i + 1
        while j < end and candles[j].ts < close_ts:
            j += 1
        i = max(j, i + 1)
    return trades


def executed(trades: list[Trade]) -> list[Trade]:
    """Haqiqatan pozitsiya ochilib yopilganlar (TP, SL, muddat tugashi). AMBIGUOUS va NOT_TRIGGERED — hisobda yo'q."""
    return [t for t in trades if t.status in (TP_HIT, SL_HIT, EXPIRED) and t.r is not None]


def stats(trades: list[Trade]) -> dict:
    ex = executed(trades)
    n = len(ex)
    rs = [t.r for t in ex]
    out = {"signals": len(trades), "n": n, "ambiguous": sum(t.status == AMBIGUOUS for t in trades),
           "not_triggered": sum(t.status not in (TP_HIT, SL_HIT, EXPIRED, AMBIGUOUS) for t in trades)}
    if n == 0:
        return {**out, "win_rate": None, "expectancy": None, "pf": None, "avg_win": None, "avg_loss": None, "maxdd": 0.0,
                "ci_lo": None, "ci_hi": None, "total_r": 0.0}
    wins = [r for r in rs if r > 0]
    losses = [-r for r in rs if r <= 0]
    mean = sum(rs) / n
    sd = math.sqrt(sum((r - mean) ** 2 for r in rs) / (n - 1)) if n > 1 else 0.0
    half = 1.96 * sd / math.sqrt(n) if n > 1 else float("nan")
    curve = peak = dd = 0.0
    for r in rs:
        curve += r
        peak = max(peak, curve)
        dd = max(dd, peak - curve)
    return {**out, "win_rate": round(len(wins) / n * 100, 1), "expectancy": round(mean, 3),
            "pf": round(sum(wins) / sum(losses), 2) if losses and sum(losses) else None,
            "avg_win": round(sum(wins) / len(wins), 2) if wins else None,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else None, "maxdd": round(dd, 2),
            "ci_lo": round(mean - half, 3), "ci_hi": round(mean + half, 3), "total_r": round(sum(rs), 1)}
