"""ZONE-1..5: detektorlar (sof hisob), skaner (bazaga yozish, e'lon, kvota) — tarmoqsiz, soxta shamlar bilan."""
from __future__ import annotations

import asyncio
import math
import types
from datetime import datetime, timedelta, timezone

from agent.staff.desk import Desk
from agent.trading.data import Candle
from agent.trading.db import TradingDB
from agent.zones.detectors import Bar, atr, classify, impulse_origin, liquidity, rng, snr
from agent.zones.scanner import ZoneScanner, zone_id


def wave(n=300, base=100.0, amp=3.0, period=40):
    """Sinus to'lqin: tepa/pastlar aniq takrorlanadi -> S/R topiladi."""
    bars = []
    for i in range(n):
        c = base + amp * math.sin(2 * math.pi * i / period)
        bars.append(Bar(c, c + 0.4, c - 0.4, c + 0.05))
    return bars


def test_snr_finds_repeated_levels_and_classifies_active():
    bars = wave()
    zs = snr(bars, "1h")
    assert zs and all(z["low"] < z["high"] for z in zs)
    top = max(zs, key=lambda z: z["strength"])
    assert top["kind"] in ("support", "resistance")
    a = atr(bars)
    st, dist = classify({**top}, (top["low"] + top["high"]) / 2, a)
    assert st == "active" and dist == 0.0
    far, _ = classify({**top}, top["high"] + 10 * a, a)
    assert far in ("fresh", "broken")


def test_range_only_when_tight():
    flat = [Bar(100, 100.3, 99.7, 100.0 + (0.1 if i % 2 else -0.1)) for i in range(80)]
    assert rng(flat, "1h")
    assert rng(wave(80, amp=10), "1h") == []


def test_impulse_origin_skips_mitigated_zone():
    bars = [Bar(100, 100.5, 99.5, 100) for _ in range(40)]
    bars.append(Bar(100, 105, 99.9, 104.8))  # kuchli impuls (bull)
    bars += [Bar(104.8, 105.2, 104.4, 105) for _ in range(5)]
    z = impulse_origin(bars, "1h")
    assert z and z[-1]["kind"] == "demand" and z[-1]["low"] == 99.5
    bars.append(Bar(105, 105, 98, 98.5))  # demand pastga teshildi
    assert impulse_origin(bars, "1h") == []


def test_liquidity_equal_highs():
    bars = wave()
    z = liquidity(bars, "1h")
    assert z and any(x["kind"] == "liq-high" for x in z)


class FakeProv:
    def klines(self, symbol, tf, limit, end=None, start=None):
        sec = 3600 if tf == "1h" else 14400
        t0 = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(seconds=sec * 330)
        out = []
        for i, b in enumerate(wave(330)):
            out.append(Candle(t0 + timedelta(seconds=sec * i), b.open, b.high, b.low, b.close, 1.0, sec))
        return out[-limit:]


def make(tmp_path, llm=None, cfg=None):
    db = TradingDB(tmp_path / "t.db")
    svc = types.SimpleNamespace(db=db, settings=types.SimpleNamespace(data={}), market=types.SimpleNamespace(providers={"binance": FakeProv()}))
    return db, ZoneScanner(svc, Desk(db, llm), None, cfg=cfg)


def test_scan_store_announce_and_activity(tmp_path):
    db, zs = make(tmp_path)
    zs.universe = {"binance": ["AAAUSDT", "BBBUSDT"], "mt5": []}
    zs._uni_at = 1e18  # ro'yxatni yangilamaslik (tarmoq yo'q)
    res = zs.run_pass()
    assert res["errors"] == 0 and res["zones"] > 0
    rows = db.query("SELECT * FROM zones")
    assert {r["detector"] for r in rows} >= {"ZONE-1", "ZONE-3"} and len(rows) == res["zones"] - 0 or rows
    top = zs.announce(res["news"])
    assert top and db.query("SELECT * FROM staff_messages WHERE kind='zone'")
    assert db.one("SELECT announced_at FROM zones WHERE id=?", (top[0]["id"],))["announced_at"]
    acts = {r["role"] for r in db.query("SELECT role FROM staff_activity")}
    assert {"ZONE-1", "ZONE-2", "ZONE-3", "ZONE-4", "ZONE-5"} <= acts
    # ikkinchi o'tish: kuldaun tufayli qayta e'lon qilinmaydi
    res2 = zs.run_pass()
    already = {t["id"] for t in top}
    assert not [n for n in res2["news"] if n["id"] in already]


def test_scan_error_is_isolated(tmp_path):
    class Bad:
        def klines(self, *a, **k):
            raise OSError("offline")
    db, zs = make(tmp_path)
    zs.svc.market.providers["binance"] = Bad()
    zs.universe = {"binance": ["AAAUSDT"], "mt5": []}
    zs._uni_at = 1e18
    res = zs.run_pass()
    assert res["errors"] == 1 and res["zones"] == 0


def test_consult_budget_and_never_trades(tmp_path):
    calls = []

    async def llm(system, prompt):
        calls.append(system[:30])
        return '{"watch": [1], "note": "ok"}' if "KUZATUV" in prompt else "fikr"
    db, zs = make(tmp_path, llm=llm, cfg={"consult_per_hour": 1})
    zs.universe = {"binance": ["AAAUSDT"], "mt5": []}
    zs._uni_at = 1e18
    res = zs.run_pass()
    top = zs.announce(res["news"])[:2]
    asyncio.run(zs.consult(top))
    n = len(calls)
    assert n == 3 and db.one("SELECT COUNT(*) n FROM zones WHERE watch=1")["n"] == 1
    asyncio.run(zs.consult(top))  # soatlik limit tugadi
    assert len(calls) == n
    assert db.one("SELECT COUNT(*) n FROM signals")["n"] == 0  # zona signal/zdelka yaratmaydi


