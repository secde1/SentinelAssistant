"""Qog'oz savdo statistikasi. Hal bo'lmagan ssenariylar (PENDING/ACTIVE/AMBIGUOUS/EXPIRED/...) yutuq foizi
maxrajiga KIRMAYDI: win rate = TP / (TP + SL). Har ko'rsatkich yonida namuna hajmi va cheklov."""
from __future__ import annotations

from collections import defaultdict

SMALL_SAMPLE = 30


def _rows(db, date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    sql = ("SELECT a.analysis_id, a.local_date, a.created_at, a.symbol, a.timeframe, a.session, a.kind, a.strategy_id, "
           "a.strategy_version, a.direction, o.status, o.r_multiple, o.exit_time, o.entry_time "
           "FROM analyses a LEFT JOIN outcomes o ON o.analysis_id = a.analysis_id WHERE 1=1")
    params: list = []
    if date_from:
        sql += " AND a.local_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND a.local_date <= ?"
        params.append(date_to)
    return db.query(sql + " ORDER BY a.created_at", params)


def summarize(rows: list[dict]) -> dict:
    trades = [r for r in rows if r["kind"] == "TRADE"]
    st = defaultdict(int)
    for r in trades:
        st[r["status"] or "PENDING"] += 1
    resolved = [r for r in trades if r["status"] in ("TP_HIT", "SL_HIT")]
    rs = [r["r_multiple"] for r in resolved if r["r_multiple"] is not None]
    wins = st["TP_HIT"]
    # Maksimal pasayish: yopilish vaqti bo'yicha jamlangan R egri chizig'i.
    curve, peak, max_dd = 0.0, 0.0, 0.0
    for r in sorted(resolved, key=lambda x: x["exit_time"] or ""):
        curve += r["r_multiple"] or 0.0
        peak = max(peak, curve)
        max_dd = max(max_dd, peak - curve)
    triggered = sum(st[k] for k in ("ACTIVE_SIMULATION", "TP_HIT", "SL_HIT", "EXPIRED")) + \
        sum(1 for r in trades if r["status"] == "AMBIGUOUS_DATA" and r["entry_time"])
    n_res = len(resolved)
    out = {
        "total_analyses": len(rows),
        "no_trade": sum(1 for r in rows if r["kind"] == "NO_TRADE"),
        "trade_scenarios": len(trades),
        "valid_entries": triggered,
        "not_triggered": st["NOT_TRIGGERED"],
        "cancelled": st["CANCELLED"],
        "pending": st["PENDING"],
        "active": st["ACTIVE_SIMULATION"],
        "tp_hits": wins,
        "sl_hits": st["SL_HIT"],
        "expired": st["EXPIRED"],
        "ambiguous": st["AMBIGUOUS_DATA"],
        "resolved": n_res,
        "win_rate": round(wins / n_res * 100, 1) if n_res else None,
        "avg_r": round(sum(rs) / len(rs), 3) if rs else None,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "total_r": round(sum(rs), 3) if rs else 0.0,
        "max_drawdown_r": round(max_dd, 3),
        "small_sample": n_res < SMALL_SAMPLE,
    }
    expired_r = [r["r_multiple"] for r in trades if r["status"] == "EXPIRED" and r["r_multiple"] is not None]
    out["expired_avg_r"] = round(sum(expired_r) / len(expired_r), 3) if expired_r else None
    return out


def breakdown(rows: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] != "TRADE":
            continue
        k = r[key] if key != "strategy" else f"{r['strategy_id']} v{r['strategy_version']}"
        groups[str(k)].append(r)
    out = []
    for k, rs in sorted(groups.items()):
        s = summarize(rs)
        out.append({"key": k, "scenarios": s["trade_scenarios"], "resolved": s["resolved"], "tp": s["tp_hits"],
                    "sl": s["sl_hits"], "win_rate": s["win_rate"], "expectancy_r": s["expectancy_r"],
                    "max_drawdown_r": s["max_drawdown_r"], "small_sample": s["small_sample"]})
    return out


def performance(db, date_from: str | None = None, date_to: str | None = None) -> dict:
    rows = _rows(db, date_from, date_to)
    return {
        "summary": summarize(rows),
        "by_strategy": breakdown(rows, "strategy"),
        "by_instrument": breakdown(rows, "symbol"),
        "by_session": breakdown(rows, "session"),
        "by_timeframe": breakdown(rows, "timeframe"),
        "limitations": [
            f"Yutuq foizi faqat hal bo'lgan (TP/SL) ssenariylar bo'yicha; {SMALL_SAMPLE} tadan kam namuna statistik "
            "jihatdan ishonchsiz.",
            "AMBIGUOUS_DATA, EXPIRED, NOT_TRIGGERED, CANCELLED yutuq foiziga kirmaydi.",
            "Natijalar simulyatsiya: haqiqiy ijroda slipaj va likvidlik farq qilishi mumkin.",
        ],
    }


def equity_curve(db) -> list[dict]:
    rows = db.query("SELECT o.analysis_id, o.exit_time, o.r_multiple, a.strategy_id FROM outcomes o JOIN analyses a "
                    "ON a.analysis_id=o.analysis_id WHERE o.status IN ('TP_HIT','SL_HIT') ORDER BY o.exit_time")
    total, out = 0.0, []
    for r in rows:
        total += r["r_multiple"] or 0.0
        out.append({"ts": r["exit_time"], "analysis_id": r["analysis_id"], "r": r["r_multiple"],
                    "cum_r": round(total, 3), "strategy": r["strategy_id"]})
    return out
