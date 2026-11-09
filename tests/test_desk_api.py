"""Dashboard: bo'lim/signal/pozitsiya ko'rinishlari (faqat o'qish) va boshqaruv buyruqlarini qo'yish (qat'iy ro'yxat)."""
from __future__ import annotations

import json
import sqlite3

import pytest

from agent.dashboard.desk_api import ApiError, DeskView
from agent.trading.db import TradingDB


@pytest.fixture()
def view(tmp_path):
    db_path = tmp_path / "trading_memory" / "database" / "trading_research.db"
    db_path.parent.mkdir(parents=True)
    db = TradingDB(db_path)
    return DeskView(tmp_path), db


def test_staff_lists_roster_and_marks_recent_speaker_active(view):
    v, db = view
    from datetime import datetime, timezone
    db.execute("INSERT INTO staff_messages(ts, role, kind, text, ref) VALUES(?,?,?,?,?)",
               (datetime.now(timezone.utc).isoformat(), "DEBATE-B", "vote", "REJECT", "S1"))
    members = {m["id"]: m for m in v.staff()["members"]}
    assert members["DIR-1"]["unit"] == "direktor" and members["DEBATE-B"]["active"] and not members["DEBATE-A"]["active"]


def test_messages_incremental_and_signals_with_staff_verdict(view):
    v, db = view
    for i in range(3):
        db.execute("INSERT INTO staff_messages(ts, role, kind, text, ref) VALUES('t','DIR-1','x',?, 'S1')", (f"m{i}",))
    assert [m["text"] for m in v.messages()["items"]] == ["m0", "m1", "m2"]
    assert [m["text"] for m in v.messages(after_id=2)["items"]] == ["m2"]
    db.execute("INSERT INTO signals(signal_id, created_at, symbol, direction, status) VALUES('S1','2026-11-08','BTCUSDT','LONG','SENT')")
    db.execute("INSERT INTO staff_decisions(ts, kind, ref, approve, votes, reason) VALUES('t','signal','S1',1,?, 'ok')", (json.dumps({"DEBATE-A": "approve"}),))
    s = v.signals()["items"][0]
    assert s["staff"]["approve"] is True and s["staff"]["votes"] == {"DEBATE-A": "approve"}


def test_positions_totals(view):
    v, db = view
    db.execute("INSERT INTO position_snapshot(position_id, symbol, side, volume, price_open, sl, tp, profit, swap, magic, opened_at, ts) "
               "VALUES(1,'BTCUSDm','BUY',0.01,100,90,120,1.5,0,20260711,'a','b')")
    db.execute("INSERT INTO live_trades(position_id, symbol, direction, closed_at, net) VALUES(2,'ETH','BUY','2026-01-02',-3.0)")
    db.execute("INSERT INTO live_trades(position_id, symbol, direction, closed_at, net) VALUES(3,'ETH','BUY','2026-01-03',5.0)")
    p = v.positions()
    assert p["totals"] == {"open_profit": 1.5, "closed_n": 2, "closed_net": 2.0, "wins": 1, "losses": 1} and len(p["open"]) == 1


def test_command_whitelist_and_pending_row(view):
    v, db = view
    r = v.command("mode", "auto")
    assert r["status"] == "pending"
    row = db.one("SELECT * FROM control_commands WHERE id=?", (r["id"],))
    assert (row["cmd"], row["arg"], row["source"], row["status"]) == ("mode", "auto", "web", "pending")
    for bad in (("rm", ""), ("mode", "yolo"), ("review", "x; drop"), ("stop", "zzz")):
        with pytest.raises(ApiError):
            v.command(*bad)
    assert v.command("review", "SIG-20261108-001")["status"] == "pending"
    assert v.command_status(r["id"])["status"] == "pending"


def test_dashboard_connection_cannot_write_other_tables(view):
    v, db = view
    conn = v._db().conn
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM signals")


