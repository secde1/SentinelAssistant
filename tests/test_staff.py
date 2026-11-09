"""Trading bo'limi (Claude xodimlari): bahs, qaror qoidasi, xatoda zdelka ochilmasligi, zarar auditi, veb-boshqaruv.
Soxta LLM bilan (tarmoq/obuna ishlatilmaydi), soxta MT5 bilan."""
from __future__ import annotations

import asyncio
import json

from test_autotrade import auto_service
from test_signals import NOW, cand, run

from agent.staff import roster
from agent.staff.desk import Desk, parse_json
from agent.webcontrol import WebControl


def fake_llm(votes=("approve",) * 4, director="approve", news="Yangilik xavfi yo'q.", fail=False, calls=None):
    """votes: DEBATE-A..D ovozlari; ikkinchi raund ham xuddi shu ovozlarni beradi."""
    async def llm(system: str, prompt: str) -> str:
        if calls is not None:
            calls.append(system.split("rolling: ")[1].split(" —")[0])
        if fail:
            raise RuntimeError("kvota")
        if "DEBATE-" in system:
            idx = "ABCD".index(system.split("DEBATE-")[1][0])
            return json.dumps({"vote": votes[idx], "confidence": 7, "reason": f"asos {idx}"})
        if "DIR-1" in system:
            return "Mana qaror: " + json.dumps({"decision": director, "reason": "yakun"}) + " tamom"
        if "AUDIT-1" in system:
            return "Taxmin: SL juda yaqin."
        return news
    return llm


def sig_row(svc, sv, monkeypatch):
    monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier="CONFIRM", score=7))
    run(sv.scan_once())
    return svc.db.one("SELECT * FROM signals ORDER BY created_at DESC")


def test_roster_has_director_news_four_debaters_audit_and_robot_ids():
    ids = [m.id for m in roster.ALL]
    assert ids[0] == "DIR-1" and "NEWS-1" in ids and "AUDIT-1" in ids and "RISK-1" in ids
    assert [m.id for m in roster.DEBATERS] == ["DEBATE-A", "DEBATE-B", "DEBATE-C", "DEBATE-D"]


def test_parse_json_tolerates_surrounding_text_and_rejects_garbage():
    assert parse_json('oldin {"vote": "approve"} keyin') == {"vote": "approve"}
    assert parse_json("json emas") is None and parse_json("") is None


def test_unanimous_approve_opens_only_with_director_and_logs_everything(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path)
    row = sig_row(svc, sv, monkeypatch)
    calls = []
    desk = Desk(svc.db, fake_llm(calls=calls))
    v = run(desk.review_signal(row))
    assert v.approve and v.decided and list(v.votes.values()) == ["approve"] * 4
    assert len(calls) == 1 + 4 + 1  # NEWS + 4 bahschi (ikkinchi raund yo'q) + DIR
    kinds = [m["kind"] for m in svc.db.query("SELECT kind FROM staff_messages WHERE ref=? ORDER BY id", (row["signal_id"],))]
    assert kinds[0] == "open" and kinds[-1] == "verdict" and kinds.count("vote") == 4 and "news" in kinds and "decision" in kinds
    assert svc.db.one("SELECT approve FROM staff_decisions")["approve"] == 1


def test_split_vote_triggers_second_round_and_two_of_four_is_rejected(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path)
    row = sig_row(svc, sv, monkeypatch)
    calls = []
    v = run(Desk(svc.db, fake_llm(votes=("approve", "approve", "reject", "reject"), calls=calls)).review_signal(row))
    assert not v.approve and v.decided and calls.count("DEBATE-A") == 2  # ikkinchi raund bo'ldi
    assert svc.db.one("SELECT COUNT(*) n FROM staff_messages WHERE kind='vote2'")["n"] == 4


def test_three_of_four_approve_but_director_reject_means_no_trade(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path)
    row = sig_row(svc, sv, monkeypatch)
    assert run(Desk(svc.db, fake_llm(votes=("approve", "approve", "approve", "reject"), director="reject")).review_signal(row)).approve is False
    assert run(Desk(svc.db, fake_llm(votes=("approve", "approve", "approve", "reject"))).review_signal(row)).approve is True


def test_llm_failure_or_missing_llm_never_approves(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path)
    row = sig_row(svc, sv, monkeypatch)
    v = run(Desk(svc.db, fake_llm(fail=True)).review_signal(row))
    assert not v.approve and not v.decided
    v2 = run(Desk(svc.db, None).review_signal(row))
    assert not v2.approve and not v2.decided
    assert svc.db.one("SELECT COUNT(*) n FROM staff_decisions WHERE approve=1")["n"] == 0


