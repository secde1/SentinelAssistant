"""V23: yangi strategiya NOMZODLARI — likvidlik tortishi (bank manipulyatsiyasi / stop-hunt), trend chizig'i, SNR rad etish.

Muhim: bular tadqiqot gipotezalari. Holati 'candidate' — signal generatsiyasiga KIRMAYDI, faqat tarixiy sinov uchun. Faol
bo'lishi uchun sinovdan (xarajat bilan, in-sample/out-of-sample, ko'p sinov tuzatmasi) o'tishi va egasi tasdiqlashi shart.
Parametrlar oldindan, darslik bo'yicha belgilangan va TARIXGA MOSLASHTIRILMAGAN.

Hammasi causal: faqat i-shamgacha (shu jumladan) yopilgan ma'lumot; swing nuqtalari o'ngdan tasdiqlangan (Features.swings).
Kirish signal shamidan keyin (stop-buyurtma, tasdiq), SL strukturaning narigi tomonida, TP = 2R.
"""
from __future__ import annotations

from .indicators import Features
from .strategies import (RANGE, TRANSITION, TREND_DOWN, TREND_UP, NoSetup, Regime, Setup, StrategySpec, _levels, _mk)

ALL_REGIMES = [TREND_UP, TREND_DOWN, RANGE, TRANSITION]


def _nan(*xs: float) -> bool:
    return any(x != x for x in xs)