def test_status_dashboard_market_and_signal_detail(view, monkeypatch):
    v, db = view
    from agent.dashboard import desk_api
    st = v.status()
    assert st["agent"]["running"] is False and st["mt5"]["connected"] is None and st["last_sync"] is None  # soxta ONLINE yo'q
    k = v.dashboard()["kpi"]
    assert k["signals"] == 0 and k["win_rate"] is None and k["profit_factor"] is None
    db.execute("INSERT INTO signals(signal_id, created_at, symbol, direction, status, analysis) VALUES('S9','2026-11-08','BTCUSDT','LONG','SENT',?)",
               (json.dumps({"items": [{"key": "a", "label": "A", "ok": True, "detail": "d"}], "structure": "x"}),))
    db.execute("INSERT INTO staff_messages(ts, role, kind, text, ref) VALUES('t','DIR-1','x','hi','S9')")
    d = v.signal_detail("S9")
    assert d["signal"]["analysis"]["structure"] == "x" and d["messages"][0]["text"] == "hi" and d["decision"] is None
    with pytest.raises(ApiError):
        v.signal_detail("NOPE")
    desk_api._market_cache.update(ts=0.0, data=None)
    monkeypatch.setattr(desk_api, "_fetch_market", lambda: (_ for _ in ()).throw(OSError("offline")))
    m = v.market()
    assert m["error"] and all(i["price"] is None for i in m["items"])  # tarmoq yo'q -> N/A, soxta narx yo'q
    desk_api._market_cache.update(ts=0.0, data=None)


def test_command_whitelist_includes_confirm_reject(view):
    v, _ = view
    assert v.command("confirm", "SIG-20261108-0001")["status"] == "pending"
    assert v.command("reject", "SIG-20261108-0001")["status"] == "pending"
    with pytest.raises(ApiError):
        v.command("confirm", "x; DROP")


