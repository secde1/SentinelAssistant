"""Kunlik va haftalik hisobot. Bugungi tahlillar natijasi va OLDINGI kunlardagi tahlillar natijasi alohida."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from . import analytics
from .db import dumps, utcnow

LABEL = "🧪 RESEARCH ONLY / PAPER TRADING — simulyatsiya natijalari, real savdo emas."


def _local_date(iso: str | None, tz) -> str | None:
    return datetime.fromisoformat(iso).astimezone(tz).strftime("%Y-%m-%d") if iso else None


def daily(db, settings, day: str, memory=None) -> tuple[str, dict]:
    tz = settings.tz
    analyses = db.query("SELECT analysis_id, kind, symbol, timeframe, strategy_id, strategy_version FROM analyses "
                        "WHERE local_date=? ORDER BY created_at", (day,))
    outs = db.query("SELECT o.*, a.local_date, a.symbol, a.strategy_id, a.strategy_version FROM outcomes o JOIN analyses a "
                    "ON a.analysis_id=o.analysis_id")
    triggered = [o for o in outs if _local_date(o["entry_time"], tz) == day]
    resolved = [o for o in outs if o["status"] in ("TP_HIT", "SL_HIT", "EXPIRED", "AMBIGUOUS_DATA", "NOT_TRIGGERED",
                                                   "CANCELLED") and _local_date(o["exit_time"] or o["updated_at"], tz)
                == day]
    today_res = [o for o in resolved if o["local_date"] == day]
    earlier_res = [o for o in resolved if o["local_date"] != day]

    def counts(rows):
        c = Counter(o["status"] for o in rows)
        return {k: c.get(k, 0) for k in ("TP_HIT", "SL_HIT", "EXPIRED", "AMBIGUOUS_DATA", "NOT_TRIGGERED", "CANCELLED")}
    unresolved = [o for o in outs if o["status"] in ("PENDING", "ACTIVE_SIMULATION")]
    perf = analytics.performance(db)
    sources = db.query("SELECT topic, title, url, evidence_type FROM research_sources WHERE substr(retrieved_at,1,10)=? "
                       "ORDER BY id", (day,))
    warnings = db.query("SELECT symbol, timeframe, kind, detail FROM data_warnings WHERE substr(ts,1,10)=?", (day,))
    exps = db.query("SELECT experiment_id, strategy_id, verdict FROM experiments WHERE substr(created_at,1,10)=?", (day,))
    reviews = db.query("SELECT strategy_id, classification FROM sl_reviews WHERE created_at >= ?",
                       ((datetime.fromisoformat(day) - timedelta(days=14)).isoformat(),))
    proposals = proposals_from_reviews(reviews)
    data = {"day": day, "analyses": len(analyses), "no_trade": sum(1 for a in analyses if a["kind"] == "NO_TRADE"),
            "trade": sum(1 for a in analyses if a["kind"] == "TRADE"), "triggered": len(triggered),
            "triggered_from_today": sum(1 for o in triggered if o["local_date"] == day),
            "outcomes_today_analyses": counts(today_res), "outcomes_earlier_analyses": counts(earlier_res),
            "unresolved": len(unresolved), "strategy_performance": perf["by_strategy"], "summary": perf["summary"],
            "research": sources, "data_warnings": warnings, "experiments": exps, "proposals": proposals}
    t, e = data["outcomes_today_analyses"], data["outcomes_earlier_analyses"]
    s = perf["summary"]
    lines = [f"📒 Kunlik tadqiqot hisoboti — {day}", "",
             f"Tahlillar: {data['analyses']} (ssenariy {data['trade']}, NO-TRADE {data['no_trade']})",
             f"Bugun gipotetik kirish bajarilgan: {data['triggered']} (shundan bugungi tahlillardan "
             f"{data['triggered_from_today']})",
             f"Bugungi tahlillar natijasi: TP {t['TP_HIT']}, SL {t['SL_HIT']}, muddati tugagan {t['EXPIRED']}, noaniq "
             f"{t['AMBIGUOUS_DATA']}, kirilmagan {t['NOT_TRIGGERED']}, bekor {t['CANCELLED']}",
             f"Oldingi kunlar tahlillari (bugun yopilgan): TP {e['TP_HIT']}, SL {e['SL_HIT']}, muddati tugagan "
             f"{e['EXPIRED']}, noaniq {e['AMBIGUOUS_DATA']}",
             f"Hal bo'lmagan ssenariylar: {data['unresolved']}", "",
             f"Umumiy (barcha davr): hal bo'lgan {s['resolved']}, yutuq foizi "
             f"{s['win_rate'] if s['win_rate'] is not None else '—'}%, expectancy "
             f"{s['expectancy_r'] if s['expectancy_r'] is not None else '—'}R, maks. pasayish {s['max_drawdown_r']}R"
             + (" — namuna kichik, xulosa chiqarib bo'lmaydi" if s["small_sample"] else "")]
    if perf["by_strategy"]:
        lines.append("Strategiyalar:")
        for b in perf["by_strategy"][:8]:
            lines.append(f"  • {b['key']}: ssenariy {b['scenarios']}, TP {b['tp']}/SL {b['sl']}, expectancy "
                         f"{b['expectancy_r'] if b['expectancy_r'] is not None else '—'}R"
                         + (" (namuna kichik)" if b["small_sample"] else ""))
    if sources:
        lines.append("Tadqiqot topilmalari:")
        lines += [f"  • [{x['evidence_type']}] {x['title'][:90]} — {x['url']}" for x in sources[:6]]
    if warnings:
        lines.append(f"Ma'lumot sifati ogohlantirishlari: {len(warnings)} ta (" +
                     "; ".join(f"{w['symbol']} {w['kind']}" for w in warnings[:4]) + ")")
    if exps or proposals:
        lines.append("Eksperimentlar / takliflar:")
        lines += [f"  • {x['experiment_id']} {x['strategy_id']}: {x['verdict']}" for x in exps]
        lines += [f"  • taklif: {p}" for p in proposals]
    lines += ["", LABEL]
    text = "\n".join(lines)
    rid = f"daily-{day}"
    db.execute("INSERT OR REPLACE INTO reports(report_id, kind, period_start, period_end, created_at, text, data) "
               "VALUES(?,?,?,?,?,?,?)", (rid, "daily", day, day, utcnow(), text, dumps(data)))
    if memory is not None:
        (memory.reports / f"{day}.md").write_text(text + "\n", encoding="utf-8")
    return text, data


def weekly(db, settings, end_day: str, memory=None) -> tuple[str, dict]:
    end = date.fromisoformat(end_day)
    start = (end - timedelta(days=6)).isoformat()
    perf = analytics.performance(db, start, end_day)
    s = perf["summary"]
    lines = [f"🗓 Haftalik tadqiqot hisoboti — {start} … {end_day}",
             f"Tahlillar: {s['total_analyses']} (NO-TRADE {s['no_trade']}), kirish bajarilgan {s['valid_entries']}",
             f"TP {s['tp_hits']}, SL {s['sl_hits']}, muddati tugagan {s['expired']}, noaniq {s['ambiguous']}, "
             f"kirilmagan {s['not_triggered']}",
             f"Yutuq foizi (hal bo'lganlar {s['resolved']}): {s['win_rate'] if s['win_rate'] is not None else '—'}%, "
             f"expectancy {s['expectancy_r'] if s['expectancy_r'] is not None else '—'}R, maks. pasayish "
             f"{s['max_drawdown_r']}R" + (" — namuna kichik" if s["small_sample"] else ""), "", LABEL]
    text = "\n".join(lines)
    rid = f"weekly-{end_day}"
    db.execute("INSERT OR REPLACE INTO reports(report_id, kind, period_start, period_end, created_at, text, data) "
               "VALUES(?,?,?,?,?,?,?)", (rid, "weekly", start, end_day, utcnow(), text, dumps(perf)))
    if memory is not None:
        (memory.reports / f"weekly-{end_day}.md").write_text(text + "\n", encoding="utf-8")
    return text, perf


def proposals_from_reviews(reviews: list[dict]) -> list[str]:
    """SL tahlillaridan eksperiment takliflari (faqat takrorlanuvchi naqsh bo'lsa; bitta zarar — sabab emas)."""
    c = Counter((r["strategy_id"], r["classification"]) for r in reviews)
    out = []
    for (sid, cls), n in c.items():
        if n < 3:
            continue
        if cls == "Incorrect volatility assumption":
            out.append(f"{sid}: 14 kunda {n} ta SL volatillik bilan bog'liq — sl_atr ni +0.25 qilib eksperiment")
        elif cls == "Poor market-regime match":
            out.append(f"{sid}: {n} ta SL rejim mos kelmagan holatda — rejim filtrini qattiqlashtirish eksperimenti")
        elif cls == "Execution-model problem":
            out.append(f"{sid}: {n} ta SL xarajat yuqori — kichik taymfreymdan voz kechish yoki masofani oshirish")
    return out
