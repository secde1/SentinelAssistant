"""AUTO rejim yordamchilari (V28): lot hisobi (1% risk), zdelkani ikkiga bo'lish, aylanma o'chirgich. Sof funksiyalar.

Zdelka guruhi: bitta signal -> 2 ta pozitsiya (bir xil SL). A — yaqin TP (tp1_r * R), tezroq yopiladi; B — signalning to'liq TP
(odatda 2R), TP gacha kutadi. Umumiy risk risk_pct (har yarim lot ~ yarim risk). Lot brokerning qadamiga pastga yaxlitlanadi va
`max_lot` bilan cheklanadi, shuning uchun haqiqiy risk ba'zan belgilanganidan past bo'ladi (xabarda ko'rsatiladi).
Hisob faqat DEMO da ishlatiladi (DemoTrader hisob turini har safar tekshiradi); bu modul tarmoqqa chiqmaydi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


class PlanRefused(Exception):
    """Zdelka rejasi tuzilmadi (sababi matnda)."""


@dataclass
class Leg:
    tag: str  # "A" | "B" | "S" (bo'linmagan)
    lot: float
    tp: float


@dataclass
class GroupPlan:
    legs: list[Leg]
    sl: float
    sl_adjusted: bool
    dist: float
    risk_money: float  # rejalashtirilgan risk (balans * risk_pct)
    risk_actual: float  # lot yaxlitlangandan va cheklangandan keyingi haqiqiy risk
    lot_total: float
    notes: list[str] = field(default_factory=list)


def _floor_step(x: float, step: float) -> float:
    if step <= 0:
        return x
    decimals = max(0, -int(math.floor(math.log10(step))) + 1) if step < 1 else 0
    return round(math.floor(x / step + 1e-9) * step, decimals)


def plan_group(*, side: str, price: float, sl: float, tp: float, atr: float | None, balance: float, spec: dict,
               risk_pct: float = 1.0, min_sl_atr: float = 1.0, min_rr: float = 1.5, tp1_r: float = 1.0, split: bool = True,
               max_lot: float = 0.10, spread: float = 0.0, max_spread_sl: float = 0.10,
               min_lot_fallback: bool = False, min_lot_max_risk_pct: float = 8.0) -> GroupPlan:
    """spec: tick_value, tick_size, volume_min, volume_step, volume_max, digits. Aks holda PlanRefused."""
    long = side == "buy"
    notes: list[str] = []
    if balance <= 0:
        raise PlanRefused("balans o'qilmadi yoki nolga teng")
    if (sl >= price) if long else (sl <= price):
        raise PlanRefused(f"SL {sl} narxning noto'g'ri tomonida")
    if (tp <= price) if long else (tp >= price):
        raise PlanRefused(f"TP {tp} narxning noto'g'ri tomonida")
    digits = int(spec.get("digits", 5))
    dist, adjusted = abs(price - sl), False
    if atr and atr > 0 and dist < min_sl_atr * atr:  # SL juda yaqin: kamida min_sl_atr ATR (lot kichrayadi, risk saqlanadi)
        dist, adjusted = min_sl_atr * atr, True
        sl = round(price - dist if long else price + dist, digits)
        dist = abs(price - sl)
        notes.append(f"SL {min_sl_atr:g} ATR ga uzaytirildi: {sl}")
    rr = abs(tp - price) / dist
    if rr < min_rr:
        raise PlanRefused(f"R/R past: 1:{rr:.2f} < 1:{min_rr:g}")
    if spread and spread / dist > max_spread_sl:
        raise PlanRefused(f"spred riskning {spread / dist * 100:.0f}% i (chegara {max_spread_sl * 100:.0f}%)")
    tick_size, tick_value = float(spec.get("tick_size") or 0), float(spec.get("tick_value") or 0)
    if tick_size <= 0 or tick_value <= 0:
        raise PlanRefused("simvolning tick qiymati noma'lum — lot hisoblanmadi")
    per_unit = tick_value / tick_size  # 1 lot, narx 1 birlikka o'zgarsa — hisob valyutasida
    risk_money = balance * risk_pct / 100
    raw = risk_money / (dist * per_unit)
    step, vmin = float(spec.get("volume_step") or 0.01), float(spec.get("volume_min") or 0.01)
    cap = min(max_lot, float(spec.get("volume_max") or max_lot))
    if raw > cap:
        notes.append(f"lot {raw:.3f} -> {cap:g} (max_lot chegarasi): haqiqiy risk kichikroq")
    total = _floor_step(min(raw, cap), step)
    if total < vmin:
        if not min_lot_fallback:
            raise PlanRefused(f"1% risk uchun lot {raw:.4f} < broker minimumi {vmin} (balans kichik yoki SL juda uzoq)")
        pct = vmin * dist * per_unit / balance * 100
        if pct > min_lot_max_risk_pct:
            raise PlanRefused(f"minimal lot {vmin} riski {pct:.1f}% > chegara {min_lot_max_risk_pct:g}% — zdelka ochilmadi")
        total = vmin
        split = False
        notes.append(f"⚠️ minimal lot {vmin} ishlatildi: haqiqiy risk {pct:.1f}% (reja {risk_pct:g}%), bitta pozitsiya")
    tp1 = round(price + tp1_r * dist if long else price - tp1_r * dist, digits)
    tp2 = round(tp, digits)
    legs = [Leg("S", total, tp2)]
    if split and rr >= tp1_r + 0.25:
        a = _floor_step(total / 2, step)
        b = round(total - a, 8)
        if a >= vmin and b >= vmin:
            legs = [Leg("A", a, tp1), Leg("B", b, tp2)]
        else:
            notes.append("lot ikkiga bo'linmaydi (minimumdan kam) — bitta pozitsiya")
    elif split:
        notes.append("TP yaqin — bo'linmadi, bitta pozitsiya")
    return GroupPlan(legs, sl, adjusted, dist, risk_money, round(total * dist * per_unit, 2), total, notes)


def consecutive_losses(group_nets: list[float]) -> int:
    """Eng yangi yopilgan guruhlardan boshlab ketma-ket zararlar soni (group_nets — yangidan eskiga)."""
    n = 0
    for x in group_nets:
        if x < 0:
            n += 1
        else:
            break
    return n


def drawdown_pct(group_nets_old_to_new: list[float], start_balance: float) -> float:
    """Yig'ma natija egri chizig'ining cho'qqisidan hozirgi nuqtagacha pasayish, boshlang'ich balansning %."""
    if start_balance <= 0:
        return 0.0
    cum = peak = dd = 0.0
    for x in group_nets_old_to_new:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd / start_balance * 100
