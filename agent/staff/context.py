"""Xodimlar uchun ma'lumot to'plami: bazadan O'QILADI (taxmin yo'q) — topshiriq va davriy ishlar shu faktlarga tayanadi."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone


def hhmm_tk(iso: str | None) -> str:
    """UTC ISO -> 'HH:MM' Toshkent vaqti (UTC+5, DST yo'q). Noaniq bo'lsa — bo'sh."""
    try:
        d = datetime.fromisoformat(str(iso))
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        return d.astimezone(timezone(timedelta(hours=5))).strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def _iso(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def risk_status(db, cfg: dict) -> str:
    bal = db.one("SELECT value FROM meta WHERE key='account_balance'")
    b = json.loads(bal["value"]) if bal else None
    open_n = (db.one("SELECT COUNT(*) n FROM position_snapshot") or {}).get("n", 0)
    open_pl = (db.one("SELECT COALESCE(SUM(profit),0) p FROM position_snapshot") or {}).get("p", 0)
    since = _iso(24)
    today = db.one("SELECT COUNT(*) n, COALESCE(SUM(net),0) s FROM live_trades WHERE closed_at >= ?", (since,)) or {}
    last = db.query("SELECT net FROM live_trades ORDER BY closed_at DESC LIMIT 5")
    streak = 0
    for r in last:
        if (r["net"] or 0) < 0:
            streak += 1
        else:
            break
    bal_txt = f"{b['balance']:.2f} (yangilangan {hhmm_tk(b.get('ts'))} Toshkent vaqti)" if b else "noma'lum (monitor hali yozmagan)"
    return (f"Balans: {bal_txt} | ochiq pozitsiya: {open_n}, suzuvchi P/L {open_pl:.2f} | "
            f"oxirgi 24 soat yopilgan: {today.get('n', 0)} ta, natija {today.get('s', 0):.2f} | ketma-ket zarar: {streak}/{cfg.get('breaker_losses', 3)} | "
            f"rejim: {cfg.get('trade_mode', '?')} | risk {cfg.get('risk_pct', 1)}%, max guruh {cfg.get('max_groups', '?')}, kunlik limit {cfg.get('daily_loss_pct', 5)}%")


def strategy_stats(db, prefix: str | None = None) -> list[dict]:
    """Strategiya bo'yicha: signal soni (7 kun), paper natija (R), DEMO natija. Faqat mavjud ma'lumot."""
    since = _iso(24 * 7)
    rows = db.query("SELECT strategy_id, COUNT(*) n, SUM(tier='STRONG') strong, SUM(tier='CONFIRM') confirm FROM signals "
                    "WHERE created_at >= ? GROUP BY strategy_id", (since,))
    out = []
    for r in rows:
        sid = r["strategy_id"] or "?"
        if prefix and not sid.startswith(prefix):
            continue
        paper = db.query("SELECT p.r_multiple r FROM paper_positions p JOIN signals s ON s.signal_id=p.signal_id "
                         "WHERE s.strategy_id=? AND p.r_multiple IS NOT NULL AND COALESCE(p.dataset,'EXECUTABLE')='EXECUTABLE'", (sid,))
        live = db.query("SELECT net, r_multiple FROM live_trades WHERE strategy=?", (sid,))
        rs = [p["r"] for p in paper]
        out.append({"strategy": sid, "signals_7d": r["n"], "strong": r["strong"] or 0, "confirm": r["confirm"] or 0,
                    "paper_n": len(rs), "paper_avg_r": round(sum(rs) / len(rs), 2) if rs else None,
                    "demo_n": len(live), "demo_net": round(sum((x["net"] or 0) for x in live), 2) if live else None})
    return sorted(out, key=lambda x: -x["signals_7d"])


def zones_brief(db, n: int = 10) -> str:
    rows = db.query("SELECT symbol, source, detector, kind, tf, low, high, dist_atr, strength, watch FROM zones WHERE status='active' "
                    "ORDER BY watch DESC, dist_atr, strength DESC LIMIT ?", (n,))
    total = (db.one("SELECT COUNT(*) n FROM zones WHERE status='active'") or {}).get("n", 0)
    if not rows:
        return "Aktiv zona yo'q."
    lines = [f"- {r['symbol']} {r['tf']} {r['kind']} {r['low']:.6g}-{r['high']:.6g} ({r['detector']}, kuch {r['strength']}, "
             f"{'ichida' if r['dist_atr'] <= 0.001 else '%.2f ATR' % r['dist_atr']}{', KUZATUV' if r['watch'] else ''})" for r in rows]
    return f"Aktiv zonalar jami {total} (eng yaqin {len(rows)} ta):\n" + "\n".join(lines)


def positions_brief(db) -> str:
    rows = db.query("SELECT position_id, symbol, side, volume, price_open, sl, tp, profit FROM position_snapshot")
    if not rows:
        return "Ochiq pozitsiya yo'q."
    return "Ochiq pozitsiyalar:\n" + "\n".join(f"- #{r['position_id']} {r['symbol']} {r['side']} {r['volume']} kirish {r['price_open']} SL {r['sl']} TP {r['tp']} P/L {r['profit']}" for r in rows)


def signals_brief(db, n: int = 6) -> str:
    rows = db.query("SELECT signal_id, symbol, direction, tier, status, entry, sl, tp FROM signals ORDER BY created_at DESC LIMIT ?", (n,))
    return "Oxirgi signallar:\n" + ("\n".join(f"- {r['signal_id']} {r['symbol']} {r['direction']} {r['tier']} {r['status']} kirish {r['entry']} SL {r['sl']} TP {r['tp']}" for r in rows) or "yo'q")


def zone_trade_status(db) -> str:
    row = db.one("SELECT value FROM meta WHERE key='zone_trade_status'")
    last = db.one("SELECT signal_id, status, created_at, substr(decision_note,1,120) AS note FROM signals WHERE strategy_id='ZONE-DIR' ORDER BY created_at DESC LIMIT 1")
    if not row:
        txt = "hali birorta tekshiruv bo'lmagan (skaner birinchi o'tishini kutmoqda)"
    else:
        try:
            d = json.loads(row["value"])
        except ValueError:
            d = {}
        if d.get("enabled") is False:
            txt = f"{hhmm_tk(d.get('ts'))} (Toshkent) holati: ishlamayapti — {d.get('why')}"
        else:
            txt = (f"{hhmm_tk(d.get('ts'))} (Toshkent): {d.get('state', '')}; nomzod zonalar {d.get('candidates', '—')}, urinish {d.get('tried', '—')}; "
                   f"o'tmagan sabablar: {'; '.join(d.get('skipped') or []) or 'yo\'q'}; ruxsat etilgan MT5 kategoriyalar: {', '.join(d.get('categories') or [])} + kripto (Binance/MT5 BTC,ETH)")
    tail = f" Oxirgi zona signali: {last['signal_id']} {last['status']} ({last['note'] or ''})." if last else " Hali zona signali bo'lmagan."
    return "DIR-1 ZONA ZDELKA VAZIFASI (avtomatik, egasi tasdig'isiz, har skanerdan keyin): " + txt + tail


def pack(db, cfg: dict) -> str:
    """Topshiriq uchun umumiy ma'lumot (xodimlarga MA'LUMOT sifatida beriladi)."""
    stats = strategy_stats(db)
    st = "\n".join(f"- {s['strategy']}: signal(7k) {s['signals_7d']}, paper {s['paper_n']} ta o'rtacha {s['paper_avg_r']} R, DEMO {s['demo_n']} ta net {s['demo_net']}" for s in stats[:8]) or "yo'q"
    return "\n\n".join([risk_status(db, cfg), zone_trade_status(db), zones_brief(db), positions_brief(db), signals_brief(db), "Strategiyalar (7 kun):\n" + st])
