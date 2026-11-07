"""Korrelyatsiya bo'yicha umumiy risk (V21). Faqat sof funksiyalar — hozircha savdo oqimiga ULANMAGAN (egasi tasdig'idan keyin).

Muammo: BTC va ETH (korrelyatsiya ~0.9), USTEC va US500 (~0.95), EURUSD va GBPUSD (~0.87) bitta xavfning ikki nusxasi.
Har birida 1% risk — aslida ~2% bitta g'oyaga.

Mexanizm: ochiq pozitsiyalar va yangi nomzod uchun samarali risk
    R_eff = sqrt( sum_i sum_j  rho_ij * s_i * s_j * r_i * r_j )
bunda r — pozitsiya riski (% hisob), s = +1 (long) / -1 (short), rho — kunlik daromadlar korrelyatsiyasi.
Qarama-qarshi yo'nalish xavfni kamaytiradi (hedge). Nomzod R_eff > MAX_EFFECTIVE_RISK bo'lsa rad etiladi.

MAX_EFFECTIVE_RISK = 1.75%: bu ~3 ta mustaqil 1% pozitsiyaning sqrt(3)=1.73% ga teng. Mustaqil 3 ta ruxsat etiladi;
BTC+ETH bir yo'nalishda (1.95%) rad etiladi; BTC+XAU (1.69%) ruxsat. Korrelyatsiya matritsasi 2021-11..2026-11 kunlik
logaritmik daromadlardan (5 yil va oxirgi 250 kunning kattasi, ya'ni konservativ); qiymatlar research/corr.py dan.
Matritsada yo'q juftlik uchun UNKNOWN_RHO = 0.5 (konservativ) ishlatiladi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MAX_EFFECTIVE_RISK = 1.75
UNKNOWN_RHO = 0.5

_PAIRS = {
    ("BTC", "ETH"): 0.91, ("BTC", "XAU"): 0.42, ("BTC", "USTEC"): 0.55, ("BTC", "US500"): 0.58, ("BTC", "EURUSD"): 0.29,
    ("BTC", "GBPUSD"): 0.37, ("ETH", "XAU"): 0.43, ("ETH", "USTEC"): 0.54, ("ETH", "US500"): 0.57, ("ETH", "EURUSD"): 0.35,
    ("ETH", "GBPUSD"): 0.40, ("XAU", "USTEC"): 0.38, ("XAU", "US500"): 0.42, ("XAU", "EURUSD"): 0.49, ("XAU", "GBPUSD"): 0.46,
    ("USTEC", "US500"): 0.95, ("USTEC", "EURUSD"): 0.32, ("USTEC", "GBPUSD"): 0.35, ("US500", "EURUSD"): 0.40,
    ("US500", "GBPUSD"): 0.44, ("EURUSD", "GBPUSD"): 0.87,
}
RHO = {frozenset(k): v for k, v in _PAIRS.items()}

_ALIAS = {"BTCUSDT": "BTC", "BTCUSD": "BTC", "ETHUSDT": "ETH", "ETHUSD": "ETH", "XAUUSD": "XAU", "GOLD": "XAU",
          "USTEC": "USTEC", "NAS100": "USTEC", "US100": "USTEC", "US500": "US500", "SPX500": "US500", "SP500": "US500",
          "EURUSD": "EURUSD", "GBPUSD": "GBPUSD"}


def canon(symbol: str) -> str:
    """'BTCUSDm', 'BTC/USD', 'USTEC_x100m' -> 'BTC', 'BTC', 'USTEC'. Noma'lum simvol — katta harfli o'zi."""
    s = "".join(ch for ch in symbol.upper() if ch.isalnum() or ch == "_").replace("_X100", "").replace("_X10", "")
    if s.endswith("M") and (s[:-1] in _ALIAS or len(s) == 7):  # broker "m" qo'shimchasi (EURUSDm, USDJPYm)
        s = s[:-1]
    return _ALIAS.get(s, s)


def rho(a: str, b: str) -> tuple[float, bool]:
    """(korrelyatsiya, ma'lum_mi). Bir xil aktiv — 1.0."""
    a, b = canon(a), canon(b)
    if a == b:
        return 1.0, True
    v = RHO.get(frozenset((a, b)))
    return (v, True) if v is not None else (UNKNOWN_RHO, False)


@dataclass(frozen=True)
class Position:
    symbol: str
    direction: str  # LONG | SHORT (yoki buy | sell)
    risk_pct: float  # hisobning %, SL gacha

    @property
    def sign(self) -> int:
        return 1 if self.direction.upper() in ("LONG", "BUY") else -1


def effective_risk(positions: list[Position]) -> float:
    total = 0.0
    for a in positions:
        for b in positions:
            total += rho(a.symbol, b.symbol)[0] * a.sign * b.sign * a.risk_pct * b.risk_pct
    return math.sqrt(max(total, 0.0))


@dataclass
class Verdict:
    allowed: bool
    effective_risk: float
    reason: str
    unknown_pairs: list[str]


def check(open_positions: list[Position], candidate: Position, limit: float = MAX_EFFECTIVE_RISK) -> Verdict:
    allp = [*open_positions, candidate]
    eff = effective_risk(allp)
    unknown = sorted({f"{canon(a.symbol)}/{canon(b.symbol)}" for i, a in enumerate(allp) for b in allp[i + 1:]
                      if not rho(a.symbol, b.symbol)[1]})
    if eff > limit + 1e-9:
        return Verdict(False, round(eff, 3), f"samarali risk {eff:.2f}% > {limit:.2f}% (korrelyatsiyali pozitsiyalar "
                                             "bitta xavfni takrorlaydi)", unknown)
    return Verdict(True, round(eff, 3), f"samarali risk {eff:.2f}% <= {limit:.2f}%", unknown)