def test_chart_draws_from_agent_data_and_never_fakes_candles(view, monkeypatch):
    v, db = view
    from agent.dashboard import desk_api
    desk_api._candle_cache.clear()
    monkeypatch.setattr(desk_api, "_fetch_candles", lambda s, tf, limit=300: [{"time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5}])
    an = json.dumps({"evidence": {"range_high": 105.0, "range_low": 100.0}})
    db.execute("INSERT INTO signals(signal_id, created_at, symbol, direction, entry, sl, tp, status, analysis) VALUES('S-0001','2026-11-08','BTCUSDT','LONG',102,99,110,'SENT',?)", (an,))
    db.execute("INSERT INTO position_snapshot(position_id, symbol, side, volume, price_open, sl, tp, profit, swap, magic, opened_at, ts) VALUES(5,'BTCUSDm','BUY',0.01,101,98,0,0.5,0,1,'t','t')")
    c = v.chart("BTCUSDT", "1h")
    kinds = sorted((x["kind"], x["price"]) for x in c["levels"])
    assert ("entry", 102) in kinds and ("sl", 99) in kinds and ("tp", 110) in kinds and ("position", 101) in kinds and ("sl", 98) in kinds
    assert c["zones"][0]["high"] == 105.0 and len(c["candles"]) == 1 and c["error"] is None
    desk_api._candle_cache.clear()
    monkeypatch.setattr(desk_api, "_fetch_candles", lambda s, tf, limit=300: (_ for _ in ()).throw(OSError("offline")))
    c = v.chart("BTCUSDT", "1h")
    assert c["candles"] == [] and c["error"] and c["levels"]  # sham yo'q — soxta chizilmaydi, xato aytiladi
    with pytest.raises(ApiError):
        v.chart("BTC;DROP", "1h")
    with pytest.raises(ApiError):
        v.chart("BTCUSDT", "9x")


def test_say_command_validates_and_truncates(view):
    v, db = view
    assert v.command("say", "BTC zonalarini tekshir" + "x" * 600)["status"] == "pending"
    row = db.one("SELECT arg FROM control_commands ORDER BY id DESC")
    assert len(row["arg"]) == 500
    with pytest.raises(ApiError):
        v.command("say", " ")


def test_chart_supports_mt5_symbols_and_all_timeframes(view, monkeypatch):
    v, db = view
    from agent.dashboard import desk_api
    desk_api._candle_cache.clear()
    db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, status, first_seen, last_seen) "
               "VALUES('m1','EURUSDm','mt5','ZONE-1','support','1h',1.10,1.11,30,'active','t','t')")
    db.execute("INSERT INTO position_snapshot(position_id, symbol, side, volume, price_open, sl, tp, profit, swap, magic, opened_at, ts) "
               "VALUES(9,'EURUSDm','BUY',0.01,1.105,1.09,0,0,0,1,'t','t')")
    seen = []
    monkeypatch.setattr(v, "_mt5_candles", lambda s, tf, n: seen.append((s, tf)) or [{"time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5}])
    monkeypatch.setattr(desk_api, "_fetch_candles", lambda *a, **k: (_ for _ in ()).throw(AssertionError("MT5 simvoli Binance'ga ketmasligi kerak")))
    c = v.chart("EURUSDm", "1m")  # kichik 'm' harfi saqlanadi, upper() qilinmaydi
    assert c["source"] == "mt5" and seen == [("EURUSDm", "1m")] and c["zones"] and any(x["kind"] == "position" for x in c["levels"])
    assert "EURUSDm" in c["groups"]["mt5"]
    for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d"):
        assert tf in desk_api.TFS
    with pytest.raises(ApiError):
        v.chart("EURUSDm", "6m")


def test_mt5_category_uses_real_broker_path():
    from agent.dashboard.desk_api import mt5_category
    assert mt5_category("EURUSDm", r"Standard\Forex\EURUSDm") == "Forex"
    assert mt5_category("XAUUSDm", r"Standard\Forex\XAUUSDm") == "Metals"
    assert mt5_category("AAPLm", r"Standard\Stocks\AAPLm") == "Stocks"
    assert mt5_category("US30m", r"Standard\Indices\US30m") == "Indices"
    assert mt5_category("UKOILm", r"Standard\Energies\UKOILm") == "Commodities"
    assert mt5_category("BTCUSDm", r"Standard\Crypto\BTCUSDm") == "Crypto"


def test_instruments_come_from_real_sources_and_failures_are_reported(view, monkeypatch):
    v, db = view
    from agent.dashboard import desk_api
    desk_api._inst_cache.update(ts=0.0, data=None)
    db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, status, first_seen, last_seen) "
               "VALUES('z','ETHUSDT','binance','ZONE-1','support','1h',1,2,30,'active','t','t')")

    def fake(url, timeout=15):
        if "vision" in url:
            return {"symbols": [{"symbol": "ETHUSDT", "status": "TRADING", "baseAsset": "ETH", "quoteAsset": "USDT"},
                                {"symbol": "OLDUSDT", "status": "BREAK", "baseAsset": "OLD", "quoteAsset": "USDT"}]}
        raise OSError("futures ulanmagan")
    monkeypatch.setattr(desk_api, "_get_json", fake)
    monkeypatch.setitem(__import__("os").environ, "MT5_PATH", "C:/yo'q/terminal64.exe")
    d = v.instruments(force=True)
    spot = [i for i in d["items"] if i["market"] == "spot"]
    assert [i["symbol"] for i in spot] == ["ETHUSDT"] and spot[0]["zones"] == 1  # TRADING bo'lmagani chiqarib tashlandi
    assert d["sources"]["spot"]["ok"] is True
    assert d["sources"]["futures-usdm"]["ok"] is False and d["sources"]["futures-coinm"]["ok"] is False  # soxta ro'yxat yo'q
    assert not [i for i in d["items"] if i["market"].startswith("futures")]
    desk_api._inst_cache.update(ts=0.0, data=None)


def test_chart_market_param_routes_to_matching_source(view, monkeypatch):
    v, _ = view
    from agent.dashboard import desk_api
    desk_api._candle_cache.clear()
    seen = []
    monkeypatch.setattr(desk_api, "_fetch_candles_market", lambda s, tf, m, limit=400: seen.append((s, m)) or [{"time": 1, "open": 1, "high": 2, "low": 0.5, "close": 1.5}])
    c = v.chart("btcusdt", "5m", "futures-usdm")
    assert seen == [("BTCUSDT", "futures-usdm")] and c["market"] == "futures-usdm" and c["levels"] == [] and c["zones"] == []  # futures uchun agent chizmasi yo'q
    with pytest.raises(ApiError):
        v.chart("BTCUSDT", "5m", "bogus")
    desk_api._candle_cache.clear()


def test_every_dashboard_route_has_a_working_view_method(view):
    """Regressiya: grafik kodini almashtirganda `zones` metodi o'chib ketgan edi (API 500). Serverdagi hamma desk marshruti ishlashi shart."""
    import re
    from pathlib import Path
    v, db = view
    src = Path(__file__).resolve().parents[1].joinpath("agent", "dashboard", "server.py").read_text(encoding="utf-8")
    called = set(re.findall(r"self\.desk\.(\w+)\(", src))
    missing = [n for n in sorted(called) if not callable(getattr(v, n, None))]
    assert not missing, f"DeskView'da yo'q metodlar: {missing}"


def test_zones_endpoint_filters_and_summarises(view):
    v, db = view
    for i, (sym, src, st, strength) in enumerate([("AAAUSDT", "binance", "active", 30), ("BBBUSDT", "binance", "fresh", 10), ("EURUSDm", "mt5", "active", 20)]):
        db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, status, dist_atr, first_seen, last_seen) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"z{i}", sym, src, "ZONE-1", "support", "1h", 1, 2, strength, st, 0.1 * i, "t", "t"))
    d = v.zones()
    assert d["summary"]["total"] == 3 and d["summary"]["active"] == 2 and d["summary"]["symbols"] == 3
    assert [x["symbol"] for x in v.zones(status="active")["items"]][0] == "AAAUSDT"
    assert [x["symbol"] for x in v.zones(symbol="EURUSDm")["items"]] == ["EURUSDm"]
    assert d["by_detector" if False else "summary"]["by_detector"][0]["n"] == 3


