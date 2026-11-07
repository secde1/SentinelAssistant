"""Indikatorlar — faqat o'tmishga tayanadigan (causal) seriyalar: i-qiymat faqat 0..i shamlardan hisoblanadi.

Shu sabab backtestda butun seriyani bir marta hisoblab, i-indeksda baholash look-ahead bermaydi. Swing (fraktal)
nuqtalari o'ng tomondan `k` sham bilan tasdiqlanadi: j-nuqta faqat i >= j + k bo'lganda ma'lum.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .data import Candle

NaN = float("nan")


def sma(values: list[float], n: int) -> list[float]:
    out, s = [], 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else NaN)
    return out


def ema(values: list[float], n: int) -> list[float]:
    out: list[float] = []
    k = 2 / (n + 1)
    prev = NaN
    for i, v in enumerate(values):
        if i < n - 1:
            out.append(NaN)
            continue
        if i == n - 1:
            prev = sum(values[:n]) / n
        else:
            prev = v * k + prev * (1 - k)
        out.append(prev)
    return out


def rsi(closes: list[float], n: int = 14) -> list[float]:
    out = [NaN] * len(closes)
    if len(closes) <= n:
        return out
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    avg_g, avg_l = gains / n, losses / n
    out[n] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_g = (avg_g * (n - 1) + max(d, 0)) / n
        avg_l = (avg_l * (n - 1) + max(-d, 0)) / n
        out[i] = 100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l)
    return out


def true_range(c: list[Candle]) -> list[float]:
    out = []
    for i, x in enumerate(c):
        if i == 0:
            out.append(x.high - x.low)
        else:
            pc = c[i - 1].close
            out.append(max(x.high - x.low, abs(x.high - pc), abs(x.low - pc)))
    return out


def wilder(values: list[float], n: int) -> list[float]:
    out = [NaN] * len(values)
    if len(values) < n:
        return out
    prev = sum(values[:n]) / n
    out[n - 1] = prev
    for i in range(n, len(values)):
        prev = (prev * (n - 1) + values[i]) / n
        out[i] = prev
    return out


def atr(c: list[Candle], n: int = 14) -> list[float]:
    return wilder(true_range(c), n)


def adx(c: list[Candle], n: int = 14) -> list[float]:
    plus, minus = [0.0], [0.0]
    for i in range(1, len(c)):
        up = c[i].high - c[i - 1].high
        down = c[i - 1].low - c[i].low
        plus.append(up if up > down and up > 0 else 0.0)
        minus.append(down if down > up and down > 0 else 0.0)
    tr_s = wilder(true_range(c), n)
    p_s, m_s = wilder(plus, n), wilder(minus, n)
    dx = []
    for t, p, m in zip(tr_s, p_s, m_s):
        if any(math.isnan(x) for x in (t, p, m)) or t == 0:
            dx.append(NaN)
            continue
        pdi, mdi = 100 * p / t, 100 * m / t
        dx.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    out = [NaN] * len(dx)
    valid = [i for i, v in enumerate(dx) if not math.isnan(v)]
    if len(valid) < n:
        return out
    start = valid[0]
    prev = sum(dx[start:start + n]) / n
    out[start + n - 1] = prev
    for i in range(start + n, len(dx)):
        prev = (prev * (n - 1) + dx[i]) / n
        out[i] = prev
    return out


def stdev(values: list[float], n: int) -> list[float]:
    out = []
    for i in range(len(values)):
        if i < n - 1:
            out.append(NaN)
            continue
        w = values[i - n + 1:i + 1]
        m = sum(w) / n
        out.append(math.sqrt(sum((x - m) ** 2 for x in w) / n))
    return out


def percentile_rank(values: list[float], i: int, lookback: int) -> float:
    w = [v for v in values[max(0, i - lookback + 1):i + 1] if not math.isnan(v)]
    if len(w) < 10 or math.isnan(values[i]):
        return NaN
    return 100.0 * sum(1 for v in w if v <= values[i]) / len(w)


@dataclass
class Features:
    """Bir marta hisoblanadigan seriyalar (live tahlil va backtest bir xil kodni ishlatadi)."""

    candles: list[Candle]
    close: list[float] = field(default_factory=list)
    high: list[float] = field(default_factory=list)
    low: list[float] = field(default_factory=list)
    ema9: list[float] = field(default_factory=list)
    ema20: list[float] = field(default_factory=list)
    ema21: list[float] = field(default_factory=list)
    ema50: list[float] = field(default_factory=list)
    ema200: list[float] = field(default_factory=list)
    sma20: list[float] = field(default_factory=list)
    rsi14: list[float] = field(default_factory=list)
    atr14: list[float] = field(default_factory=list)
    adx14: list[float] = field(default_factory=list)
    bb_width: list[float] = field(default_factory=list)
    bb_upper: list[float] = field(default_factory=list)
    bb_lower: list[float] = field(default_factory=list)
    atr_pct: list[float] = field(default_factory=list)
    swing_k: int = 3

    @classmethod
    def build(cls, candles: list[Candle]) -> "Features":
        f = cls(candles)
        f.close = [c.close for c in candles]
        f.high = [c.high for c in candles]
        f.low = [c.low for c in candles]
        f.ema9, f.ema20, f.ema21 = ema(f.close, 9), ema(f.close, 20), ema(f.close, 21)
        f.ema50, f.ema200 = ema(f.close, 50), ema(f.close, 200)
        f.sma20 = sma(f.close, 20)
        f.rsi14 = rsi(f.close, 14)
        f.atr14 = atr(candles, 14)
        f.adx14 = adx(candles, 14)
        sd = stdev(f.close, 20)
        f.bb_upper = [m + 2 * s if not math.isnan(m) else NaN for m, s in zip(f.sma20, sd)]
        f.bb_lower = [m - 2 * s if not math.isnan(m) else NaN for m, s in zip(f.sma20, sd)]
        f.atr_pct = [a / c * 100 if not math.isnan(a) and c else NaN for a, c in zip(f.atr14, f.close)]
        f.bb_width = [(u - lo) / m if not math.isnan(m) and m else NaN for u, lo, m in zip(f.bb_upper, f.bb_lower, f.sma20)]
        return f

    def __len__(self) -> int:
        return len(self.candles)

    def swings(self, i: int, lookback: int = 100) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
        """i-shamgacha TASDIQLANGAN swing high/low: j nuqta j+k <= i bo'lsagina."""
        k = self.swing_k
        highs, lows = [], []
        for j in range(max(k, i - lookback), i - k + 1):
            h, lo = self.high[j], self.low[j]
            if all(h >= self.high[x] for x in range(j - k, j + k + 1) if x != j):
                highs.append((j, h))
            if all(lo <= self.low[x] for x in range(j - k, j + k + 1) if x != j):
                lows.append((j, lo))
        return highs, lows
