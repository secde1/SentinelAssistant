"""Bozor rejimi va versiyali strategiyalar kutubxonasi. Har strategiya — sinalishi kerak bo'lgan GIPOTEZA.

Versiya = qoidalar va parametrlar to'plami (bazada o'zgarmas). Faol versiya jim o'zgartirilmaydi: yangi versiya faqat
eksperiment (backtest + out-of-sample) va egasining tasdig'i (/trading_faollashtir) bilan faol bo'ladi.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Callable

from .indicators import Features, percentile_rank

TREND_UP, TREND_DOWN, RANGE, TRANSITION = "TREND_UP", "TREND_DOWN", "RANGE", "TRANSITION"


def _isnan(*xs: float) -> bool:
    return any(x is None or (isinstance(x, float) and math.isnan(x)) for x in xs)


def round_price(p: float, ref: float) -> float:
    digits = len(str(int(abs(ref)))) if abs(ref) >= 1 else 0
    return round(p, max(2, 6 - digits) if abs(ref) >= 1 else 6)


# -------------------------------------------------------------------------------------------- rejim
@dataclass
class Regime:
    trend: str
    volatility: str
    readings: dict

    def label(self) -> str:
        return f"{self.trend} / volatility {self.volatility}"


def classify_regime(f: Features, i: int) -> Regime:
    c, a, e50, e200, adx = f.close[i], f.atr14[i], f.ema50[i], f.ema200[i], f.adx14[i]
    if _isnan(a, e50, e200, adx) or i < 210:
        raise ValueError("rejim uchun ma'lumot yetarli emas (EMA200/ADX)")
    slope = (f.ema50[i] - f.ema50[i - 10]) / a if a else 0.0
    if adx >= 25 and c > e200 and e50 > e200 and slope > 0.3:
        trend = TREND_UP
    elif adx >= 25 and c < e200 and e50 < e200 and slope < -0.3:
        trend = TREND_DOWN
    elif adx < 20:
        trend = RANGE
    else:
        trend = TRANSITION
    atr_pct = f.atr_pct
    pr = percentile_rank(atr_pct, i, 200)
    vol = "NORMAL" if _isnan(pr) else ("LOW" if pr < 25 else "HIGH" if pr > 75 else "NORMAL")
    readings = {"close": c, "ema50": round(e50, 6), "ema200": round(e200, 6), "adx14": round(adx, 2),
                "ema50_slope_atr": round(slope, 3), "atr14": round(a, 6), "atr_pct": round(atr_pct[i], 4),
                "atr_pct_percentile_200": None if _isnan(pr) else round(pr, 1)}
    return Regime(trend, vol, readings)


# -------------------------------------------------------------------------------------------- natija turlari
@dataclass
class Setup:
    strategy_id: str
    version: int
    direction: str  # LONG | SHORT
    entry_type: str  # buy_stop | buy_limit | sell_stop | sell_limit | next_open
    entry: float
    sl: float
    tp: float
    invalidation: dict  # {"type": "close_below"|"close_above", "level": x, "text": ...}
    evidence: dict
    assumptions: list[str]
    structure: str
    valid_bars: int

    @property
    def rr(self) -> float:
        risk = abs(self.entry - self.sl)
        return abs(self.tp - self.entry) / risk if risk else 0.0


@dataclass
class NoSetup:
    strategy_id: str
    version: int
    reason: str


@dataclass
class StrategySpec:
    strategy_id: str
    name: str
    version: int
    regimes: list[str]
    params: dict
    description: str
    entry_rules: str
    exit_rules: str
    risk: str
    status: str = "active"

    def evaluate(self, f: Features, i: int, regime: Regime) -> Setup | NoSetup:
        fn = ENGINES[self.strategy_id]
        if regime.trend not in self.regimes:
            return NoSetup(self.strategy_id, self.version, f"rejim {regime.trend} bu strategiyaga mos emas "
                                                           f"({', '.join(self.regimes)})")
        return fn(self, f, i, regime)


def _mk(spec: StrategySpec, f: Features, i: int, direction: str, entry_type: str, entry: float, sl: float, tp: float,
        inval_level: float, inval_text: str, evidence: dict, assumptions: list[str], structure: str) -> Setup:
    ref = f.close[i]
    inval_type = "close_below" if direction == "LONG" else "close_above"
    return Setup(spec.strategy_id, spec.version, direction, entry_type, round_price(entry, ref), round_price(sl, ref),
                 round_price(tp, ref), {"type": inval_type, "level": round_price(inval_level, ref), "text": inval_text},
                 {k: (round(v, 6) if isinstance(v, float) else v) for k, v in evidence.items()},
                 assumptions, structure, int(spec.params.get("valid_bars", 6)))


# -------------------------------------------------------------------------------------------- strategiya dvigatellari
def _trend_pullback(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a = s.params, f.atr14[i]
    e20, e50, e200 = f.ema20[i], f.ema50[i], f.ema200[i]
    lows, highs = f.low[i - 2:i + 1], f.high[i - 2:i + 1]
    ev = {"ema20": e20, "ema50": e50, "ema200": e200, "atr14": a, "close": f.close[i]}
    if r.trend == TREND_UP:
        if not (e20 > e50 > e200):
            return NoSetup(s.strategy_id, s.version, "EMA20>EMA50>EMA200 tartibi yo'q")
        if min(lows) > e20 + p["pullback_atr"] * a or f.close[i] <= e20:
            return NoSetup(s.strategy_id, s.version, "EMA20 ga pullback va undan yuqorida yopilish yo'q")
        entry = f.high[i] + p["entry_buffer_atr"] * a
        sl = entry - p["sl_atr"] * a
        return _mk(s, f, i, "LONG", "buy_stop", entry, sl, entry + p["rr"] * (entry - sl), e50,
                   "kirishdan oldin sham EMA50 dan pastda yopilsa", ev,
                   ["trend davom etadi (ADX>=25)", "pullback EMA20 da tugagan"],
                   "Yuqoriga trend: EMA20>EMA50>EMA200, oxirgi 3 shamda EMA20 ga pullback")
    if not (e20 < e50 < e200):
        return NoSetup(s.strategy_id, s.version, "EMA20<EMA50<EMA200 tartibi yo'q")
    if max(highs) < e20 - p["pullback_atr"] * a or f.close[i] >= e20:
        return NoSetup(s.strategy_id, s.version, "EMA20 ga pullback va undan pastda yopilish yo'q")
    entry = f.low[i] - p["entry_buffer_atr"] * a
    sl = entry + p["sl_atr"] * a
    return _mk(s, f, i, "SHORT", "sell_stop", entry, sl, entry - p["rr"] * (sl - entry), e50,
               "kirishdan oldin sham EMA50 dan yuqorida yopilsa", ev,
               ["pastga trend davom etadi (ADX>=25)", "pullback EMA20 da tugagan"],
               "Pastga trend: EMA20<EMA50<EMA200, oxirgi 3 shamda EMA20 ga pullback")


def _breakout_retest(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a, n = s.params, f.atr14[i], int(s.params["lookback"])
    for j in range(i, max(n, i - int(p["recent"])) - 1, -1):
        prior_high = max(f.high[j - n:j])
        prior_low = min(f.low[j - n:j])
        ev = {"breakout_bar": f.candles[j].ts.isoformat(), "atr14": a, "close": f.close[i]}
        if f.close[j] > prior_high and r.trend != TREND_DOWN:
            level = prior_high
            if f.low[i] <= level + p["retest_atr"] * a and f.close[i] > level:
                entry = level + 0.1 * a
                sl = level - p["sl_atr"] * a
                return _mk(s, f, i, "LONG", "buy_limit", entry, sl, entry + p["rr"] * (entry - sl),
                           level - 0.5 * a, "sham buzilgan daraja (minus 0.5 ATR) dan pastda yopilsa",
                           {**ev, "broken_level": level}, ["buzilgan qarshilik endi qo'llab-quvvatlash bo'ladi"],
                           f"{n}-shamlik qarshilik {level:.6g} yuqoriga buzildi, narx qayta sinamoqda")
            return NoSetup(s.strategy_id, s.version, "buzilish bor, lekin retest zonasiga qaytmagan")
        if f.close[j] < prior_low and r.trend != TREND_UP:
            level = prior_low
            if f.high[i] >= level - p["retest_atr"] * a and f.close[i] < level:
                entry = level - 0.1 * a
                sl = level + p["sl_atr"] * a
                return _mk(s, f, i, "SHORT", "sell_limit", entry, sl, entry - p["rr"] * (sl - entry),
                           level + 0.5 * a, "sham buzilgan daraja (plus 0.5 ATR) dan yuqorida yopilsa",
                           {**ev, "broken_level": level}, ["buzilgan qo'llab-quvvatlash endi qarshilik bo'ladi"],
                           f"{n}-shamlik qo'llab-quvvatlash {level:.6g} pastga buzildi, narx qayta sinamoqda")
            return NoSetup(s.strategy_id, s.version, "buzilish bor, lekin retest zonasiga qaytmagan")
    return NoSetup(s.strategy_id, s.version, f"oxirgi {p['recent']} shamda {n}-shamlik daraja buzilmagan")


def _levels(points: list[tuple[int, float]], tol: float, touches: int) -> list[float]:
    vals = sorted(v for _, v in points)
    clusters: list[list[float]] = []
    for v in vals:
        if clusters and v - clusters[-1][-1] <= tol:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [sum(c) / len(c) for c in clusters if len(c) >= touches]


def _support_resistance(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a, c = s.params, f.atr14[i], f.close[i]
    highs, lows = f.swings(i, int(p["lookback"]))
    supports = [x for x in _levels(lows, 0.5 * a, int(p["touches"])) if x < c]
    resist = [x for x in _levels(highs, 0.5 * a, int(p["touches"])) if x > c]
    ev = {"atr14": a, "close": c, "rsi14": f.rsi14[i], "supports": [round(x, 6) for x in supports[-3:]],
          "resistances": [round(x, 6) for x in resist[:3]]}
    if supports and c - supports[-1] <= p["zone_atr"] * a and f.rsi14[i] < 50:
        sup = supports[-1]
        entry, sl = sup + 0.1 * a, sup - p["sl_atr"] * a
        if not resist:
            return NoSetup(s.strategy_id, s.version, "qo'llab-quvvatlash yaqin, lekin maqsad (qarshilik) aniqlanmadi")
        tp = resist[0] - 0.1 * a
        if (tp - entry) / (entry - sl) < p["min_rr"]:
            return NoSetup(s.strategy_id, s.version, "qarshilik juda yaqin — R/R past")
        return _mk(s, f, i, "LONG", "buy_limit", entry, sl, tp, sup - 0.5 * a,
                   "sham qo'llab-quvvatlashdan 0.5 ATR pastda yopilsa", {**ev, "level": sup},
                   [f"daraja kamida {p['touches']} marta sinalgan", "diapazon davom etadi"],
                   f"Qo'llab-quvvatlash {sup:.6g} (swing klaster), qarshilik {resist[0]:.6g}")
    if resist and resist[0] - c <= p["zone_atr"] * a and f.rsi14[i] > 50:
        res = resist[0]
        entry, sl = res - 0.1 * a, res + p["sl_atr"] * a
        if not supports:
            return NoSetup(s.strategy_id, s.version, "qarshilik yaqin, lekin maqsad (qo'llab-quvvatlash) aniqlanmadi")
        tp = supports[-1] + 0.1 * a
        if (entry - tp) / (sl - entry) < p["min_rr"]:
            return NoSetup(s.strategy_id, s.version, "qo'llab-quvvatlash juda yaqin — R/R past")
        return _mk(s, f, i, "SHORT", "sell_limit", entry, sl, tp, res + 0.5 * a,
                   "sham qarshilikdan 0.5 ATR yuqorida yopilsa", {**ev, "level": res},
                   [f"daraja kamida {p['touches']} marta sinalgan", "diapazon davom etadi"],
                   f"Qarshilik {res:.6g} (swing klaster), qo'llab-quvvatlash {supports[-1]:.6g}")
    return NoSetup(s.strategy_id, s.version, "narx tasdiqlangan darajaga yaqin emas")


def _ma_cross(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a, c = s.params, f.atr14[i], f.close[i]
    up = f.ema9[i] > f.ema21[i] and f.ema9[i - 2] <= f.ema21[i - 2]
    down = f.ema9[i] < f.ema21[i] and f.ema9[i - 2] >= f.ema21[i - 2]
    ev = {"ema9": f.ema9[i], "ema21": f.ema21[i], "ema200": f.ema200[i], "atr14": a, "close": c}
    n = int(p["swing_lookback"])
    if up and c > f.ema200[i]:
        sl = min(min(f.low[i - n:i + 1]) - 0.2 * a, c - p["sl_atr_min"] * a)
        return _mk(s, f, i, "LONG", "next_open", c, sl, c + p["rr"] * (c - sl), f.ema21[i],
                   "kirishdan oldin EMA9 yana EMA21 dan pastga tushsa", ev,
                   ["kesishish EMA200 yo'nalishida", "kirish keyingi sham ochilishida"],
                   "EMA9 EMA21 ni yuqoriga kesib o'tdi, narx EMA200 dan yuqorida")
    if down and c < f.ema200[i]:
        sl = max(max(f.high[i - n:i + 1]) + 0.2 * a, c + p["sl_atr_min"] * a)
        return _mk(s, f, i, "SHORT", "next_open", c, sl, c - p["rr"] * (sl - c), f.ema21[i],
                   "kirishdan oldin EMA9 yana EMA21 dan yuqoriga chiqsa", ev,
                   ["kesishish EMA200 yo'nalishida", "kirish keyingi sham ochilishida"],
                   "EMA9 EMA21 ni pastga kesib o'tdi, narx EMA200 dan pastda")
    return NoSetup(s.strategy_id, s.version, "EMA200 yo'nalishida yangi EMA9/21 kesishishi yo'q")


def _rsi_mean_reversion(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a, c, rsi = s.params, f.atr14[i], f.close[i], f.rsi14[i]
    if r.volatility == "HIGH":
        return NoSetup(s.strategy_id, s.version, "volatillik yuqori — o'rtachaga qaytish xavfli")
    ev = {"rsi14": rsi, "bb_lower": f.bb_lower[i], "bb_upper": f.bb_upper[i], "sma20": f.sma20[i], "atr14": a,
          "close": c}
    if rsi < p["oversold"] and c < f.bb_lower[i]:
        entry = c - p["entry_offset_atr"] * a
        sl, tp = entry - p["sl_atr"] * a, f.sma20[i]
        if tp <= entry or (tp - entry) / (entry - sl) < p["min_rr"]:
            return NoSetup(s.strategy_id, s.version, "o'rtachagacha masofa kichik — R/R past")
        return _mk(s, f, i, "LONG", "buy_limit", entry, sl, tp, entry - p["sl_atr"] * a,
                   "kirishdan oldin narx SL darajasidan pastda yopilsa", ev,
                   ["diapazon rejimi davom etadi", "narx SMA20 ga qaytadi"],
                   f"RSI {rsi:.1f} (<{p['oversold']}), narx pastki Bollinger'dan tashqarida")
    if rsi > p["overbought"] and c > f.bb_upper[i]:
        entry = c + p["entry_offset_atr"] * a
        sl, tp = entry + p["sl_atr"] * a, f.sma20[i]
        if tp >= entry or (entry - tp) / (sl - entry) < p["min_rr"]:
            return NoSetup(s.strategy_id, s.version, "o'rtachagacha masofa kichik — R/R past")
        return _mk(s, f, i, "SHORT", "sell_limit", entry, sl, tp, entry + p["sl_atr"] * a,
                   "kirishdan oldin narx SL darajasidan yuqorida yopilsa", ev,
                   ["diapazon rejimi davom etadi", "narx SMA20 ga qaytadi"],
                   f"RSI {rsi:.1f} (>{p['overbought']}), narx yuqori Bollinger'dan tashqarida")
    return NoSetup(s.strategy_id, s.version, f"RSI {rsi:.1f} — haddan tashqari holat yo'q")


def _volatility_breakout(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a = s.params, f.atr14[i]
    pr = percentile_rank(f.bb_width, i, 120)
    if _isnan(pr) or pr > p["squeeze_pctile"]:
        return NoSetup(s.strategy_id, s.version, f"siqilish (squeeze) yo'q: BB kengligi persentili {pr:.0f}")
    n = int(p["range_bars"])
    hi, lo = max(f.high[i - n + 1:i + 1]), min(f.low[i - n + 1:i + 1])
    ev = {"bb_width_percentile": pr, "range_high": hi, "range_low": lo, "atr14": a, "ema50": f.ema50[i]}
    if hi - lo > p["max_range_atr"] * a:
        return NoSetup(s.strategy_id, s.version, "diapazon juda keng — SL masofasi katta")
    if f.ema50[i] >= f.ema50[i - 5]:
        entry, sl = hi + p["buffer_atr"] * a, lo - p["buffer_atr"] * a
        return _mk(s, f, i, "LONG", "buy_stop", entry, sl, entry + p["rr"] * (entry - sl), lo,
                   "kirishdan oldin sham diapazon pastidan tashqarida yopilsa", ev,
                   ["siqilishdan keyin volatillik kengayadi", "yo'nalish EMA50 qiyaligi bo'yicha"],
                   f"{n}-shamlik tor diapazon {lo:.6g}–{hi:.6g}, BB siqilishi")
    entry, sl = lo - p["buffer_atr"] * a, hi + p["buffer_atr"] * a
    return _mk(s, f, i, "SHORT", "sell_stop", entry, sl, entry - p["rr"] * (sl - entry), hi,
               "kirishdan oldin sham diapazon tepasidan tashqarida yopilsa", ev,
               ["siqilishdan keyin volatillik kengayadi", "yo'nalish EMA50 qiyaligi bo'yicha"],
               f"{n}-shamlik tor diapazon {lo:.6g}–{hi:.6g}, BB siqilishi")


def _market_structure(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    p, a = s.params, f.atr14[i]
    highs, lows = f.swings(i, 120)
    if len(lows) < 2 or not highs:
        return NoSetup(s.strategy_id, s.version, "tasdiqlangan swing nuqtalari yetarli emas")
    (jl1, l1), l2 = lows[-2], lows[-1][1]
    hs_after = [(j, h) for j, h in highs if j > jl1]
    if r.trend != TREND_DOWN and l2 > l1 and hs_after:
        h = max(h for _, h in hs_after)
        if f.close[i] > h >= f.close[i - 1] or (f.close[i] > h and f.close[i - 2] <= h):
            top = f.high[i]
            entry = top - p["retrace"] * (top - l2)
            sl = l2 - p["sl_buffer_atr"] * a
            return _mk(s, f, i, "LONG", "buy_limit", entry, sl, entry + p["rr"] * (entry - sl), l2,
                       "kirishdan oldin sham oxirgi ko'tarilgan pastlikdan (HL) pastda yopilsa",
                       {"swing_low_prev": l1, "swing_low_last": l2, "broken_high": h, "atr14": a},
                       ["struktura buzilishi (BOS) davom etadi", "impulsning 50% retrace'i kirish beradi"],
                       f"HL {l2:.6g} > {l1:.6g}, swing high {h:.6g} yuqoriga buzildi (BOS)")
    hs = highs[-2:] if len(highs) >= 2 else []
    if r.trend != TREND_UP and len(hs) == 2 and hs[1][1] < hs[0][1]:
        ls_after = [(j, lo) for j, lo in lows if j > hs[0][0]]
        if ls_after:
            low_lvl = min(lo for _, lo in ls_after)
            if f.close[i] < low_lvl <= f.close[i - 1] or (f.close[i] < low_lvl and f.close[i - 2] >= low_lvl):
                bottom, h2 = f.low[i], hs[1][1]
                entry = bottom + p["retrace"] * (h2 - bottom)
                sl = h2 + p["sl_buffer_atr"] * a
                return _mk(s, f, i, "SHORT", "sell_limit", entry, sl, entry - p["rr"] * (sl - entry), h2,
                           "kirishdan oldin sham oxirgi pasaygan cho'qqidan (LH) yuqorida yopilsa",
                           {"swing_high_prev": hs[0][1], "swing_high_last": h2, "broken_low": low_lvl, "atr14": a},
                           ["struktura buzilishi (BOS) davom etadi", "impulsning 50% retrace'i kirish beradi"],
                           f"LH {h2:.6g} < {hs[0][1]:.6g}, swing low {low_lvl:.6g} pastga buzildi (BOS)")
    return NoSetup(s.strategy_id, s.version, "yangi struktura buzilishi (BOS) yo'q")


ENGINES: dict[str, Callable[[StrategySpec, Features, int, Regime], Setup | NoSetup]] = {
    "TF-PULLBACK": _trend_pullback, "BRK-RETEST": _breakout_retest, "SR-BOUNCE": _support_resistance,
    "MA-CROSS": _ma_cross, "RSI-MR": _rsi_mean_reversion, "VOL-BRK": _volatility_breakout, "MS-BOS": _market_structure,
}

DEFAULT_STRATEGIES = [
    StrategySpec("TF-PULLBACK", "Trend following (EMA pullback)", 1, [TREND_UP, TREND_DOWN],
                 {"pullback_atr": 0.3, "sl_atr": 1.5, "rr": 2.0, "entry_buffer_atr": 0.1, "valid_bars": 6},
                 "Kuchli trendda EMA20 ga pullbackdan keyin trend yo'nalishida kirish.",
                 "EMA20>EMA50>EMA200 (short: teskari), oxirgi 3 shamda EMA20 ga tegish, yopilish EMA20 ortida; buy/sell "
                 "stop signal shami ekstremumidan 0.1 ATR narida.", "SL = kirish ∓ 1.5 ATR; TP = 2R; amal muddati 6 sham.",
                 "Bitta g'oyada 1R; SL ATR bo'yicha."),
    StrategySpec("BRK-RETEST", "Breakout and retest", 1, [TREND_UP, TREND_DOWN, TRANSITION],
                 {"lookback": 20, "recent": 5, "retest_atr": 0.4, "sl_atr": 1.0, "rr": 2.0, "valid_bars": 6},
                 "20-shamlik daraja buzilgach, unga qayta sinov (retest) paytida kirish.",
                 "Oxirgi 5 shamda 20-shamlik high/low yopilish bilan buzilgan; narx darajadan 0.4 ATR ichida; limit "
                 "daraja ± 0.1 ATR.", "SL = daraja ∓ 1 ATR; TP = 2R; bekor: daraja ∓ 0.5 ATR ortida yopilish.",
                 "1R; soxta buzilish xavfi."),
    StrategySpec("SR-BOUNCE", "Support and resistance", 1, [RANGE, TRANSITION],
                 {"zone_atr": 0.5, "sl_atr": 0.8, "min_rr": 1.5, "touches": 2, "lookback": 120, "valid_bars": 6},
                 "Kamida 2 marta sinalgan swing darajadan qaytish.",
                 "Narx tasdiqlangan darajadan 0.5 ATR ichida, RSI daraja tomoniga mos; limit daraja ± 0.1 ATR.",
                 "SL = daraja ∓ 0.8 ATR; TP = qarama-qarshi daraja; R/R >= 1.5.", "1R; daraja buzilishi xavfi."),
    StrategySpec("MA-CROSS", "Moving average crossover (EMA 9/21)", 1, [TREND_UP, TREND_DOWN, TRANSITION],
                 {"swing_lookback": 10, "sl_atr_min": 1.0, "rr": 2.0, "valid_bars": 1},
                 "EMA9/EMA21 kesishishi EMA200 yo'nalishida.",
                 "Oxirgi 2 shamda kesishish; narx EMA200 tomonida; kirish keyingi sham ochilishida.",
                 "SL = so'nggi 10 sham swingi ∓ 0.2 ATR (kamida 1 ATR); TP = 2R.", "1R; yon bozorda ko'p soxta signal."),
    StrategySpec("RSI-MR", "RSI mean reversion", 1, [RANGE],
                 {"oversold": 30, "overbought": 70, "sl_atr": 1.2, "min_rr": 1.2, "entry_offset_atr": 0.2,
                  "valid_bars": 4},
                 "Diapazonda RSI haddan tashqari holatidan SMA20 ga qaytish.",
                 "Faqat RANGE va volatillik HIGH emas; RSI<30 va narx pastki Bollinger'dan past (short: teskari); limit "
                 "0.2 ATR naridan.", "SL = 1.2 ATR; TP = SMA20; R/R >= 1.2.", "1R; trend boshlansa ketma-ket zarar."),
    StrategySpec("VOL-BRK", "Volatility breakout (squeeze)", 1, [RANGE, TRANSITION],
                 {"squeeze_pctile": 20, "range_bars": 10, "buffer_atr": 0.1, "max_range_atr": 3.0, "rr": 2.0,
                  "valid_bars": 6},
                 "Bollinger siqilishidan keyin diapazon buzilishi.",
                 "BB kengligi 120-sham persentili <= 20; 10-shamlik diapazon <= 3 ATR; yo'nalish EMA50 qiyaligi; stop "
                 "kirish diapazon chegarasidan 0.1 ATR narida.", "SL = diapazonning qarama-qarshi chegarasi; TP = 2R.",
                 "1R; soxta buzilish xavfi."),
    StrategySpec("MS-BOS", "Market structure (break of structure)", 1, [TREND_UP, TREND_DOWN, TRANSITION],
                 {"retrace": 0.5, "sl_buffer_atr": 0.2, "rr": 2.0, "valid_bars": 8},
                 "HL/LH struktura va swing nuqtasining buzilishi (BOS), impuls retrace'ida kirish.",
                 "Tasdiqlangan swinglar (3 sham); HL hosil bo'lib, oxirgi swing high yopilish bilan buzilgan (short: "
                 "teskari); limit impulsning 50% ida.", "SL = HL/LH ∓ 0.2 ATR; TP = 2R.", "1R; struktura tez o'zgarishi."),
]

PRIORITY = {
    TREND_UP: ["TF-PULLBACK", "MS-BOS", "BRK-RETEST", "MA-CROSS"],
    TREND_DOWN: ["TF-PULLBACK", "MS-BOS", "BRK-RETEST", "MA-CROSS"],
    TRANSITION: ["BRK-RETEST", "MS-BOS", "MA-CROSS", "SR-BOUNCE", "VOL-BRK"],
    RANGE: ["SR-BOUNCE", "RSI-MR", "VOL-BRK"],
}


# V21: 5 yillik tarixiy sinov (7 instrument, H1/H4, o'lchangan spred bilan) natijasi bo'yicha arxivga olingan strategiyalar.
# Kod o'chirilmaydi: ENGINES va DEFAULT_STRATEGIES da turadi, faqat faol signal generatsiyasidan chiqarilgan (status
# 'archived'). Faollashtirish — faqat egasi (Registry.activate). Sabablar tadqiqot hisobotida (research/, lab/).
ARCHIVE_V21 = {
    "BRK-RETEST": "H1 7984 savdo, net -0.137R [-0.167; -0.107] — aniq zarar",
    "SR-BOUNCE": "H1 6972 savdo, net -0.146R [-0.184; -0.107] — aniq zarar",
    "MS-BOS": "H1 2384 savdo, net -0.087R, ishonch oralig'i nolning pastida",
    "RSI-MR": "H1 645 savdo, net -0.107R; H4 da namuna juda kichik (184), ishonchsiz",
}
ARCHIVE_MARK = "[v21-arxiv]"


# -------------------------------------------------------------------------------------------- reestr (baza)
class Registry:
    def __init__(self, db, export_path=None):
        self.db = db
        self.export_path = export_path

    def sync_defaults(self) -> None:
        from .db import dumps, utcnow
        for s in DEFAULT_STRATEGIES:
            if self.db.one("SELECT 1 FROM strategies WHERE strategy_id=? AND version=?", (s.strategy_id, s.version)):
                continue
            self.db.execute("INSERT INTO strategies(strategy_id, version, name, description, params, regimes, "
                            "entry_rules, exit_rules, risk, status, created_at, created_by, parent_version, notes) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (s.strategy_id, s.version, s.name, s.description, dumps(s.params), dumps(s.regimes),
                             s.entry_rules, s.exit_rules, s.risk, s.status, utcnow(), "default", None,
                             "Boshlang'ich gipoteza — tarixiy sinov kerak"))
        # V21: bir martalik arxivlash. Belgi (ARCHIVE_MARK) qo'yilgach egasi qayta faollashtirsa, qayta arxivlanmaydi.
        for sid, why in ARCHIVE_V21.items():
            self.db.execute("UPDATE strategies SET status='archived', notes=COALESCE(notes,'') || ? WHERE strategy_id=? "
                            "AND status='active' AND COALESCE(notes,'') NOT LIKE ?",
                            (f" | {ARCHIVE_MARK} arxivlandi: {why}", sid, f"%{ARCHIVE_MARK}%"))
        self.export()

    @staticmethod
    def _spec(row: dict) -> StrategySpec:
        return StrategySpec(row["strategy_id"], row["name"], row["version"], json.loads(row["regimes"]),
                            json.loads(row["params"]), row["description"] or "", row["entry_rules"] or "",
                            row["exit_rules"] or "", row["risk"] or "", row["status"])

    def get(self, strategy_id: str, version: int) -> StrategySpec | None:
        row = self.db.one("SELECT * FROM strategies WHERE strategy_id=? AND version=?", (strategy_id, version))
        return self._spec(row) if row else None

    def active(self) -> dict[str, StrategySpec]:
        rows = self.db.query("SELECT * FROM strategies WHERE status='active'")
        return {r["strategy_id"]: self._spec(r) for r in rows}

    def all(self) -> list[dict]:
        return self.db.query("SELECT * FROM strategies ORDER BY strategy_id, version")

    def create_version(self, strategy_id: str, params_patch: dict, notes: str, created_by: str) -> StrategySpec:
        """Yangi NOMZOD versiya (faol emas). Eski versiya o'zgarmaydi."""
        from .db import dumps, utcnow
        base = self.active().get(strategy_id)
        if base is None:
            raise ValueError(f"strategiya yo'q: {strategy_id}")
        unknown = [k for k in params_patch if k not in base.params]
        if unknown:
            raise ValueError(f"noma'lum parametr(lar): {', '.join(unknown)}")
        last = self.db.one("SELECT MAX(version) AS v FROM strategies WHERE strategy_id=?", (strategy_id,))["v"]
        params = {**base.params, **params_patch}
        self.db.execute("INSERT INTO strategies(strategy_id, version, name, description, params, regimes, entry_rules, "
                        "exit_rules, risk, status, created_at, created_by, parent_version, notes) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (strategy_id, last + 1, base.name, base.description, dumps(params), dumps(base.regimes),
                         base.entry_rules, base.exit_rules, base.risk, "candidate", utcnow(), created_by,
                         base.version, notes))
        self.export()
        return self.get(strategy_id, last + 1)

    def activate(self, strategy_id: str, version: int, approved_by: str) -> None:
        """Faqat egasining aniq buyrug'i bilan (status o'zgaradi, qoidalar emas)."""
        if self.get(strategy_id, version) is None:
            raise ValueError("bunday versiya yo'q")
        self.db.execute("UPDATE strategies SET status='retired' WHERE strategy_id=? AND status='active'", (strategy_id,))
        self.db.execute("UPDATE strategies SET status='active', notes=COALESCE(notes,'') || ? WHERE strategy_id=? AND "
                        "version=?", (f" | faollashtirdi: {approved_by}", strategy_id, version))
        self.export()

    def export(self) -> None:
        if self.export_path is None:
            return
        rows = self.all()
        for r in rows:
            r["params"] = json.loads(r["params"])
            r["regimes"] = json.loads(r["regimes"])
        self.export_path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


def candidates(regime: Regime, active: dict[str, StrategySpec]) -> list[StrategySpec]:
    return [active[sid] for sid in PRIORITY.get(regime.trend, []) if sid in active]


__all__ = ["Regime", "Setup", "NoSetup", "StrategySpec", "Registry", "DEFAULT_STRATEGIES", "classify_regime",
           "candidates", "round_price", "ARCHIVE_V21"]


# V23: nomzod strategiyalar (status 'candidate' — signal generatsiyasiga kirmaydi; sinovdan o'tib, egasi tasdiqlagach faol bo'ladi)
from . import strategies_smc as _smc  # noqa: E402

ENGINES.update(_smc.ENGINES_V23)
DEFAULT_STRATEGIES.extend(_smc.SPECS_V23)
for _reg in PRIORITY:
    PRIORITY[_reg] = PRIORITY[_reg] + list(_smc.ENGINES_V23)
