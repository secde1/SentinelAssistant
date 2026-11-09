"""Aktiv zona topish: sof hisob-kitob (LLM yo'q) — zona haqiqiy shamlardan chiqadi, taxmin emas.

Har detektor bitta xodimga (ZONE-1..5) tegishli. Kirish: YOPILGAN shamlar (eski -> yangi). Chiqish: zonalar ro'yxati.
Zona: {detector, kind, tf, low, high, strength, note}. "Aktiv": oxirgi yopilish narxi zona ichida yoki ATR*near_atr
masofada (classify). Bu modul buyurtma bermaydi va signal ham yaratmaydi.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


def atr(bars: list[Bar], n: int = 14) -> float | None:
    if len(bars) < n + 1:
        return None
    trs = [max(b.high - b.low, abs(b.high - p.close), abs(b.low - p.close)) for p, b in zip(bars, bars[1:])]
    return sum(trs[-n:]) / n


def pivots(bars: list[Bar], k: int = 3) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing yuqori/pastlar: atrofidagi k shamdan baland/past (oxirgi k sham tasdiqlanmagan — olinmaydi)."""
    highs, lows = [], []
    for i in range(k, len(bars) - k):
        w = bars[i - k:i + k + 1]
        if bars[i].high == max(b.high for b in w) and sum(b.high == bars[i].high for b in w) == 1:
            highs.append((i, bars[i].high))
        if bars[i].low == min(b.low for b in w) and sum(b.low == bars[i].low for b in w) == 1:
            lows.append((i, bars[i].low))
    return highs, lows


def _cluster(points: list[tuple[int, float]], tol: float) -> list[list[tuple[int, float]]]:
    groups: list[list[tuple[int, float]]] = []
    for p in sorted(points, key=lambda x: x[1]):
        if groups and p[1] - groups[-1][-1][1] <= tol:
            groups[-1].append(p)
        else:
            groups.append([p])
    return groups


def _zone(det: str, kind: str, tf: str, low: float, high: float, strength: float, note: str) -> dict:
    return {"detector": det, "kind": kind, "tf": tf, "low": float(low), "high": float(high), "strength": round(strength, 1), "note": note}


def snr(bars: list[Bar], tf: str, det: str = "ZONE-1", k: int = 3, min_touches: int = 3, width_atr: float = 0.25) -> list[dict]:
    """Qo'llab-quvvatlash/qarshilik: bir daraja atrofida kamida `min_touches` ta swing."""
    a = atr(bars)
    if not a:
        return []
    highs, lows = pivots(bars, k)
    out = []
    price = bars[-1].close
    for grp in _cluster(highs + lows, 0.4 * a):
        if len(grp) < min_touches:
            continue
        lvl = sum(p for _, p in grp) / len(grp)
        kind = "support" if lvl <= price else "resistance"
        recent = sum(1 for i, _ in grp if i >= len(bars) - 120)
        out.append(_zone(det, kind, tf, lvl - width_atr * a, lvl + width_atr * a, len(grp) * 2 + recent, f"{len(grp)} marta tegilgan daraja"))
    return out


def rng(bars: list[Bar], tf: str, det: str = "ZONE-2", n: int = 24, max_atr: float = 3.0) -> list[dict]:
    """Siqilish/diapazon: oxirgi n shamning umumiy balandligi <= max_atr * ATR."""
    a = atr(bars)
    if not a or len(bars) < n + 15:
        return []
    w = bars[-n:]
    lo, hi = min(b.low for b in w), max(b.high for b in w)
    if hi - lo > max_atr * a:
        return []
    inside = sum(1 for b in w if lo <= b.close <= hi)
    return [_zone(det, "range", tf, lo, hi, 4 + 6 * (1 - (hi - lo) / (max_atr * a)) + inside / n * 2, f"{n} sham tor diapazon ({(hi - lo) / a:.1f} ATR)")]


def impulse_origin(bars: list[Bar], tf: str, det: str = "ZONE-4", mult: float = 1.8, lookback: int = 150) -> list[dict]:
    """Kuchli impuls boshlangan joy (order-block turi): impuls shamidan oldingi sham diapazoni. Narx uni yopilish bilan
    teshib o'tgan bo'lsa (mitigated) — olinmaydi."""
    out = []
    start = max(15, len(bars) - lookback)
    for i in range(start, len(bars) - 1):
        a = atr(bars[:i])
        if not a:
            continue
        c, base = bars[i], bars[i - 1]
        body = abs(c.close - c.open)
        if body < mult * a:
            continue
        bull = c.close > c.open
        lo, hi = base.low, base.high
        later = bars[i + 1:]
        if bull and any(x.close < lo for x in later):
            continue
        if (not bull) and any(x.close > hi for x in later):
            continue
        out.append(_zone(det, "demand" if bull else "supply", tf, lo, hi, 3 + body / a, f"impuls {body / a:.1f} ATR dan boshlangan joy"))
    return out[-4:]


def liquidity(bars: list[Bar], tf: str, det: str = "ZONE-5", k: int = 2, tol_atr: float = 0.12, lookback: int = 150) -> list[dict]:
    """Likvidlik: teng yuqori/pastlar (stop'lar to'plangan joy) — kamida 2 ta deyarli bir xil swing."""
    a = atr(bars)
    if not a:
        return []
    cut = len(bars) - lookback
    highs, lows = [p for p in pivots(bars, k)[0] if p[0] >= cut], [p for p in pivots(bars, k)[1] if p[0] >= cut]
    out = []
    for pts, kind in ((highs, "liq-high"), (lows, "liq-low")):
        for grp in _cluster(pts, tol_atr * a):
            if len(grp) < 2:
                continue
            lvl = sum(p for _, p in grp) / len(grp)
            out.append(_zone(det, kind, tf, lvl - 0.1 * a, lvl + 0.1 * a, len(grp) * 3, f"{len(grp)} ta teng {'yuqori' if 'high' in kind else 'past'} — stop'lar to'plangan"))
    return out


def classify(zone: dict, price: float, a: float, near_atr: float = 0.5) -> tuple[str, float]:
    """(holat, masofa ATR da): 'active' — narx zona ichida yoki near_atr*ATR yaqinida; aks holda 'fresh'. Teshib o'tgan — 'broken'."""
    lo, hi = zone["low"], zone["high"]
    if lo <= price <= hi:
        return "active", 0.0
    dist = (lo - price if price < lo else price - hi) / a if a else 99.0
    if zone["kind"] in ("support", "demand", "liq-low") and price < lo - 0.5 * a:
        return "broken", dist
    if zone["kind"] in ("resistance", "supply", "liq-high") and price > hi + 0.5 * a:
        return "broken", dist
    return ("active" if dist <= near_atr else "fresh"), dist


# xodim -> (detektor, kerakli taymfreym)
DETECTORS = {
    "ZONE-1": (snr, "1h"),
    "ZONE-2": (rng, "1h"),
    "ZONE-3": (partial(snr, min_touches=2), "4h"),
    "ZONE-4": (impulse_origin, "1h"),
    "ZONE-5": (liquidity, "1h"),
}