# ------------------------------------------------------------------------------------------------ likvidlik tortishi
def _liq_sweep(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    """Stop-hunt: narx tasdiqlangan swing ekstremumi ortidagi stoplarni soyasi bilan yig'ib, shamni daraja ichida yopadi
    (soxta buzilish). Teskari yo'nalishda kirish: sham ekstremumi ortida stop-buyurtma."""
    p, a = s.params, f.atr14[i]
    c = f.candles[i]
    if _nan(a) or a <= 0:
        return NoSetup(s.strategy_id, s.version, "ATR hisoblanmagan")
    rng = c.high - c.low
    if rng <= 0:
        return NoSetup(s.strategy_id, s.version, "sham diapazoni nol")
    highs, lows = f.swings(i, int(p["lookback"]))
    gap = int(p["min_age"])
    ev = {"atr14": a, "close": c.close, "high": c.high, "low": c.low}
    pools = [(j, h) for j, h in highs if j <= i - gap and max(f.high[j + 1:i] or [0]) <= h + 0.02 * a]
    for j, h in reversed(pools):  # eng yangi tegilmagan yuqori likvidlik
        pen = c.high - h
        upper_wick = c.high - max(c.open, c.close)
        if pen >= p["pen_atr"] * a and pen <= p["max_pen_atr"] * a and c.close < h and c.close < c.open \
                and upper_wick >= p["wick_frac"] * rng:
            entry = c.low - p["entry_buffer_atr"] * a
            sl = c.high + p["sl_buffer_atr"] * a
            return _mk(s, f, i, "SHORT", "sell_stop", entry, sl, entry - p["rr"] * (sl - entry), c.high,
                       "kirishdan oldin sham sweep ekstremumi ustida yopilsa", {**ev, "swept_high": h, "swept_bar": j},
                       ["yuqoridagi stoplar yig'ildi (soxta buzilish)", "yopilish darajadan pastda, rad etish sham bilan"],
                       f"Likvidlik tortishi: {h:.6g} dan yuqori swing tegildi (+{pen / a:.2f} ATR), yopilish ichkarida")
    pools = [(j, v) for j, v in lows if j <= i - gap and min(f.low[j + 1:i] or [1e18]) >= v - 0.02 * a]
    for j, v in reversed(pools):
        pen = v - c.low
        lower_wick = min(c.open, c.close) - c.low
        if pen >= p["pen_atr"] * a and pen <= p["max_pen_atr"] * a and c.close > v and c.close > c.open \
                and lower_wick >= p["wick_frac"] * rng:
            entry = c.high + p["entry_buffer_atr"] * a
            sl = c.low - p["sl_buffer_atr"] * a
            return _mk(s, f, i, "LONG", "buy_stop", entry, sl, entry + p["rr"] * (entry - sl), c.low,
                       "kirishdan oldin sham sweep ekstremumi ostida yopilsa", {**ev, "swept_low": v, "swept_bar": j},
                       ["pastdagi stoplar yig'ildi (soxta buzilish)", "yopilish darajadan yuqorida, rad etish sham bilan"],
                       f"Likvidlik tortishi: {v:.6g} dan past swing tegildi (+{pen / a:.2f} ATR), yopilish ichkarida")
    return NoSetup(s.strategy_id, s.version, "yangi likvidlik tortishi (soxta buzilish) yo'q")


# ------------------------------------------------------------------------------------------------ trend chizig'i
def _trendline(f: Features, i: int, a: float, up: bool, p: dict):
    """Oxirgi ikki tasdiqlangan swing orqali chiziq (o'sish: pastlar, pasayish: yuqorilar). Chiziq i-1 gacha buzilmagan
    bo'lishi va kamida min_touches marta tegilgan bo'lishi shart. Qaytadi (qiyalik, qiymat_funksiya, tegishlar) yoki None."""
    highs, lows = f.swings(i, int(p["lookback"]))
    pts = lows if up else highs
    if len(pts) < 2:
        return None
    (j1, v1), (j2, v2) = pts[-2], pts[-1]
    if j2 - j1 < p["min_span"] or (up and not v2 > v1) or (not up and not v2 < v1):
        return None
    m = (v2 - v1) / (j2 - j1)
    if not (p["min_slope_atr"] * a <= abs(m) <= p["max_slope_atr"] * a):
        return None  # deyarli gorizontal (bu SNR) yoki juda tik

    def line(j: int) -> float:
        return v1 + m * (j - j1)
    for j in range(j2 + 1, i):  # i dan oldin chiziq buzilmagan
        if (up and f.close[j] < line(j) - 0.2 * a) or (not up and f.close[j] > line(j) + 0.2 * a):
            return None
    touches = 2 + sum(1 for j, v in pts[:-2] if abs(v - line(j)) <= 0.3 * a)
    if touches < p["min_touches"]:
        return None
    return m, line, touches


def _tl_bounce(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    """Trend chizig'idan qaytish (trend yo'nalishida): sham chiziqqa tegib, uning ichida rad etish bilan yopiladi."""
    p, a = s.params, f.atr14[i]
    if _nan(a) or a <= 0:
        return NoSetup(s.strategy_id, s.version, "ATR hisoblanmagan")
    c = f.candles[i]
    for up in (True, False):
        tl = _trendline(f, i, a, up, p)
        if tl is None:
            continue
        m, line, touches = tl
        L = line(i)
        ev = {"atr14": a, "line": L, "slope_per_bar": m, "touches": touches, "close": c.close}
        if up and c.low <= L + p["touch_atr"] * a and c.low >= L - p["touch_atr"] * 2 * a and c.close > L and c.close > c.open:
            entry = c.high + p["entry_buffer_atr"] * a
            sl = L - p["sl_atr"] * a
            return _mk(s, f, i, "LONG", "buy_stop", entry, sl, entry + p["rr"] * (entry - sl), L - 0.5 * a,
                       "kirishdan oldin sham chiziqdan 0.5 ATR pastda yopilsa", ev,
                       [f"chiziq {touches} marta tegilgan, buzilmagan", "trend davom etadi"],
                       f"Ko'tarilish chizig'i {L:.6g} (qiyalik {m:+.4g}/sham), {touches} teginish, chiziqdan qaytish")
        if not up and c.high >= L - p["touch_atr"] * a and c.high <= L + p["touch_atr"] * 2 * a and c.close < L \
                and c.close < c.open:
            entry = c.low - p["entry_buffer_atr"] * a
            sl = L + p["sl_atr"] * a
            return _mk(s, f, i, "SHORT", "sell_stop", entry, sl, entry - p["rr"] * (sl - entry), L + 0.5 * a,
                       "kirishdan oldin sham chiziqdan 0.5 ATR yuqorida yopilsa", ev,
                       [f"chiziq {touches} marta tegilgan, buzilmagan", "pastga trend davom etadi"],
                       f"Pasayish chizig'i {L:.6g} (qiyalik {m:+.4g}/sham), {touches} teginish, chiziqdan qaytish")
    return NoSetup(s.strategy_id, s.version, "tasdiqlangan trend chizig'idan qaytish yo'q")


def _tl_break(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    """Trend chizig'ining buzilishi (trend o'zgarishi): chiziq i-1 gacha buzilmagan, i-shamning yopilishi uni aniq kesadi."""
    p, a = s.params, f.atr14[i]
    if _nan(a) or a <= 0:
        return NoSetup(s.strategy_id, s.version, "ATR hisoblanmagan")
    c = f.candles[i]
    for up in (True, False):
        tl = _trendline(f, i, a, up, p)
        if tl is None:
            continue
        m, line, touches = tl
        L = line(i)
        ev = {"atr14": a, "line": L, "slope_per_bar": m, "touches": touches, "close": c.close}
        if up and c.close < L - p["break_atr"] * a:
            entry = c.low - p["entry_buffer_atr"] * a
            sl = max(c.high, L) + p["sl_buffer_atr"] * a
            return _mk(s, f, i, "SHORT", "sell_stop", entry, sl, entry - p["rr"] * (sl - entry), L + 0.5 * a,
                       "kirishdan oldin sham chiziq ustida yopilsa", ev,
                       [f"{touches} marta tegilgan ko'tarilish chizig'i buzildi", "trend o'zgaradi"],
                       f"Ko'tarilish chizig'i {L:.6g} yopilish bilan pastga buzildi (yopilish {c.close:.6g})")
        if not up and c.close > L + p["break_atr"] * a:
            entry = c.high + p["entry_buffer_atr"] * a
            sl = min(c.low, L) - p["sl_buffer_atr"] * a
            return _mk(s, f, i, "LONG", "buy_stop", entry, sl, entry + p["rr"] * (entry - sl), L - 0.5 * a,
                       "kirishdan oldin sham chiziq ostida yopilsa", ev,
                       [f"{touches} marta tegilgan pasayish chizig'i buzildi", "trend o'zgaradi"],
                       f"Pasayish chizig'i {L:.6g} yopilish bilan yuqoriga buzildi (yopilish {c.close:.6g})")
    return NoSetup(s.strategy_id, s.version, "tasdiqlangan trend chizig'i buzilmadi")


# ------------------------------------------------------------------------------------------------ SNR rad etish
def _snr_reject(s: StrategySpec, f: Features, i: int, r: Regime) -> Setup | NoSetup:
    """SNR: kamida 3 marta sinalgan gorizontal daraja ZONASIDA rad etish sham (uzun soya, daraja ichida yopilish)."""
    p, a = s.params, f.atr14[i]
    if _nan(a) or a <= 0:
        return NoSetup(s.strategy_id, s.version, "ATR hisoblanmagan")
    c = f.candles[i]
    rng = c.high - c.low
    if rng <= 0:
        return NoSetup(s.strategy_id, s.version, "sham diapazoni nol")
    highs, lows = f.swings(i, int(p["lookback"]))
    sup = [x for x in _levels(lows, 0.5 * a, int(p["touches"]))]
    res = [x for x in _levels(highs, 0.5 * a, int(p["touches"]))]
    ev = {"atr14": a, "close": c.close, "supports": [round(x, 6) for x in sup[-3:]], "resistances": [round(x, 6) for x in res[:3]]}
    for lvl in sorted(sup, key=lambda x: -x):
        if abs(c.low - lvl) <= p["zone_atr"] * a and c.close > lvl and c.close > c.open and \
                (min(c.open, c.close) - c.low) >= p["wick_frac"] * rng:
            entry = c.high + p["entry_buffer_atr"] * a
            sl = min(c.low, lvl) - p["sl_atr"] * a
            return _mk(s, f, i, "LONG", "buy_stop", entry, sl, entry + p["rr"] * (entry - sl), lvl - 0.5 * a,
                       "kirishdan oldin sham daraja ostida yopilsa", {**ev, "level": lvl},
                       [f"daraja kamida {p['touches']} marta sinalgan", "zonada rad etish shami"],
                       f"Support {lvl:.6g}: zonada pastki soyali rad etish shami")
    for lvl in sorted(res):
        if abs(c.high - lvl) <= p["zone_atr"] * a and c.close < lvl and c.close < c.open and \
                (c.high - max(c.open, c.close)) >= p["wick_frac"] * rng:
            entry = c.low - p["entry_buffer_atr"] * a
            sl = max(c.high, lvl) + p["sl_atr"] * a
            return _mk(s, f, i, "SHORT", "sell_stop", entry, sl, entry - p["rr"] * (sl - entry), lvl + 0.5 * a,
                       "kirishdan oldin sham daraja ustida yopilsa", {**ev, "level": lvl},
                       [f"daraja kamida {p['touches']} marta sinalgan", "zonada rad etish shami"],
                       f"Resistance {lvl:.6g}: zonada yuqori soyali rad etish shami")
    return NoSetup(s.strategy_id, s.version, "tasdiqlangan SNR zonasida rad etish shami yo'q")


ENGINES_V23 = {"LIQ-SWEEP": _liq_sweep, "TL-BOUNCE": _tl_bounce, "TL-BREAK": _tl_break, "SNR-REJ": _snr_reject}

_TL = {"lookback": 150, "min_span": 8, "min_slope_atr": 0.03, "max_slope_atr": 0.6, "min_touches": 3, "touch_atr": 0.3,
       "break_atr": 0.3, "entry_buffer_atr": 0.1, "sl_atr": 1.0, "sl_buffer_atr": 0.2, "rr": 2.0, "valid_bars": 4}
SPECS_V23 = [
    StrategySpec("LIQ-SWEEP", "Liquidity sweep (stop hunt / bank manipulation)", 1, ALL_REGIMES,
                 {"lookback": 60, "min_age": 5, "pen_atr": 0.05, "max_pen_atr": 1.5, "wick_frac": 0.5,
                  "entry_buffer_atr": 0.1, "sl_buffer_atr": 0.2, "rr": 2.0, "valid_bars": 4},
                 "Tasdiqlangan swing ekstremumi ortidagi stoplar yig'ilgach (soxta buzilish) teskari yo'nalishda kirish.",
                 "Tegilmagan swing high/low (yoshi >=5 sham) soya bilan 0.05-1.5 ATR ga buzilgan, sham daraja ichida teskari "
                 "yopilgan, soya >=50% diapazon; stop-buyurtma sham ekstremumi ortida 0.1 ATR.",
                 "SL = sweep ekstremumi ± 0.2 ATR; TP = 2R; amal muddati 4 sham.", "1R; haqiqiy buzilish xavfi.",
                 status="candidate"),
    StrategySpec("TL-BOUNCE", "Trend line bounce", 1, ALL_REGIMES, dict(_TL),
                 "Kamida 3 marta tegilgan, buzilmagan trend chizig'idan trend yo'nalishida qaytish.",
                 "Oxirgi 2 swing orqali chiziq; sham chiziqqa tegib (0.3 ATR) ichida rad etish bilan yopilgan; stop-buyurtma "
                 "sham ekstremumi ortida.", "SL = chiziq ∓ 1 ATR; TP = 2R.", "1R; chiziq buzilishi xavfi.", status="candidate"),
    StrategySpec("TL-BREAK", "Trend line break", 1, ALL_REGIMES, dict(_TL),
                 "Kamida 3 marta tegilgan trend chizig'ining aniq buzilishi (trend o'zgarishi).",
                 "Chiziq i-1 gacha buzilmagan; i-sham yopilishi chiziqdan 0.3 ATR narida; stop-buyurtma sham ekstremumi "
                 "ortida.", "SL = sham/chiziq ekstremumi ± 0.2 ATR; TP = 2R.", "1R; soxta buzilish xavfi.", status="candidate"),
    StrategySpec("SNR-REJ", "Support/Resistance rejection (3+ touches)", 1, ALL_REGIMES,
                 {"lookback": 200, "touches": 3, "zone_atr": 0.3, "wick_frac": 0.5, "entry_buffer_atr": 0.1,
                  "sl_atr": 0.5, "rr": 2.0, "valid_bars": 4},
                 "3+ marta sinalgan gorizontal daraja zonasida rad etish shamidan keyin kirish.",
                 "Daraja klasteri >=3 swing (0.5 ATR); sham soyasi zonaga (0.3 ATR) tegib, daraja ichida yo'nalishga mos "
                 "yopilgan, soya >=50% diapazon.", "SL = daraja/sham ∓ 0.5 ATR; TP = 2R.", "1R; daraja buzilishi xavfi.",
                 status="candidate"),
]
