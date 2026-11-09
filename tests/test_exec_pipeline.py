"""V32 ijro quvuri ishonchliligi: aniq hayot sikli (exec_status), SIG pre-tekshiruvi, paper ajratish, ijro jurnali, voronka.
Soxta MT5/Telegram (haqiqiy buyurtma YO'Q). Strategiya, risk chegaralari, R/R, bahs qoidalari va lot formulasi O'ZGARMAGAN — shu testlar ham
aynan o'sha himoyalar hamon rad etishini tekshiradi."""
from __future__ import annotations

import json
import sqlite3
from datetime import timedelta

import pytest
from test_autotrade import GHistory, GTrader, auto_service, confirm
from test_signals import GROUP, NOW, OWNER, row, run, sent_signal

from agent.staff.desk import Desk
from agent.trading import lifecycle as lc
from agent.trading.db import TradingDB


def audit(svc, sid=None):
    q = "SELECT * FROM execution_audit" + (" WHERE signal_id=?" if sid else "") + " ORDER BY id"
    return svc.db.query(q, (sid,) if sid else ())


def desk(svc, approve=True):
    async def llm(system, prompt):
        if "FAQAT bitta JSON" in system and "vote" in system:
            return json.dumps({"vote": "approve" if approve else "reject", "confidence": 8, "reason": "ok"})
        if "decision" in system:
            return json.dumps({"decision": "approve" if approve else "reject", "reason": "ok"})
        return "xulosa"
    return Desk(svc.db, llm, calendar=svc.calendar)


