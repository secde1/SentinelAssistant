"""Tarixiy sinov va eksperimentlar. Live kuzatuv bilan BIR XIL natija dvigateli (outcomes.simulate) ishlatiladi.

Look-ahead yo'q: signal i-shamgacha (shu jumladan) ma'lumotdan hisoblanadi (indikatorlar causal, swinglar o'ngdan
tasdiqlangan), kirish faqat i+1-shamdan boshlab. Bir vaqtning o'zida bitta pozitsiya. Xarajatlar (spread +
komissiya) hisobga olinadi. Eksperiment: vaqt bo'yicha in-sample (70%) / out-of-sample (30%), yangi versiya eski bilan
OOS da solishtiriladi. Natija hech qachon avtomatik faollashtirilmaydi; muvaffaqiyatsiz eksperimentlar ham saqlanadi.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

from .data import TF_SECONDS, Candle
from .db import dumps, utcnow
from .indicators import Features
from .outcomes import FINAL, Scenario, simulate
from .strategies import NoSetup, StrategySpec, classify_regime

MIN_OOS_TRADES = 30
MIN_IMPROVEMENT_R = 0.05


@dataclass
class Trade:
    signal_ts: str
    direction: str
    status: str
    r: float | None


def run(spec: StrategySpec, candles: list[Candle], *, spread_fn, commission: float, start: int = 220,
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
        sc = Scenario("BT", res.direction, res.entry_type, res.entry, res.sl, res.tp, res.invalidation, data_end,
                      data_end, data_end + timedelta(seconds=sec * res.valid_bars), max_hold, _tf(sec),
                      spread_fn(res.entry), commission)
        future = candles[i + 1:min(end, i + 2 + res.valid_bars + max_hold) + 1]  # yakunlanish uchun yetarli oyna
        st = simulate(sc, future)  # mayda ma'lumotsiz: bir shamdagi noaniqlik -> AMBIGUOUS_DATA
        if st.status not in FINAL:
            break  # ma'lumot tugadi — yakunlanmagan savdo hisobga olinmaydi
        trades.append(Trade(candles[i].ts.isoformat(), res.direction, st.status, st.r_multiple))
        # keyingi signal faqat shu ssenariy yopilgandan keyin (bir vaqtda bitta pozitsiya)
        close_ts = st.exit_time or (st.events[-1]["ts"] if st.events else data_end)
        j = i + 1
        while j < end and candles[j].ts < close_ts:
            j += 1
        i = max(j, i + 1)
    return trades


def _tf(sec: int) -> str:
    return {60: "1m", 300: "5m", 900: "15m", 1800: "30m", 3600: "1h", 14400: "4h", 86400: "1d"}[sec]


def metrics(trades: list[Trade]) -> dict:
    resolved = [t for t in trades if t.status in ("TP_HIT", "SL_HIT")]
    rs = [t.r for t in resolved if t.r is not None]
    curve = peak = dd = 0.0
    for r in rs:
        curve += r
        peak = max(peak, curve)
        dd = max(dd, peak - curve)
    wins = [t for t in resolved if t.status == "TP_HIT"]
    win_r = [t.r for t in wins if t.r is not None]
    loss_r = [abs(t.r) for t in resolved if t.status == "SL_HIT" and t.r is not None]
    return {"signals": len(trades), "resolved": len(resolved), "tp": len(wins), "sl": len(resolved) - len(wins),
            "ambiguous": sum(1 for t in trades if t.status == "AMBIGUOUS_DATA"),
            "expired": sum(1 for t in trades if t.status == "EXPIRED"),
            "not_triggered": sum(1 for t in trades if t.status in ("NOT_TRIGGERED", "CANCELLED")),
            "win_rate": round(len(wins) / len(resolved) * 100, 1) if resolved else None,
            "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
            "avg_reward_risk": round((sum(win_r) / len(win_r)) / (sum(loss_r) / len(loss_r)), 2)
            if win_r and loss_r else None,
            "max_drawdown_r": round(dd, 3)}


def walk_forward(spec: StrategySpec, candles: list[Candle], *, spread_fn, commission: float,
                 split: float = 0.7) -> dict:
    cut = int(len(candles) * split)
    ins = run(spec, candles, spread_fn=spread_fn, commission=commission, end=cut)
    oos = run(spec, candles, spread_fn=spread_fn, commission=commission, start=max(cut, 220))
    return {"in_sample": metrics(ins), "out_of_sample": metrics(oos),
            "periods": {"start": candles[0].ts.isoformat(), "split": candles[cut].ts.isoformat(),
                        "end": candles[-1].end.isoformat(), "bars": len(candles)}}


def verdict(base: dict, cand: dict) -> tuple[str, str]:
    b, c = base["out_of_sample"], cand["out_of_sample"]
    if b["resolved"] < MIN_OOS_TRADES or c["resolved"] < MIN_OOS_TRADES:
        return "inconclusive", (f"OOS namuna kam (asosiy {b['resolved']}, nomzod {c['resolved']} < {MIN_OOS_TRADES}) — "
                                "xulosa chiqarilmaydi")
    be, ce = b["expectancy_r"] or 0.0, c["expectancy_r"] or 0.0
    if ce > be + MIN_IMPROVEMENT_R and ce > 0 and c["max_drawdown_r"] <= max(b["max_drawdown_r"] * 1.25, 1.0):
        return "supported", f"OOS expectancy {be:+.3f}R -> {ce:+.3f}R, pasayish {b['max_drawdown_r']} -> " \
                            f"{c['max_drawdown_r']}R"
    return "not_supported", f"OOS expectancy {be:+.3f}R -> {ce:+.3f}R — dalil o'zgarishni qo'llab-quvvatlamaydi"


def record_experiment(db, memory, *, strategy_id: str, base: StrategySpec, cand: StrategySpec, problem: str,
                      hypothesis: str, data_info: dict, costs: dict, base_res: dict, cand_res: dict) -> dict:
    v, why = verdict(base_res, cand_res)
    day = utcnow()[:10].replace("-", "")
    exp_id = f"EXP-{day}-{db.next_counter('experiment:' + day):02d}"
    results = {"base": base_res, "candidate": cand_res, "explanation": why}
    db.execute("INSERT INTO experiments(experiment_id, created_at, strategy_id, base_version, candidate_version, problem, "
               "hypothesis, data, costs, results, verdict, notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
               (exp_id, utcnow(), strategy_id, base.version, cand.version, problem, hypothesis, dumps(data_info),
                dumps(costs), dumps(results), v, "avtomatik faollashtirilmaydi — egasi /trading_faollashtir bilan"))
    rec = {"experiment_id": exp_id, "strategy_id": strategy_id, "base_version": base.version,
           "candidate_version": cand.version, "problem": problem, "hypothesis": hypothesis, "data": data_info,
           "costs": costs, "results": results, "verdict": v}
    if memory is not None:
        (memory.experiments / f"{exp_id}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), "utf-8")
    return rec


def library_stats(db, spec: StrategySpec, symbol: str, timeframe: str, candles: list[Candle], *, spread_fn,
                  commission: float) -> dict:
    """Kutubxona uchun tarixiy sinov natijasi (sinov davri, namuna, xarajat bilan)."""
    m = metrics(run(spec, candles, spread_fn=spread_fn, commission=commission))
    db.execute("INSERT INTO strategy_stats(strategy_id, version, symbol, timeframe, period_start, period_end, sample_size, "
               "win_rate, avg_rr, expectancy, max_dd, ambiguous, costs, source, created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (spec.strategy_id, spec.version, symbol, timeframe, candles[0].ts.isoformat(), candles[-1].end.isoformat(),
                m["resolved"], m["win_rate"], m["avg_reward_risk"], m["expectancy_r"], m["max_drawdown_r"],
                m["ambiguous"], dumps({"commission_per_side": commission, "spread_model": "settings"}),
                "backtest (bir xil natija dvigateli, 1m aniqlashtirishsiz)", utcnow()))
    return m


__all__ = ["run", "metrics", "walk_forward", "verdict", "record_experiment", "library_stats", "TF_SECONDS"]
