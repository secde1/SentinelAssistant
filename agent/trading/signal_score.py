"""Signal sifati: 10 ta tekshiriladigan mezon (V22). Sof funksiyalar — tarmoq ham, baza ham yo'q.

Har bir mezon 1 ball va FAQAT haqiqatan hisoblangan ko'rsatkichga asoslanadi. Ma'lumot yetishmasa mezon 0 ball oladi va
"ma'lumot yo'q" deb belgilanadi; asosiy mezonlar yetishmasa signal umuman yuborilmaydi (blocked). Ball — bajarilgan
mezonlar soni, G'ALABA EHTIMOLI EMAS; EMA, MACD va RSI narxdan hosil bo'lgan, shuning uchun mezonlar to'liq mustaqil emas.

Darajalar:  0-3 — yuborilmaydi (DROP) · 4-5 — kuzatuv ro'yxati (WATCH) · 6-7 — faqat qo'shimcha tasdiq bo'lsa (CONFIRM:
4H va 1H trend + hajm + R/R hammasi bajarilgan bo'lsa, aks holda WATCH) · 8-10 — kuchli nomzod (STRONG).
4H trend signalga qarama-qarshi bo'lsa — ball qanday bo'lmasin BLOCK (5 yillik sinovda bunday savdolar eng yomon edi).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .indicators import Features, ema
from .strategies import TREND_DOWN, TREND_UP, classify_regime

MAX_SCORE = 10
CORE = ("h4_trend", "h1_trend", "m15_ema", "rsi", "macd", "volume", "structure")  # bularsiz signal yuborilmaydi
NAN = float("nan")


@dataclass
class Item:
    key: str
    label: str
    ok: bool | None  # None — ma'lumot yo'q
    detail: str


@dataclass
class Score:
    score: int
    items: list[Item]
    tier: str  # STRONG | CONFIRM | WATCH | DROP | BLOCKED
    blocked: str | None = None
    missing: list[str] = field(default_factory=list)

    def passed(self) -> list[Item]:
        return [i for i in self.items if i.ok]

    def get(self, key: str) -> Item:
        return next(i for i in self.items if i.key == key)


def macd_hist(close: list[float]) -> list[float]:
    """MACD(12,26,9) gistogrammasi (EMA12-EMA26 minus signal). Boshlang'ich qismi NaN."""
    e12, e26 = ema(close, 12), ema(close, 26)
    macd = [a - b if not (math.isnan(a) or math.isnan(b)) else NAN for a, b in zip(e12, e26)]
    valid = [v for v in macd if not math.isnan(v)]
    sig_valid = ema(valid, 9) if len(valid) >= 9 else [NAN] * len(valid)
    out, k = [], 0
    for v in macd:
        if math.isnan(v):
            out.append(NAN)
        else:
            s = sig_valid[k]
            k += 1
            out.append(v - s if not math.isnan(s) else NAN)
    return out


def _fmt(x: float) -> str:
    return f"{x:.6g}"


def _regime_trend(f: Features) -> tuple[str | None, str]:
    i = len(f) - 1
    try:
        r = classify_regime(f, i)
    except ValueError:
        return None, "ma'lumot yetarli emas (EMA200/ADX)"
    return r.trend, f"{r.trend} (ADX {r.readings['adx14']})"


def _trend_item(key: str, label: str, f: Features, long: bool) -> Item:
    trend, detail = _regime_trend(f)
    if trend is None:
        return Item(key, label, None, detail)
    want = TREND_UP if long else TREND_DOWN
    return Item(key, label, trend == want, detail)


def trend_of(f: Features) -> str | None:
    return _regime_trend(f)[0]