# ------------------------------------------------------------------------------------------------ 1. holatlar
def test_debate_approval_is_not_an_executed_trade(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto")
    sv.desk = desk(svc, approve=True)

    async def go():
        sid = await sent_signal(svc, sv)
        assert row(svc, sid)["exec_status"] == lc.GENERATED
        assert await sv.staff_gate({"signal_id": sid}) is True
        r = row(svc, sid)
        assert r["exec_status"] == lc.DEBATE_APPROVED and r["status"] == "SENT"  # faqat ruxsat — zdelka YO'Q
        assert tr.opens == [] and svc.db.one("SELECT COUNT(*) n FROM demo_groups")["n"] == 0
        assert [a["decision"] for a in audit(svc, sid)] == ["DEBATE_APPROVED"]
        assert audit(svc, sid)[0]["mt5_request"] == lc.MT5_NOT_SENT and audit(svc, sid)[0]["debate_result"].startswith("approve 4/4")
    run(go())


def test_risk_rejection_after_debate_approval_is_refused_and_never_sent_to_mt5(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto")
    sv.desk = desk(svc, approve=True)

    async def go():
        sid = await sent_signal(svc, sv)  # pre-tekshiruv o'tdi (tugma bor)
        assert tg.sent[-1]["markup"] is not None
        assert await sv.staff_gate({"signal_id": sid})
        tr.spread = 2.0  # bahsdan keyin spred kengaydi: ijro paytida QAYTA tekshiruv ushlaydi
        ans = await sv.auto_confirm(sid)
        r = row(svc, sid)
        assert "spred" in ans and r["status"] == "REFUSED" and r["exec_status"] == lc.EXECUTION_REFUSED
        assert tr.opens == [] and svc.db.one("SELECT COUNT(*) n FROM demo_groups")["n"] == 0
        last = audit(svc, sid)[-1]
        assert (last["decision"], last["stage"], last["risk_result"], last["mt5_request"]) == ("EXECUTION_REFUSED", "risk_plan", "refused", lc.MT5_NOT_SENT)
        assert last["debate_result"].startswith("approve") and last["origin"] == lc.ORIGIN_AUTO and last["mt5_retcode"] is None
        assert "spred" in last["reason"] and last["ts"].endswith("+00:00")
    run(go())


# ------------------------------------------------------------------------------------------------ 2. SIG pre-tekshiruv
@pytest.mark.parametrize("kw,trader_kw,history_bal,why", [
    ({}, {"spread": 2.0}, 100.0, "spred"),  # spred
    ({"min_lot_fallback": True}, {}, 0.5, "minimal lot"),  # minimal lot riski > chegara
    ({}, {}, 0.5, "minimumi"),  # fallback o'chiq: 1% uchun lot < minimum
])
def test_sig_precheck_blocks_button_and_states_exact_reason(tmp_path, kw, trader_kw, history_bal, why):
    tr = GTrader(**trader_kw)
    svc, sv, tg, tr = auto_service(tmp_path, tr, GHistory(tr, balance=history_bal), **kw)

    async def go():
        sid = await sent_signal(svc, sv)
        msg = tg.sent[-1]
        assert msg["markup"] is None and "IJRO MUMKIN EMAS" in msg["text"] and why in msg["text"]  # tugma yo'q, sabab aniq
        r = row(svc, sid)
        assert r["status"] == "REFUSED" and r["exec_status"] == lc.EXECUTION_REFUSED and why in r["decision_note"]
        a = audit(svc, sid)
        assert [x["decision"] for x in a] == ["PRECHECK_REFUSED"] and a[0]["mt5_request"] == lc.MT5_NOT_SENT and a[0]["risk_result"] == "refused"
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)  # eski xabardan bosilsa ham — xavf nazorati chetlanmaydi
        assert "Ijro mumkin emas" in ans and why in ans and tr.opens == []
    run(go())


def test_sig_precheck_passes_shows_button_and_execution_revalidates(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        assert tg.sent[-1]["markup"] is not None and row(svc, sid)["status"] == "SENT" and audit(svc, sid) == []
        tr.spread = 2.0  # tugma ko'rsatilgandan keyin sharoit yomonlashdi
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "spred" in ans and tr.opens == [] and row(svc, sid)["exec_status"] == lc.EXECUTION_REFUSED
        assert audit(svc, sid)[-1]["origin"] == lc.ORIGIN_MANUAL
    run(go())


def test_stale_quote_is_refused_at_precheck_and_at_execution(tmp_path):
    tr = GTrader()
    orig = tr.symbol_spec
    tr.symbol_spec = lambda name: {**orig(name), "quote_age_s": 5000.0}  # kotirovka 83 daqiqa eski (bozor yopiq / uzilish)
    svc, sv, tg, tr = auto_service(tmp_path, tr)

    async def go():
        sid = await sent_signal(svc, sv)
        assert "kotirovka eskirgan" in row(svc, sid)["decision_note"] and tg.sent[-1]["markup"] is None and tr.opens == []
        # yangi kotirovka (None = noma'lum yosh) tekshirilmaydi; yangi bo'lsa o'tadi
        tr.symbol_spec = lambda name: {**orig(name), "quote_age_s": 3.0}
        sid2 = await sent_signal(svc, sv, direction="SHORT")
        assert row(svc, sid2)["status"] == "SENT" and tg.sent[-1]["markup"] is not None
    run(go())


def test_expired_signal_is_not_executable_and_is_audited(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv, valid_h=1)
        svc.clock = lambda: NOW + timedelta(hours=2)
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "Muddati o'tgan" in ans and tr.opens == []
        assert row(svc, sid)["exec_status"] == lc.EXPIRED
        assert [(a["decision"], a["stage"]) for a in audit(svc, sid)] == [("EXPIRED", "expired")]
    run(go())


def test_price_moved_signal_is_invalidated_at_execution(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        last = float(svc.market.history("BTCUSDT", "1h", 50, need=30).candles[-1].close)
        # reja (SL/TP joriy narxning to'g'ri tomonida) pre-tekshiruvdan o'tadi, lekin signal kirishi joriy narxdan ancha uzoq -> ijro paytida qayta tekshiruv
        sid = await sent_signal(svc, sv, entry=last + 500, sl=last - 5, tp=last + 1000)
        assert row(svc, sid)["status"] == "SENT"
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "ancha o'zgargan" in ans and tr.opens == []
        a = audit(svc, sid)[-1]
        assert (a["decision"], a["stage"], a["mt5_request"]) == ("EXECUTION_REFUSED", "revalidate", lc.MT5_NOT_SENT)
        assert row(svc, sid)["exec_status"] == lc.INVALIDATED
    run(go())


# ------------------------------------------------------------------------------------------------ 3. paper ajratish
def test_paper_datasets_are_separated_and_stats_use_executable_only(tmp_path):
    async def go():
        svc, sv, tg, tr = auto_service(tmp_path / "a", max_groups=3)
        ok_sid, _ = await confirm(svc, sv)  # ijro bo'ldi
        assert svc.db.one("SELECT dataset FROM paper_positions WHERE signal_id=?", (ok_sid,))["dataset"] == lc.DS_EXECUTABLE
        # ikkinchi signal: pre-tekshiruv o'tadi, tugmadan keyin spred kengayadi -> ijro rad -> COUNTERFACTUAL
        sid2 = await sent_signal(svc, sv, direction="SHORT")
        assert row(svc, sid2)["status"] == "SENT"
        tr.spread = 2.0
        await sv.handle_callback(f"sentinel:confirm:{sid2}", OWNER, GROUP)
        # majburiy sinov (spred normal; qarama-qarshi yo'nalish, takroriy pozitsiya yo'q) -> TEST
        tr.spread = 0.2
        svc.settings.data["signals"]["max_groups"] = 5
        tr.pos[:] = []
        svc.db.execute("UPDATE demo_groups SET status='CLOSED'")
        sid3 = await sent_signal(svc, sv, direction="LONG", entry=None)
        assert row(svc, sid3)["status"] == "SENT"
        await sv.auto_confirm(sid3, origin=lc.ORIGIN_FORCED)
        ds = {r["signal_id"]: r["dataset"] for r in svc.db.query("SELECT signal_id, dataset FROM paper_positions")}
        assert ds == {ok_sid: lc.DS_EXECUTABLE, sid2: lc.DS_COUNTERFACTUAL, sid3: lc.DS_TEST}
        # statistika faqat EXECUTABLE ni sanaydi
        svc.db.execute("UPDATE paper_positions SET status='TP_HIT', r_multiple=2.0 WHERE signal_id=?", (ok_sid,))
        svc.db.execute("UPDATE paper_positions SET status='SL_HIT', r_multiple=-1.0 WHERE signal_id IN (?,?)", (sid2, sid3))
        st = sv.stats()
        assert st["closed"] == 1 and st["total_r"] == 2.0  # rad etilgan va sinov (-1R) aralashmaydi
    run(go())


def test_counterfactual_paper_never_notifies_owner(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        tr.spread = 2.0
        await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        n0 = len(tg.sent)
        svc.db.execute("UPDATE paper_positions SET status='SL_HIT', r_multiple=-1.0 WHERE signal_id=?", (sid,))
        assert await sv._notify_position(sid) == 0 and len(tg.sent) == n0
        assert "COUNTERFACTUAL" in svc.db.one("SELECT detail FROM signal_events WHERE signal_id=? AND kind='paper_opened'", (sid,))["detail"]
    run(go())


def test_migration_backfills_dataset_from_evidence_and_keeps_history(tmp_path):
    p = tmp_path / "legacy.db"
    c = sqlite3.connect(p)  # eski sxema: yangi ustunlar yo'q
    c.executescript("""
    CREATE TABLE signals (signal_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT, direction TEXT NOT NULL,
      strategy_id TEXT, strategy_version INTEGER, entry_type TEXT, entry REAL, sl REAL, tp REAL, rr REAL, rr_net REAL, score INTEGER, tier TEXT,
      status TEXT NOT NULL, valid_until TEXT, data_ts TEXT, data_source TEXT, analysis TEXT, invalidation TEXT, text TEXT, chat_id INTEGER,
      message_id INTEGER, decided_at TEXT, decided_by INTEGER, decision_note TEXT);
    CREATE TABLE paper_positions (signal_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, entry_type TEXT, entry_signal REAL,
      sl REAL, tp REAL, confirmed_at TEXT NOT NULL, data_end TEXT, valid_until TEXT, status TEXT NOT NULL, spread REAL, commission REAL,
      max_hold INTEGER, invalidation TEXT, entry_time TEXT, entry_price REAL, exit_time TEXT, exit_price REAL, r_multiple REAL, cost_r REAL,
      last_bar_ts TEXT, note TEXT, notified TEXT, trend_warned INTEGER DEFAULT 0);
    CREATE TABLE signal_events (id INTEGER PRIMARY KEY, signal_id TEXT NOT NULL, ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT);
    CREATE TABLE staff_decisions (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT, approve INTEGER, votes TEXT, reason TEXT);
    """)
    for sid, st in (("SIG-1", "CONFIRMED"), ("SIG-2", "CONFIRMED"), ("TST-1", "CONFIRMED"), ("ZON-1", "CONFIRMED"), ("ZON-2", "CONFIRMED")):
        c.execute("INSERT INTO signals(signal_id, created_at, symbol, direction, status) VALUES(?,?,?,?,?)", (sid, "2026-11-08T10:00:00+00:00", "X", "LONG", st))
        c.execute("INSERT INTO paper_positions(signal_id, symbol, direction, confirmed_at, status) VALUES(?,?,?,?,?)", (sid, "X", "LONG", "t", "PENDING"))
    c.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES('SIG-1','t','demo_refused','x')")  # rad etilgan
    c.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES('SIG-2','t','demo_opened','x')")  # ochilgan
    c.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES('ZON-1','t','auto_confirm','x')")  # bahssiz AUTO = majburiy sinov
    c.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES('ZON-2','t','auto_confirm','x')")
    c.execute("INSERT INTO staff_decisions(ts, kind, ref, approve, votes, reason) VALUES('t','signal','ZON-2',1,'{}','ok')")  # bahsdan o'tgan
    c.commit()
    c.close()
    before = sqlite3.connect(p).execute("SELECT signal_id, status FROM signals ORDER BY 1").fetchall()
    db = TradingDB(p)  # migratsiya
    ds = {r["signal_id"]: r["dataset"] for r in db.query("SELECT signal_id, dataset FROM paper_positions")}
    assert ds == {"SIG-1": lc.DS_COUNTERFACTUAL, "SIG-2": lc.DS_EXECUTABLE, "TST-1": lc.DS_TEST, "ZON-1": lc.DS_TEST, "ZON-2": lc.DS_EXECUTABLE}
    assert [(r["signal_id"], r["status"]) for r in db.query("SELECT signal_id, status FROM signals ORDER BY 1")] == before  # tarix o'zgarmadi
    assert all(r["exec_status"] is None for r in db.query("SELECT exec_status FROM signals"))  # eski qatorlar to'ldirilmaydi (hisoblanadi)
    db.close()
    TradingDB(p).close()  # takroriy ishga tushirish xavfsiz (idempotent)


@pytest.mark.parametrize("status,kinds,decided_by,want", [
    ("WATCH", [], None, lc.WATCH), ("EXPIRED", [], None, lc.EXPIRED), ("SENT", [], None, lc.GENERATED),
    ("SENT", ["staff_approve"], None, lc.DEBATE_APPROVED), ("SENT", ["staff_reject"], None, lc.DEBATE_REJECTED),
    ("REJECTED", ["staff_reject"], 0, lc.DEBATE_REJECTED), ("REJECTED", [], 871134228, lc.EXECUTION_REFUSED),
    ("INVALIDATED", ["staff_reject"], None, lc.INVALIDATED), ("INVALIDATED", ["demo_refused"], None, lc.EXECUTION_REFUSED),
    ("CONFIRMED", ["demo_opened"], None, lc.EXECUTED), ("CONFIRMED", ["demo_refused"], None, lc.EXECUTION_REFUSED),  # eski noaniq CONFIRMED
    ("CONFIRMED", [], None, lc.EXECUTION_READY), ("CONFIRMING", [], None, lc.RISK_VALIDATION_PENDING), ("REFUSED", [], None, lc.EXECUTION_REFUSED)])
def test_legacy_rows_derive_explicit_status(status, kinds, decided_by, want):
    assert lc.derive_exec_status({"status": status, "decided_by": decided_by}, kinds) == want
    assert lc.derive_exec_status({"status": "CONFIRMED", "exec_status": lc.EXECUTED}, ["demo_refused"]) == lc.EXECUTED  # aniq qiymat ustun


# ------------------------------------------------------------------------------------------------ 4. kelib chiqish va jurnal
def test_manual_vs_automatic_vs_forced_origin_and_accurate_logging(tmp_path):
    async def go():
        # qo'lda (HA tugmasi)
        svc, sv, tg, tr = auto_service(tmp_path / "m", max_groups=3)
        sid, ans = await confirm(svc, sv)
        r, a = row(svc, sid), audit(svc, sid)[-1]
        assert "ochildi" in ans and (r["origin"], r["exec_status"], r["status"]) == (lc.ORIGIN_MANUAL, lc.EXECUTED, "CONFIRMED")
        assert (a["decision"], a["stage"], a["mt5_request"], a["mt5_retcode"], a["origin"], a["risk_result"]) == \
            ("EXECUTED", "mt5_order_send", lc.MT5_SENT_OK, 10009, lc.ORIGIN_MANUAL, "passed")
        assert len(tr.opens) == 2
        # avtomatik
        svc, sv, tg, tr = auto_service(tmp_path / "a", trade_mode="auto")
        sid = await sent_signal(svc, sv)
        await sv.auto_confirm(sid)
        assert (row(svc, sid)["origin"], audit(svc, sid)[-1]["origin"]) == (lc.ORIGIN_AUTO, lc.ORIGIN_AUTO)
        # majburiy sinov: avtomatik SANALMAYDI
        svc, sv, tg, tr = auto_service(tmp_path / "f", trade_mode="auto")
        sid = await sent_signal(svc, sv)
        await sv.auto_confirm(sid, origin=lc.ORIGIN_FORCED)
        a = audit(svc, sid)[-1]
        assert a["origin"] == lc.ORIGIN_FORCED and a["debate_result"] == "skipped (forced_test)" and a["decision"] == "EXECUTED"
        assert svc.db.one("SELECT dataset FROM paper_positions WHERE signal_id=?", (sid,))["dataset"] == lc.DS_TEST
    run(go())


def test_order_check_rejection_is_logged_as_check_rejected_not_order_send(tmp_path):
    class CheckFail(GTrader):
        def open(self, symbol, side, lot, sl, tp=None, dry_run=False, comment=None):
            return {"ok": False, "stage": "order_check", "retcode": 10019, "comment": "No money"}
    svc, sv, tg, tr = auto_service(tmp_path, CheckFail())

    async def go():
        sid, ans = await confirm(svc, sv)
        a = audit(svc, sid)[-1]
        assert "No money" in ans and (a["decision"], a["stage"], a["mt5_request"], a["mt5_retcode"]) == \
            ("EXECUTION_REFUSED", "order_check", lc.MT5_CHECK_REJECTED, 10019)
        assert a["risk_result"] == "passed"  # risk o'tdi, MT5 tekshiruvi rad etdi — ikkalasi alohida ko'rinadi
        assert svc.db.one("SELECT COUNT(*) n FROM demo_groups")["n"] == 0 and row(svc, sid)["exec_status"] == lc.EXECUTION_REFUSED
    run(go())


def test_owner_reject_and_debate_reject_are_distinct_states(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        await sv.handle_callback(f"sentinel:reject:{sid}", OWNER, GROUP)
        a = audit(svc, sid)[-1]
        assert row(svc, sid)["exec_status"] == lc.EXECUTION_REFUSED and (a["stage"], a["origin"]) == ("owner_reject", lc.ORIGIN_MANUAL)
        sv.desk = desk(svc, approve=False)
        sid2 = await sent_signal(svc, sv, direction="SHORT")
        assert not await sv.staff_gate({"signal_id": sid2})
        assert row(svc, sid2)["exec_status"] == lc.DEBATE_REJECTED and audit(svc, sid2)[-1]["decision"] == "DEBATE_REJECTED"
    run(go())


# ------------------------------------------------------------------------------------------------ 5. takrorlanish
def test_duplicate_confirmation_opens_exactly_one_group(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto")

    async def go():
        import asyncio
        sid = await sent_signal(svc, sv)
        res = await asyncio.gather(sv.auto_confirm(sid), sv.auto_confirm(sid), sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP))
        assert svc.db.one("SELECT COUNT(*) n FROM demo_groups WHERE signal_id=?", (sid,))["n"] == 1
        assert len(tr.opens) == 2  # bitta guruh (A+B), ikkinchi/uchinchi chaqiruv hech narsa ochmadi
        assert sum(1 for r in res if r and "ochildi" in r) == 1
        assert sum(1 for a in audit(svc, sid) if a["decision"] == "EXECUTED") == 1
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "Allaqachon" in ans and len(tr.opens) == 2
    run(go())


def test_same_symbol_direction_cannot_be_executed_twice(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, max_groups=3)

    async def go():
        await confirm(svc, sv)
        sid2 = await sent_signal(svc, sv)  # xuddi shu simvol/yo'nalish: pre-tekshiruv ochiq pozitsiyani ko'radi
        assert "allaqachon ochiq" in row(svc, sid2)["decision_note"] and tg.sent[-1]["markup"] is None and len(tr.opens) == 2
    run(go())


# ------------------------------------------------------------------------------------------------ 6. API / voronka
def test_execution_api_counts_each_class_separately(tmp_path):
    from agent.dashboard.desk_api import DeskView
    db_path = tmp_path / "trading_memory" / "database" / "trading_research.db"
    db_path.parent.mkdir(parents=True)
    db = TradingDB(db_path)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def sig(sid, status, kinds=(), decided_by=None, exec_status=None):
        db.execute("INSERT INTO signals(signal_id, created_at, symbol, direction, status, decided_by, exec_status) VALUES(?,?,?,?,?,?,?)",
                   (sid, now, "X", "LONG", status, decided_by, exec_status))
        for k in kinds:
            db.execute("INSERT INTO signal_events(signal_id, ts, kind, detail) VALUES(?,?,?,?)", (sid, now, k, "d 12.5"))
    sig("SIG-A", "WATCH")
    sig("SIG-B", "SENT", ["sent", "staff_reject"])
    sig("SIG-C", "CONFIRMED", ["sent", "staff_approve", "auto_confirm", "demo_opened"], 0)  # avtomatik zdelka
    db.execute("INSERT INTO staff_decisions(ts, kind, ref, approve, votes, reason) VALUES(?,?,?,?,?,?)", (now, "signal", "ZON-D", 0, "{}", "r"))
    sig("ZON-D", "CONFIRMED", ["sent", "staff_reject", "demo_refused"], 871134228)  # bahs rad etgan, egasi bosdi, risk rad etdi
    sig("ZON-E", "CONFIRMED", ["sent", "auto_confirm", "demo_opened"], 0)  # bahssiz AUTO = majburiy sinov
    sig("SIG-F", "INVALIDATED", ["sent", "invalidated"])
    sig("SIG-G", "EXPIRED", ["sent", "expired"])
    sig("TST-H", "CONFIRMED", ["demo_opened"])  # TEST — sanalmaydi
    d = DeskView(tmp_path).execution()
    c = d["windows"]["all"]["counters"]
    assert c["generated"] == 7 and c["watch"] == 1 and c["sent"] == 6
    assert c["debate_rejected"] == 2 and c["debate_approved"] == 1
    assert c["mt5_executed"] == 1 and c["manual_test_orders"] == 1  # majburiy sinov AVTOMATIK ga qo'shilmaydi
    assert c["risk_approved"] == 2 and c["risk_refused"] == 1 and c["expired_invalidated"] == 2 and c["owner_override_after_reject"] == 1
    stops = {x["status"]: x["n"] for x in d["windows"]["all"]["stopped_at"]}
    assert stops[lc.EXECUTION_REFUSED] == 1 and stops[lc.DEBATE_REJECTED] == 1 and stops[lc.WATCH] == 1
    assert [f["stage"] for f in d["windows"]["all"]["funnel"]] == ["GENERATED", "SENT", "DEBATE_APPROVED", "RISK_APPROVED", "EXECUTION_READY", "EXECUTED"]
    assert d["windows"]["today"]["counters"]["generated"] == 7
    sl = DeskView(tmp_path).signals()["items"]
    by = {x["signal_id"]: x for x in sl}
    assert by["ZON-E"]["origin"] == lc.ORIGIN_FORCED and by["SIG-C"]["origin"] == lc.ORIGIN_AUTO and by["ZON-D"]["exec_status"] == lc.EXECUTION_REFUSED
    db.close()


def test_positions_api_keeps_paper_counterfactual_and_tests_apart(tmp_path):
    from agent.dashboard.desk_api import DeskView
    db_path = tmp_path / "trading_memory" / "database" / "trading_research.db"
    db_path.parent.mkdir(parents=True)
    db = TradingDB(db_path)
    for sid, ds in (("S1", lc.DS_EXECUTABLE), ("S2", lc.DS_COUNTERFACTUAL), ("S3", lc.DS_TEST)):
        db.execute("INSERT INTO paper_positions(signal_id, symbol, direction, confirmed_at, status, r_multiple, dataset) VALUES(?,?,?,?,?,?,?)",
                   (sid, "X", "LONG", "2026-11-09", "SL_HIT", -1.0 if ds != lc.DS_EXECUTABLE else 2.0, ds))
    v = DeskView(tmp_path)
    p = v.positions()
    assert [x["signal_id"] for x in p["paper"]] == ["S1"] and [x["signal_id"] for x in p["counterfactual"]] == ["S2"] and [x["signal_id"] for x in p["tests"]] == ["S3"]
    assert v.dashboard()["kpi"]["paper_r"] == 2.0  # KPI faqat ijro qilinadigan paper
    db.close()