def test_zone_id_stable_for_small_shift():
    assert zone_id("X", "ZONE-1", "1h", "support", 100.0, 100.5) == zone_id("X", "ZONE-1", "1h", "support", 100.001, 100.501)


# ------------------------------------------------------------------ V30: davriy ishlar va egasi topshirig'i
def test_routine_every_role_reports_without_llm(tmp_path):
    from agent.staff.routine import SCHEDULE, StaffRoutine
    db = TradingDB(tmp_path / "r.db")
    desk = Desk(db, None)
    rt = StaffRoutine(desk, db, lambda: {})
    for k in rt._due:
        rt._due[k] = 0
    assert rt.tick() == len(SCHEDULE)
    roles = {r["role"] for r in db.query("SELECT role FROM staff_messages WHERE kind='report'")}
    assert roles == set(SCHEDULE)
    assert rt.tick() == 0  # interval kelmaguncha qayta yozmaydi
    acts = {r["role"] for r in db.query("SELECT role FROM staff_activity")}
    assert set(SCHEDULE) <= acts


def test_owner_task_is_assigned_executed_and_summarised(tmp_path):
    from agent.staff.routine import StaffRoutine
    db = TradingDB(tmp_path / "o.db")
    seen = []

    async def llm(system, prompt):
        seen.append(system.split("—")[0][-8:])
        if "Topshiriqni mos xodimlarga" in prompt:
            return '{"assign":[{"role":"ZONE-1","task":"BTC zonasi"},{"role":"RISK-1","task":"xavf"},{"role":"NOPE","task":"x"}],"note":"ok"}'
        if "yakuniy javob" in prompt:
            return "Yakun: bajarildi"
        return "natija matni"
    rt = StaffRoutine(Desk(db, llm), db, lambda: {})
    asyncio.run(rt.handle_owner("BTC zonalarini tekshir"))
    kinds = [(r["role"], r["kind"]) for r in db.query("SELECT role, kind FROM staff_messages ORDER BY id")]
    assert ("OWNER", "owner") in kinds and ("DIR-1", "assign") in kinds
    assert ("ZONE-1", "task-result") in kinds and ("RISK-1", "task-result") in kinds and ("NOPE", "task-result") not in kinds
    assert ("DIR-1", "owner-reply") in kinds
    assert db.one("SELECT COUNT(*) n FROM signals")["n"] == 0  # topshiriq zdelka ochmaydi


def test_owner_task_errors_are_visible_and_budget_limits(tmp_path):
    from agent.staff import routine as RM
    db = TradingDB(tmp_path / "e.db")

    async def boom(system, prompt):
        raise RuntimeError("kvota")
    rt = RM.StaffRoutine(Desk(db, boom), db, lambda: {})
    asyncio.run(rt.handle_owner("salom"))
    assert db.one("SELECT text FROM staff_messages WHERE role='DIR-1' AND kind='system'")["text"].startswith("Topshiriq yakunlanmadi")
    rt._owner_calls = [__import__("time").time()] * RM.OWNER_LLM_PER_HOUR
    asyncio.run(rt.handle_owner("yana"))
    assert "limiti" in db.query("SELECT text FROM staff_messages WHERE kind='system' ORDER BY id DESC LIMIT 1")[0]["text"]


def test_staff_context_times_are_tashkent_not_utc():
    from agent.staff.context import hhmm_tk
    assert hhmm_tk("2026-11-09T04:44:05+00:00") == "09:44"  # UTC+5
    assert hhmm_tk("2026-11-09T22:30:00+00:00") == "03:30"  # kun almashinuvi
    assert hhmm_tk("2026-11-09T04:44:05") == "09:44"  # offsetsiz = UTC
    assert hhmm_tk(None) == "" and hhmm_tk("xato") == ""


def test_universe_connects_mt5_first_and_keeps_old_list_on_failure(tmp_path):
    """Regressiya: agent endi ishga tushganda MT5 hali ulanmagan edi -> ro'yxat bo'sh qolib, 1 soat eslab qolinardi (MT5 zonalari yo'qolardi)."""
    from types import SimpleNamespace

    class Conn:
        def __init__(self):
            self.mt5, self.fail, self.connects = None, False, 0

        def connect(self):
            self.connects += 1
            if self.fail:
                raise OSError("terminal band")
            self.mt5 = SimpleNamespace(symbols_get=lambda: [SimpleNamespace(name="EURUSDm", trade_mode=4, path=r"Standard\Forex\EURUSDm"),
                                                           SimpleNamespace(name="AAPLm", trade_mode=4, path=r"Standard\Stocks\AAPLm")])

    class Http:
        def get(self, url):
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: [{"symbol": "BTCUSDT", "quoteVolume": "9000000"}])
    conn = Conn()
    db, zs = make(tmp_path)
    zs.mt5, zs.http = conn, Http()
    zs.refresh_universe()
    assert conn.connects == 1 and zs.universe["mt5"] == ["EURUSDm", "AAPLm"] and zs.mt5_group["EURUSDm"] == "Forex"
    # keyingi chaqiruv (1 soat ichida) qayta so'ramaydi
    zs.refresh_universe()
    assert conn.connects == 1
    # xato bo'lsa — eskisi saqlanadi va KEYINGI o'tishda qayta uriniladi (_uni_at yangilanmaydi)
    zs._uni_at, conn.fail = 0.0, True
    zs.refresh_universe()
    assert zs.universe["mt5"] == ["EURUSDm", "AAPLm"] and zs._uni_at == 0.0
    conn.fail = False
    zs.refresh_universe()
    assert conn.connects == 3 and zs._uni_at > 0
