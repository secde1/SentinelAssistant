"""Bitta tahlil: ma'lumot -> rejim -> strategiyani tanlash -> TRADE yoki NO-TRADE. Natija o'zgarmas yozuv.

Maqsad — sifatli tahlil, majburiy signal emas: hech qaysi strategiya sharti bajarilmasa yoki R/R past bo'lsa — NO-TRADE
(sababi bilan). Ma'lumot yo'q bo'lsa — tahlil umuman yaratilmaydi (DataUnavailable).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .data import TF_SECONDS, DataUnavailable, MarketData
from .db import TradingDB, dumps
from .indicators import Features
from .strategies import NoSetup, Registry, Setup, candidates, classify_regime

LIMITATIONS = [
    "Bu tadqiqot va qog'oz savdo (paper trading) ssenariysi — moliyaviy maslahat emas, foyda kafolatlanmaydi.",
    "Faqat yopilgan shamlar va texnik ko'rsatkichlarga asoslangan; yangiliklar va fundamental omillar baholanmagan.",
    "Strategiya gipoteza: tarixiy natija kelajakni kafolatlamaydi; namuna hajmi kutubxonada ko'rsatiladi.",
]


def session_of(dt: datetime) -> str:
    h = dt.astimezone(timezone.utc).hour
    if h < 7:
        return "Asia"
    if h < 12:
        return "London"
    if h < 16:
        return "London/New York overlap"
    if h < 21:
        return "New York"
    return "Off-hours (late US / early Asia)"


@dataclass
class Result:
    analysis: dict | None
    reason: str = ""


def new_analysis_id(db: TradingDB, local_date: str) -> str:
    n = db.next_counter(f"analysis:{local_date}")
    return f"TA-{local_date.replace('-', '')}-{n:02d}"


def build(db: TradingDB, settings, market: MarketData, registry: Registry, symbol: str, timeframe: str,
          now: datetime | None = None, memory=None) -> Result:
    now = now or datetime.now(timezone.utc)
    bundle = market.history(symbol, timeframe, int(settings["history_bars"]), need=230)  # DataUnavailable -> chaqiruvchi
    f = Features.build(bundle.candles)
    i = len(f) - 1
    try:
        regime = classify_regime(f, i)
    except ValueError as exc:
        raise DataUnavailable(str(exc)) from None
    active = registry.active()
    cands = candidates(regime, active)
    setups: list[Setup] = []
    reasons: list[str] = []
    for spec in cands:
        out = spec.evaluate(f, i, regime)
        if isinstance(out, NoSetup):
            reasons.append(f"{spec.strategy_id} v{spec.version}: {out.reason}")
            continue
        min_rr = float(spec.params.get("min_rr", settings["min_rr"]))  # strategiya o'z chegarasini belgilashi mumkin
        if out.rr < min_rr - 1e-9:
            reasons.append(f"{spec.strategy_id} v{spec.version}: R/R {out.rr:.2f} < {min_rr}")
            continue
        setups.append(out)
    local = settings.local(now)
    local_date = local.strftime("%Y-%m-%d")
    aid = new_analysis_id(db, local_date)
    sec = TF_SECONDS[timeframe]
    data_end = bundle.last_close_time
    spread = settings.spread_price(symbol, bundle.candles[-1].close)
    comm = settings.commission_rate(symbol)
    record = {
        "analysis_id": aid, "created_at": now.isoformat(timespec="seconds"), "local_date": local_date,
        "timezone": settings.get("timezone"), "local_time": local.isoformat(timespec="seconds"),
        "symbol": symbol, "timeframe": timeframe, "session": session_of(now),
        "regime": {"trend": regime.trend, "volatility": regime.volatility, **regime.readings},
        "data_source": bundle.source, "data_ts": data_end.isoformat(), "data_fetched_at": bundle.fetched_at.isoformat(
            timespec="seconds"), "last_close": bundle.candles[-1].close,
        "data_warnings": bundle.warnings,
        "costs": {"spread": spread, "commission_pct_per_side": comm * 100,
                  "model": "bid shamlar, long kirish ask=bid+spread; komissiya R dan ayiriladi"},
        "candidates": [s.strategy_id for s in cands], "rejected": reasons,
        "limitations": LIMITATIONS + ([f"Ma'lumot ogohlantirishi: {w}" for w in bundle.warnings]),
    }
    if setups:
        s = setups[0]
        risk = abs(s.entry - s.sl)
        cost_r = (comm * 2 * s.entry + spread) / risk if risk else 0.0
        record.update({
            "kind": "TRADE", "strategy_id": s.strategy_id, "strategy_version": s.version,
            "strategy_name": active[s.strategy_id].name, "direction": s.direction, "entry_type": s.entry_type,
            "entry": s.entry, "sl": s.sl, "tp": s.tp, "rr": round(s.rr, 2), "rr_net": round(s.rr - cost_r, 2),
            "invalidation": s.invalidation, "valid_until": (data_end + timedelta(seconds=sec * s.valid_bars)).isoformat(),
            "max_hold_bars": int(settings["max_hold_bars"]), "evidence": s.evidence, "assumptions": s.assumptions,
            "structure": s.structure,
            "other_setups": [{"strategy_id": o.strategy_id, "direction": o.direction, "rr": round(o.rr, 2)}
                             for o in setups[1:]],
        })
    else:
        record.update({
            "kind": "NO_TRADE", "strategy_id": None, "strategy_version": None, "direction": None, "entry_type": None,
            "entry": None, "sl": None, "tp": None, "rr": None, "rr_net": None, "invalidation": None, "valid_until": None,
            "max_hold_bars": None, "evidence": {"regime": regime.readings},
            "assumptions": ["Hech qaysi strategiya sharti bajarilmadi — kuzatish davom etadi"],
            "structure": f"Rejim {regime.label()}; mos strategiyalar: {', '.join(s.strategy_id for s in cands) or 'yoq'}",
            "no_trade_reasons": reasons or [f"{regime.trend} rejimi uchun faol strategiya yo'q"],
        })
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    record["content_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    row = dict(record)
    row["payload"] = payload
    row["limitations"] = record["limitations"]
    db.insert_analysis(row)
    if memory is not None:  # o'zgarmas JSON nusxa (faqat yaratish: 'x' rejimi)
        day_dir = memory.analyses / local_date
        day_dir.mkdir(parents=True, exist_ok=True)
        with open(day_dir / f"{aid}.json", "x", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, indent=1, default=str))
    return Result(record)


def load(db: TradingDB, analysis_id: str) -> dict | None:
    row = db.analysis(analysis_id)
    if row is None:
        return None
    rec = json.loads(row["payload"])
    rec["content_hash"] = row["content_hash"]
    return rec


def verify_integrity(db: TradingDB, analysis_id: str) -> bool:
    """Asl tahlil o'zgartirilmaganini tekshiradi (payload sha256 == content_hash)."""
    row = db.analysis(analysis_id)
    return bool(row) and hashlib.sha256(row["payload"].encode("utf-8")).hexdigest() == row["content_hash"]


__all__ = ["build", "load", "verify_integrity", "session_of", "dumps"]