def evaluate(long: bool, f15: Features, f1h: Features, f4h: Features, *, entry: float, sl: float, tp: float,
             rr_net: float, min_rr: float, volume_kind: str = "volume", breakout_bars: int = 3) -> Score:
    items: list[Item] = []
    side = "LONG" if long else "SHORT"

    # 1-2. 4H va 1H trend (bozor rejimi: ADX + EMA50/EMA200 + qiyalik)
    h4 = _trend_item("h4_trend", "4H trend", f4h, long)
    items.append(h4)
    items.append(_trend_item("h1_trend", "1H trend", f1h, long))

    # 3. 15M EMA20/EMA50
    i15 = len(f15) - 1
    e20, e50, c15 = f15.ema20[i15], f15.ema50[i15], f15.close[i15]
    if any(math.isnan(v) for v in (e20, e50, c15)):
        items.append(Item("m15_ema", "15M EMA20/EMA50", None, "ma'lumot yetarli emas"))
    else:
        ok = (e20 > e50 and c15 > e20) if long else (e20 < e50 and c15 < e20)
        items.append(Item("m15_ema", "15M EMA20/EMA50", ok,
                          f"EMA20 {_fmt(e20)} {'>' if e20 > e50 else '<'} EMA50 {_fmt(e50)}, narx EMA20 "
                          f"{'tepasida' if c15 > e20 else 'ostida'}"))

    # 4. RSI (1H)
    i = len(f1h) - 1
    rsi = f1h.rsi14[i]
    if math.isnan(rsi):
        items.append(Item("rsi", "RSI (1H)", None, "ma'lumot yetarli emas"))
    else:
        ok = 45 <= rsi <= 70 if long else 30 <= rsi <= 55
        items.append(Item("rsi", "RSI (1H)", ok, f"RSI14 = {rsi:.1f} ({'45-70' if long else '30-55'} oralig'i kerak)"))

    # 5. MACD gistogrammasi (1H): ishora mos va yo'nalishda kuchaymoqda
    hist = macd_hist(f1h.close)
    h, hp = hist[i], hist[i - 1] if i >= 1 else NAN
    if math.isnan(h) or math.isnan(hp):
        items.append(Item("macd", "MACD (1H)", None, "ma'lumot yetarli emas"))
    else:
        ok = (h > 0 and h >= hp) if long else (h < 0 and h <= hp)
        items.append(Item("macd", "MACD (1H)", ok, f"gistogramma {h:+.4g} (oldingi {hp:+.4g}) — "
                          f"{'BUY' if h > 0 else 'SELL'} tomonda, {'kuchaymoqda' if abs(h) >= abs(hp) else 'susaymoqda'}"))

    # 6. Support/Resistance: foyda tomonidagi eng yaqin tasdiqlangan daraja kamida 1R uzoqda
    risk = abs(entry - sl)
    highs, lows = f1h.swings(i, lookback=200)
    if risk <= 0:
        items.append(Item("sr", "Support/Resistance", None, "risk noldan katta emas"))
    else:
        if long:
            above = sorted(p for _, p in highs if p > entry)
            lvl = above[0] if above else None
            ok = lvl is None or (lvl - entry) >= risk
            txt = f"eng yaqin qarshilik {_fmt(lvl)} ({(lvl - entry) / risk:.2f}R)" if lvl is not None else \
                "foyda tomonida tasdiqlangan qarshilik yo'q"
        else:
            below = sorted((p for _, p in lows if p < entry), reverse=True)
            lvl = below[0] if below else None
            ok = lvl is None or (entry - lvl) >= risk
            txt = f"eng yaqin support {_fmt(lvl)} ({(entry - lvl) / risk:.2f}R)" if lvl is not None else \
                "foyda tomonida tasdiqlangan support yo'q"
        items.append(Item("sr", "Support/Resistance", ok, txt))

    # 7. Breakout/breakdown: oxirgi breakout_bars ta 1H shamdan birining yopilishi oldingi 20 sham ekstremumidan tashqarida
    brk, brk_txt = False, "oxirgi shamlarda 20-shamlik daraja buzilmagan"
    if len(f1h) > 25:
        for j in range(i, i - breakout_bars, -1):
            prev_hi = max(f1h.high[j - 20:j])
            prev_lo = min(f1h.low[j - 20:j])
            if long and f1h.close[j] > prev_hi:
                brk, brk_txt = True, f"yopilish {_fmt(f1h.close[j])} > 20-shamlik high {_fmt(prev_hi)} ({i - j} sham oldin)"
                break
            if not long and f1h.close[j] < prev_lo:
                brk, brk_txt = True, f"yopilish {_fmt(f1h.close[j])} < 20-shamlik low {_fmt(prev_lo)} ({i - j} sham oldin)"
                break
        items.append(Item("breakout", "Breakout/breakdown", brk, brk_txt))
    else:
        items.append(Item("breakout", "Breakout/breakdown", None, "ma'lumot yetarli emas"))

    # 8. Hajm: oxirgi yopilgan 1H sham hajmi oldingi 20 sham o'rtachasidan kam emas
    vols = [c.volume for c in f1h.candles]
    vlabel = "tick hajm" if volume_kind == "tick" else "hajm"
    if len(vols) < 22 or vols[i] <= 0 and sum(vols[i - 20:i]) <= 0:
        items.append(Item("volume", "Hajm", None, f"{vlabel} ma'lumoti yo'q"))
    else:
        avg = sum(vols[i - 20:i]) / 20
        ratio = vols[i] / avg if avg else NAN
        if math.isnan(ratio):
            items.append(Item("volume", "Hajm", None, f"{vlabel} o'rtachasi nol"))
        else:
            items.append(Item("volume", "Hajm", ratio >= 1.0, f"{vlabel} = {ratio:.2f}x (o'rtacha 20 sham)"))

    # 9. Bozor strukturasi (1H swing nuqtalari): LONG — HH+HL, SHORT — LH+LL
    if len(highs) < 2 or len(lows) < 2:
        items.append(Item("structure", "Market structure", None, "tasdiqlangan swing nuqtalari yetarli emas"))
    else:
        hh, hl = highs[-1][1] > highs[-2][1], lows[-1][1] > lows[-2][1]
        if long:
            ok, txt = hh and hl, f"{'HH' if hh else 'LH'} + {'HL' if hl else 'LL'}"
        else:
            ok, txt = (not hh) and (not hl), f"{'HH' if hh else 'LH'} + {'HL' if hl else 'LL'}"
        items.append(Item("structure", "Market structure", ok, txt))

    # 10. R/R (xarajatdan keyin)
    items.append(Item("rr", "Risk/Reward", rr_net >= min_rr, f"1:{rr_net:.2f} (xarajatdan keyin; kamida 1:{min_rr:g})"))

    score = sum(1 for it in items if it.ok)
    missing = [it.key for it in items if it.ok is None]
    by = {it.key: it for it in items}
    blocked = None
    miss_core = [k for k in CORE if by[k].ok is None]
    if miss_core:
        blocked = "ma'lumot yetarli emas: " + ", ".join(by[k].label for k in miss_core)
    elif h4.ok is False and (trend_of(f4h) in (TREND_UP, TREND_DOWN)):
        blocked = f"4H trend signalga teskari ({side} vs {trend_of(f4h)})"
    return Score(score, items, tier_of(score, {k: it.ok for k, it in by.items()}, blocked), blocked, missing)


def tier_of(score: int, ok: dict[str, bool | None], blocked: str | None = None) -> str:
    """Ball -> daraja. 6-7 ball faqat 4H+1H trend, hajm va R/R hammasi bajarilgan bo'lsa (qo'shimcha tasdiq) yuboriladi."""
    if blocked:
        return "BLOCKED"
    if score >= 8:
        return "STRONG"
    if score >= 6:
        return "CONFIRM" if all(ok.get(k) for k in ("h4_trend", "h1_trend", "volume", "rr")) else "WATCH"
    return "WATCH" if score >= 4 else "DROP"
