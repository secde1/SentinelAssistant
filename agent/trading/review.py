"""SL hodisasi tahlili. Har zarar avtomatik "agent xatosi" EMAS va bitta zarar strategiyani nosoz qilmaydi.

Tartib: asl tahlil -> strategiya versiyasi -> bozor konteksti -> kirish qoidasi bajarilganmi (qayta hisoblash) ->
volatillik va spread -> yaqin iqtisodiy hodisalar -> zaif joylar -> tasnif.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from .data import TF_SECONDS, DataUnavailable
from .db import dumps, utcnow
from .indicators import Features
from .strategies import NoSetup, Registry, classify_regime

NORMAL, INVALID, REGIME, VOLATILITY, DATA, EXECUTION, UNCLEAR = (
    "Normal strategy loss", "Invalid setup", "Poor market-regime match", "Incorrect volatility assumption",
    "Data-quality problem", "Execution-model problem", "Unclear cause")


def classify(checks: dict) -> tuple[str, list[str]]:
    """Faktlardan tasnif (sof funksiya — testlanadi)."""
    factors = []
    if checks.get("data_gaps"):
        factors.append(f"savdo oralig'ida {checks['data_gaps']} ta sham yo'q")
    if checks.get("reproduced") is False:
        factors.append("strategiya qoidasi shu ma'lumotda qayta tekshirilganda setup chiqmadi")
    if checks.get("levels_match") is False:
        factors.append("qayta hisoblangan darajalar e'lon qilinganidan farq qiladi")
    if checks.get("regime_ok") is False:
        factors.append(f"rejim {checks.get('regime')} strategiyaning mos rejimlari ichida emas")
    if checks.get("sl_atr") is not None and checks["sl_atr"] < 0.7:
        factors.append(f"SL masofasi {checks['sl_atr']:.2f} ATR — shovqin darajasidan kichik")
    if checks.get("atr_spike") is not None and checks["atr_spike"] > 1.8:
        factors.append(f"savdo davomida ATR {checks['atr_spike']:.1f} barobar oshgan")
    if checks.get("cost_r") is not None and checks["cost_r"] > 0.25:
        factors.append(f"xarajat {checks['cost_r']:.2f}R — ijro modeli uchun katta")
    if checks.get("events"):
        factors.append("yaqin yuqori ta'sirli hodisa(lar): " + "; ".join(e["title"] for e in checks["events"][:3]))
    if checks.get("data_gaps"):
        return DATA, factors
    if checks.get("reproduced") is None:
        return UNCLEAR, factors + ["qoidani qayta tekshirish uchun ma'lumot olinmadi"]
    if checks.get("reproduced") is False:
        return INVALID, factors
    if checks.get("levels_match") is False:
        return DATA, factors
    if checks.get("regime_ok") is False:
        return REGIME, factors
    if (checks.get("sl_atr") is not None and checks["sl_atr"] < 0.7) or \
            (checks.get("atr_spike") is not None and checks["atr_spike"] > 1.8 and checks.get("events")):
        return VOLATILITY, factors
    if checks.get("cost_r") is not None and checks["cost_r"] > 0.25:
        return EXECUTION, factors
    if checks.get("entry_met") is True:
        return NORMAL, factors or ["qoidalar bajarilgan, rejim mos, volatillik taxmini oqilona — oddiy strategik zarar"]
    return UNCLEAR, factors


def review_sl(db, market, settings, registry: Registry, analysis_id: str, calendar=None) -> dict:
    row = db.analysis(analysis_id)
    out = db.outcome(analysis_id)
    if row is None or out is None or out["status"] != "SL_HIT":
        raise ValueError("SL hodisasi topilmadi")
    rec = json.loads(row["payload"])
    spec = registry.get(row["strategy_id"], row["strategy_version"])
    checks: dict = {"entry_met": out["entry_time"] is not None, "regime": rec["regime"]["trend"],
                    "regime_ok": spec is not None and rec["regime"]["trend"] in spec.regimes}
    sec = TF_SECONDS[row["timeframe"]]
    data_end = datetime.fromisoformat(row["data_ts"])
    atr0 = rec["evidence"].get("atr14") or rec["regime"].get("atr14")
    risk = abs(row["entry"] - row["sl"])
    if atr0:
        checks["sl_atr"] = round(risk / atr0, 3)
    checks["cost_r"] = out["cost_r"]
    try:  # 1) qoidani o'sha paytdagi ma'lumot bilan qayta tekshirish
        hist = market.history(row["symbol"], row["timeframe"], int(settings["history_bars"]), end=data_end, need=230,
                              check_stale=False)
        f = Features.build(hist.candles)
        i = len(f) - 1
        regime = classify_regime(f, i)
        res = spec.evaluate(f, i, regime) if spec else None
        checks["reproduced"] = res is not None and not isinstance(res, NoSetup)
        if checks["reproduced"]:
            tol = 1e-6 * max(1.0, abs(row["entry"]))
            checks["levels_match"] = all(abs(a - b) <= tol + 1e-9 * abs(b) for a, b in
                                         ((res.entry, row["entry"]), (res.sl, row["sl"]), (res.tp, row["tp"])))
    except (DataUnavailable, ValueError) as exc:
        checks["reproduced"] = None
        checks["reproduce_error"] = str(exc)
    try:  # 2) savdo oralig'idagi volatillik va ma'lumot bo'shliqlari
        entry_t = datetime.fromisoformat(out["entry_time"])
        exit_t = datetime.fromisoformat(out["exit_time"])
        window = market.after(row["symbol"], row["timeframe"], entry_t - timedelta(seconds=sec * 20),
                              limit=int((exit_t - entry_t).total_seconds() // sec) + 25)
        expected = int((window[-1].ts - window[0].ts).total_seconds() // sec) + 1 if window else 0
        checks["data_gaps"] = max(0, expected - len(window)) if row["symbol"].endswith("USDT") else 0
        trs = [max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close)) for p, c in zip(window, window[1:])
               if c.ts >= entry_t]
        if atr0 and trs:
            checks["atr_spike"] = round((sum(trs) / len(trs)) / atr0, 2)
    except (DataUnavailable, ValueError, TypeError) as exc:
        checks["window_error"] = str(exc)
    if calendar is not None and out.get("exit_time"):
        ccy = ("USD",) if row["symbol"].endswith("USDT") else tuple(x for x in row["symbol"].split("/") if len(x) == 3)
        checks["events"] = calendar.near(datetime.fromisoformat(out["exit_time"]), 2.0, ccy or ("USD",))
        if checks["events"] is None:
            checks["events_note"] = "iqtisodiy kalendar shu davr uchun mavjud emas"
    classification, factors = classify(checks)
    review = {"analysis_id": analysis_id, "strategy_id": row["strategy_id"], "strategy_version": row["strategy_version"],
              "classification": classification, "factors": factors, "checks": checks}
    db.execute("INSERT OR REPLACE INTO sl_reviews(analysis_id, created_at, strategy_id, strategy_version, "
               "classification, factors, evidence) VALUES(?,?,?,?,?,?,?)",
               (analysis_id, utcnow(), row["strategy_id"], row["strategy_version"], classification, dumps(factors),
                dumps(checks)))
    return review