def test_diagnostics_uses_real_data_and_says_unknown_when_missing(view, monkeypatch):
    v, db = view
    from datetime import datetime, timedelta, timezone

    from agent.dashboard import desk_api
    desk_api._probe_cache.clear()
    monkeypatch.setattr(desk_api, "_get_json", lambda url, timeout=15: {"serverTime": 1})
    monkeypatch.setattr(v, "_probe", lambda key, fn, ttl=20.0: {"ok": key == "binance", "ms": 12, "detail": {"connected": False, "bars": 0}, "error": None if key == "binance" else "OSError: terminal yo'q"})
    d = v.diagnostics()
    comps = {c["id"]: c for c in d["components"]}
    assert comps["strategy"]["status"] == "unknown" and comps["database"]["status"] == "ok"  # scan_log yo'q -> soxta OK emas
    assert comps["binance"]["status"] == "ok" and comps["mt5"]["status"] == "down" and "terminal" in comps["mt5"]["last_error"]
    # skaner izi paydo bo'lgach — real hisoblagichlar
    now = datetime.now(timezone.utc)
    for i in range(3):
        db.execute("INSERT INTO scan_log(ts, symbol, stage, strategy, outcome, reason) VALUES(?,?,?,?,?,?)",
                   ((now - timedelta(minutes=15 * i)).isoformat(timespec="seconds"), "*", "summary", None, "ok",
                    json.dumps({"scanned": 5, "no_setup": 3, "watch": 2, "sent": 0, "n_errors": 1 if i == 0 else 0, "ms": 900 + i})))
    db.execute("INSERT INTO scan_log(ts, symbol, stage, strategy, outcome, reason) VALUES(?,?,?,?,?,?)",
               (now.isoformat(timespec="seconds"), "BTCUSDT", "strategy", "TF-PULLBACK", "reject", "EMA20 ga pullback va undan pastda yopilish yo'q"))
    d = v.diagnostics()
    s = {c["id"]: c for c in d["components"]}["strategy"]
    assert s["status"] == "ok" and s["executions"] == 3 and s["failures"] == 1 and s["processing_ms"] == 901
    assert d["funnel"]["scanned"] == 15 and d["funnel"]["no_setup"] == 9 and d["funnel"]["watch"] == 6 and d["funnel"]["scans"] == 3
    assert any("pullback" in r["reason"] for r in d["reasons"])  # aniq sabab, "Conditions not met" emas


def test_status_reports_last_done_research_job_not_future_pending(view):
    v, db = view
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    db.execute("INSERT INTO jobs(job_key, kind, scheduled_at, status, finished_at) VALUES('a','analysis',?,'done',?)",
               ((now - timedelta(hours=2)).isoformat(timespec="seconds"), (now - timedelta(hours=2)).isoformat(timespec="seconds")))
    db.execute("INSERT INTO jobs(job_key, kind, scheduled_at, status) VALUES('b','analysis',?,'pending')", ((now + timedelta(hours=3)).isoformat(timespec="seconds"),))
    r = v.status()["research"]
    assert r["status"] == "done" and r["fresh"] is True  # kelajakdagi 'pending' emas, oxirgi bajarilgan ish