def test_auto_mode_with_staff_gate_rejects_means_no_order_and_approve_means_orders(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto")
    sv.desk = Desk(svc.db, fake_llm(votes=("reject",) * 4, director="reject"))
    monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier="CONFIRM", score=7))
    r = run(sv.scan_once())
    assert r["auto"] == 0 and r.get("staff_rejected") == 1 and tr.opens == []
    assert svc.db.one("SELECT status FROM signals")["status"] == "SENT"  # egasiga tugma bilan qoladi
    svc2, sv2, tg2, tr2 = auto_service(tmp_path / "b", trade_mode="auto")
    sv2.desk = Desk(svc2.db, fake_llm())
    monkeypatch.setattr(sv2, "scan_symbol", lambda s: cand(svc2, tier="CONFIRM", score=7))
    r2 = run(sv2.scan_once())
    assert r2["auto"] == 1 and len(tr2.opens) == 2  # bahs tasdiqladi, himoyalar o'tdi


def test_staff_gate_off_keeps_old_behaviour(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto", staff_gate=False)
    sv.desk = Desk(svc.db, fake_llm(votes=("reject",) * 4, director="reject"))
    monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier="CONFIRM", score=7))
    assert run(sv.scan_once())["auto"] == 1


def test_loss_audit_runs_once_for_closed_losing_group_only(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)
    sent = []

    async def notify(t):
        sent.append(t)
    sv.desk, sv.notify_private = Desk(svc.db, fake_llm()), notify
    db = svc.db
    for sid, net in (("L1", -2.0), ("W1", 3.0)):
        db.execute("INSERT INTO demo_groups(signal_id, symbol, side, tickets, legs, sl, risk_money, risk_actual, mode, opened_at, closed_at, status) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,'CLOSED')", (sid, "BTCUSDm", "buy", json.dumps([hash(sid) % 1000]), "[]", 1.0, 1.0, 1.0, "auto",
                                                              NOW.isoformat(), NOW.isoformat()))
        db.execute("INSERT INTO live_trades(position_id, net) VALUES(?,?)", (hash(sid) % 1000, net))
    assert run(sv.audit_closed_losses(NOW)) == 1 and len(sent) == 1 and "AUDIT-1" in sent[0]
    assert run(sv.audit_closed_losses(NOW)) == 0  # ikkinchi marta tahlil qilinmaydi
    assert db.one("SELECT COUNT(*) n FROM staff_decisions WHERE kind='audit'")["n"] == 1


def test_web_control_commands(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)
    notes = []

    async def notify(t):
        notes.append(t)
    wc = WebControl(sv, notify)

    def cmd(c, arg=""):
        svc.db.execute("INSERT INTO control_commands(ts, cmd, arg, source, status) VALUES('t',?,?,'web','pending')", (c, arg))
        run(wc.process_pending())
        return svc.db.one("SELECT * FROM control_commands ORDER BY id DESC")

    r = cmd("mode", "auto")
    assert r["status"] == "done" and sv.trade_mode == "auto" and notes
    assert cmd("stop")["status"] == "done" and sv.trade_mode == "confirm"
    assert cmd("hack", "x")["status"] == "failed"
    assert cmd("mode", "yolo")["status"] == "failed"
    sv.cfg["sizing"] = "fixed"
    bad = cmd("mode", "auto")
    assert bad["status"] == "failed" and "sizing" in bad["result"]
    tr.pos.append({"ticket": 7, "symbol": "BTCUSDm", "side": "buy", "lot": 0.01})
    assert cmd("flat")["status"] == "done" and tr.closed == [7]
    assert cmd("review", "YOQ")["status"] == "failed"


def test_web_confirm_reject_unknown_signal_fails(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def notify(t):
        pass
    wc = WebControl(sv, notify)
    for c in ("confirm", "reject"):
        svc.db.execute("INSERT INTO control_commands(ts, cmd, arg, source, status) VALUES('t',?,?,'web','pending')", (c, "NOPE"))
        run(wc.process_pending())
        assert svc.db.one("SELECT * FROM control_commands ORDER BY id DESC")["status"] == "failed"


def test_web_say_runs_in_background_and_does_not_block(tmp_path):
    from agent.staff.routine import StaffRoutine
    svc, sv, tg, tr = auto_service(tmp_path)

    async def notify(t):
        pass

    async def llm(s, p):
        return '{"assign":[],"note":""}' if "Topshiriqni mos" in p else "javob"
    sv.desk = Desk(svc.db, llm)
    wc = WebControl(sv, notify, StaffRoutine(sv.desk, svc.db, lambda: {}))
    svc.db.execute("INSERT INTO control_commands(ts, cmd, arg, source, status) VALUES('t','say','salom jamoa','web','pending')")

    async def go():
        await wc.process_pending()
        r = svc.db.one("SELECT * FROM control_commands ORDER BY id DESC")
        await asyncio.gather(*wc._bg)
        return r
    r = run(go())
    assert r["status"] == "done" and "qabul" in r["result"]
    assert svc.db.one("SELECT COUNT(*) n FROM staff_messages WHERE role='OWNER'")["n"] == 1
