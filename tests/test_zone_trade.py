"""DIR-1 zona vazifasi: aktiv zonadan zdelka (faqat AUTO + DEMO + barcha himoya) va zdelka ochilgach yangi shart."""
from __future__ import annotations

import json

from test_autotrade import auto_service
from test_signals import run

from agent.staff.desk import Desk
from agent.zones.scanner import ZoneScanner
from agent.zones.trade import ZoneTrader, build_setup

LONGZ = {"kind": "support", "low": 99.0, "high": 100.0, "tf": "1h", "detector": "ZONE-1", "strength": 30, "note": "t", "symbol": "X"}


def test_build_setup_directional_rr_and_refusals():
    s, why = build_setup(LONGZ, 99.8, 1.0, [{"kind": "resistance", "low": 110.0, "high": 111.0}])
    assert s and s.direction == "LONG" and s.sl <= 99.8 - 1.0 and s.tp == 110.0 and s.rr_net >= 1.5 and "qarshi zona" in s.tp_note
    s, why = build_setup(LONGZ, 99.8, 1.0, [{"kind": "resistance", "low": 100.5, "high": 101.0}])
    assert s is None and "R/R" in why  # yo'lda qarshi zona yaqin
    s, why = build_setup({**LONGZ, "kind": "range"}, 99.8, 1.0, [])
    assert s is None and "yo'nalishsiz" in why
    sh, _ = build_setup({**LONGZ, "kind": "resistance", "low": 100.0, "high": 101.0}, 100.2, 2.0, [])
    assert sh and sh.direction == "SHORT" and sh.sl >= 100.2 + 2.0 and sh.tp < 100.2
    assert build_setup(LONGZ, 99.8, 0, [])[0] is None


def _env(tmp_path, approve=True, mode="auto", **cfg):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode=mode, **cfg)

    async def llm(system, prompt):
        if "FAQAT bitta JSON" in system and "vote" in system:
            return json.dumps({"vote": "approve" if approve else "reject", "confidence": 8, "reason": "ok"})
        if "decision" in system:
            return json.dumps({"decision": "approve" if approve else "reject", "reason": "ok"})
        return "xulosa"
    sv.desk = Desk(svc.db, llm, calendar=svc.calendar)
    zs = ZoneScanner(svc, sv.desk, None)
    zs.universe = {"binance": ["BTCUSDT"], "mt5": ["BTCUSDm"]}
    price = tr.last
    svc.db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, note, status, dist_atr, price, first_seen, last_seen) "
                   "VALUES('z1','BTCUSDT','binance','ZONE-1','support','1h',?,?,40,'t','active',0,?,'t','t')", (price - 3.0, price + 0.3, price))
    zt = ZoneTrader(sv, zs, cfg={"trade_min_rr": 0.5})
    zt._near_obstacle = lambda s, f1: None  # sintetik bozor swing'lari testni bezovta qilmasin (alohida testda tekshiriladi)
    return svc, sv, tg, tr, zt


def test_zone_trade_goes_through_staff_gate_and_all_guards(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)

    async def go():
        await zt.on_pass()
    run(go())
    sig = svc.db.one("SELECT * FROM signals WHERE strategy_id='ZONE-DIR'")
    assert sig and sig["tier"] == "ZONE" and sig["signal_id"].startswith("ZON-")
    assert svc.db.one("SELECT approve FROM staff_decisions WHERE ref=?", (sig["signal_id"],))["approve"] == 1  # bahs shart
    assert sig["status"] == "CONFIRMED" and len(tr.opens) >= 1
    assert all(o["sl"] for o in tr.opens)  # SL majburiy
    assert svc.db.one("SELECT COUNT(*) n FROM demo_groups WHERE status='OPEN'")["n"] == 1
    # zdelka ochilgach: DIR-1 sharti + ZONE-1..5 tasdig'i
    d = zt.directive()
    assert d and d["symbol"] == "BTCUSDT" and d["min_strength"] >= 30
    acks = {r["role"] for r in svc.db.query("SELECT role FROM staff_messages WHERE kind='directive-ack'")}
    assert acks == {"ZONE-1", "ZONE-2", "ZONE-3", "ZONE-4", "ZONE-5"}


def test_staff_rejection_or_not_auto_means_no_trade(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path / "a", approve=False)
    run(zt.on_pass())
    assert not tr.opens
    row = svc.db.one("SELECT status, decision_note FROM signals WHERE strategy_id='ZONE-DIR'")
    assert row and row["status"] == "REJECTED" and "bahs rad etdi" in row["decision_note"]  # tugmasiz signal osilib qolmaydi
    assert tg.edits and "AUTO: bahs rad etdi" in tg.edits[-1][2]  # Telegram xabari ham yangilandi
    assert not [x for x in tg.sent if x['markup']]  # tugma hech qachon yuborilmagan
    svc2, sv2, tg2, tr2, zt2 = _env(tmp_path / "b", mode="confirm")
    run(zt2.on_pass())
    assert not tr2.opens and svc2.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == 0  # AUTO emas


def test_open_position_blocks_new_trade_and_sets_queue_rules(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    svc.db.execute("INSERT INTO demo_groups(signal_id, symbol, side, status, opened_at) VALUES('S-OPEN','ETHUSDT','buy','OPEN','t')")
    run(zt.on_pass())
    assert not tr.opens and svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == 0
    zt.set_directive({"symbol": "BTCUSDT", "signal": "S1"}, announce=True)
    sc = zt.scanner
    news = [{"symbol": "BTCUSDT", "strength": 90, "dist_atr": 0, "detector": "ZONE-1", "id": "a", "kind": "support", "tf": "1h", "low": 1, "high": 2,
             "price": 1.5, "source": "binance", "note": "", "status": "active"},
            {"symbol": "ETHUSDT", "strength": 12, "dist_atr": 0, "detector": "ZONE-1", "id": "b", "kind": "support", "tf": "1h", "low": 1, "high": 2,
             "price": 1.5, "source": "binance", "note": "", "status": "active"},
            {"symbol": "SOLUSDT", "strength": 50, "dist_atr": 0, "detector": "ZONE-1", "id": "c", "kind": "support", "tf": "1h", "low": 1, "high": 2,
             "price": 1.5, "source": "binance", "note": "", "status": "active"}]
    svc.db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, status, first_seen, last_seen) "
                   "VALUES('c','SOLUSDT','binance','ZONE-1','support','1h',1,2,50,'active','t','t')")
    got = sc.announce(news)
    assert [z["symbol"] for z in got] == ["SOLUSDT"]  # ochiq instrument va kuchsiz zona shart bo'yicha o'tmaydi
    zt.set_directive(None)
    assert zt.directive() is None


def test_web_zone_command_runs_trade_task_and_respects_mode(tmp_path):
    import asyncio
    from agent.webcontrol import WebControl
    svc, sv, tg, tr, zt = _env(tmp_path)

    async def notify(t):
        pass
    wc = WebControl(sv, notify)
    wc.zone_trader = zt
    svc.db.execute("INSERT INTO control_commands(ts, cmd, arg, source, status) VALUES('t','zone','','web','pending')")

    async def go():
        await wc.process_pending()
        r = svc.db.one("SELECT * FROM control_commands ORDER BY id DESC")
        await asyncio.gather(*wc._bg)
        return r
    r = run(go())
    assert r["status"] == "done" and svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == 1
    sv.cfg["trade_mode"] = "confirm"
    svc.db.execute("INSERT INTO control_commands(ts, cmd, arg, source, status) VALUES('t','zone','','web','pending')")
    run(wc.process_pending())
    assert svc.db.one("SELECT status, result FROM control_commands ORDER BY id DESC")["status"] == "failed"


def test_manual_run_explains_why_no_trade_and_status_is_recorded(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path, mode="auto")
    svc.db.execute("UPDATE zones SET kind='range'")  # yo'nalishsiz -> nomzod yo'q
    run(zt.on_pass(manual=True))
    msg = svc.db.one("SELECT text FROM staff_messages WHERE role='DIR-1' AND kind='report'")
    assert msg and "nomzod" in msg["text"] and not tr.opens
    st = json.loads(svc.db.one("SELECT value FROM meta WHERE key='zone_trade_status'")["value"])
    assert st["enabled"] is True and st["candidates"] == 0 and "Forex" in st["categories"]


def test_owner_question_about_trading_never_opens_a_trade_and_dir_sees_real_status(tmp_path):
    """Egasi 'zdelka ochasanmi?' deb SAVOL berdi — kalit so'z bo'yicha zdelka ochilmaydi; DIR-1 haqiqiy holatdan javob beradi."""
    from agent.staff.routine import StaffRoutine
    svc, sv, tg, tr, zt = _env(tmp_path, mode="auto")
    prompts = []

    async def llm(system, prompt):
        prompts.append(prompt)
        if "Topshiriqni mos xodimlarga" in prompt:
            return '{"assign":[{"role":"RISK-1","task":"holatni ayt"}],"note":""}'
        return "javob"
    sv.desk = Desk(svc.db, llm)
    run(zt.on_pass())  # holat yoziladi (nomzod bo'lsa signal ham — buni sanab qo'yamiz)
    before = svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"]
    rt = StaffRoutine(sv.desk, svc.db, lambda: sv.cfg)
    run(rt.handle_owner("zdelka ochishni suramadim, savol berdim: zdelka ocholasanmi yoqmi, tasdiqimsiz?"))
    assert svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == before  # savol zdelka ochmadi
    assert any("DIR-1 ZONA ZDELKA VAZIFASI" in p for p in prompts)  # haqiqiy holat xodimlarga berildi
    assert any("tasdig'i shart emas" in p or "egasi tasdig'isiz" in p for p in prompts)


def test_mt5_instruments_are_tradable_only_in_allowed_categories(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    zt.scanner.universe["mt5"] = ["EURUSDm", "XAUUSDm", "AAPLm", "BTCUSDm", "US30m"]
    zt.scanner.mt5_group = {"EURUSDm": "Forex", "XAUUSDm": "Metals", "AAPLm": "Stocks", "BTCUSDm": "Crypto", "US30m": "Indices"}
    assert zt._tradable("EURUSDm", "mt5") and zt._tradable("XAUUSDm", "mt5") and zt._tradable("US30m", "mt5")
    assert not zt._tradable("AAPLm", "mt5") and not zt._tradable("BTCUSDm", "mt5")  # aksiya va MT5-kripto (Binance bilan takrorlanadi) yoqilmagan
    assert not zt._tradable("NOPEm", "mt5")  # terminalda to'liq savdoga ochiq emas
    assert zt._tradable("BTCUSDT", "binance") is True  # MT5 DEMO'da BTCUSDm bor -> Binance BTCUSDT zonasi savdoga yaroqli
    zt.scanner.universe["mt5"] = ["EURUSDm"]
    assert zt._tradable("BTCUSDT", "binance") is False  # MT5'da juftlik yo'q -> faqat ko'rsatiladi


def test_mt5_zone_registers_instrument_with_real_spread(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    zt.scanner.mt5_group = {"EURUSDm": "Forex"}
    tr.symbol_spec = lambda name: {"ask": 1.10010, "bid": 1.10000, "spread": 0.0001, "symbol": "EURUSDm"}
    zt._ensure_instrument({"source": "mt5", "symbol": "EURUSDm"})
    inst = svc.settings.instrument("EURUSDm")
    assert inst["provider"] == "mt5" and inst["market"] == "forex" and inst["commission_pct"] == 0.0 and 0.5 < inst["spread_bps"] < 1.5
    before = dict(svc.settings.data.get("instruments", {}))
    zt._ensure_instrument({"source": "binance", "symbol": "BTCUSDT"})  # binance uchun o'zgarmaydi
    assert svc.settings.data.get("instruments", {}) == before


def test_test_mode_ignores_opposing_zone_but_keeps_guards(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    p = tr.last
    svc.db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, status, first_seen, last_seen) "
                   "VALUES('opp','BTCUSDT','binance','ZONE-1','resistance','1h',?,?,50,'fresh','t','t')", (p + 0.3, p + 0.5))
    run(zt.on_pass(manual=True))  # oddiy rejim: qarshi zona yaqin -> nomzod o'tmaydi
    assert svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == 0
    run(zt.on_pass(manual=True, test=True))  # sinov: TP=2R, qolgan himoyalar o'sha-o'sha
    s = svc.db.one("SELECT * FROM signals WHERE strategy_id='ZONE-DIR'")
    assert s and s["status"] == "CONFIRMED" and tr.opens


def test_session_gaps_do_not_block_mt5_zones_but_do_block_crypto(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    gap = ["48 ta sham tushib qolgan (bozor yopiq bo'lgan vaqt bo'lishi mumkin)"]
    real = zt._bundles
    zt._ensure_instrument = lambda z: None

    def with_gap(symbol):
        bs = real(symbol)
        for b in bs:
            b.warnings = list(gap)
        return bs
    zt._bundles = with_gap
    z_mt5 = {"id": "x", "symbol": "BTCUSDT", "source": "mt5", "kind": "support", "tf": "1h", "low": tr.last - 3, "high": tr.last + 1, "strength": 30, "detector": "ZONE-1", "note": ""}
    s, why, _ = zt._setup(z_mt5)
    assert s is not None  # forex: hafta oxiri bo'shlig'i normal
    s, why, _ = zt._setup({**z_mt5, "source": "binance", "symbol": "BTCUSDT"})
    assert s is None and "ma'lumot sifati" in why  # kripto: bo'shliq — xato
    zt._bundles = real


def test_zone_signals_need_two_of_four_but_regular_signals_still_three(tmp_path):
    """Egasi qarori: ZONE-DIR uchun bahs 2/4 + DIR-1 (har doim shart); oddiy strategiya signallari 3/4 qoladi."""
    db = __import__("agent.trading.db", fromlist=["TradingDB"]).TradingDB(tmp_path / "d.db")
    n = {"i": 0}

    async def llm(system, prompt):
        if "decision" in system:
            return '{"decision": "approve", "reason": "ok"}'
        if "vote" in system:
            n["i"] += 1
            return '{"vote": "%s", "confidence": 7, "reason": "x"}' % ("approve" if n["i"] % 4 in (1, 2) else "reject")  # har bahsda 2 approve, 2 reject
        return "xulosa"
    desk = Desk(db, llm, zone_min_approvals=2)
    base = {"symbol": "X", "direction": "LONG", "tier": "ZONE", "score": 5, "entry": 1, "sl": 0.9, "tp": 1.3, "rr": 2, "analysis": "{}"}
    zone = run(desk.review_signal({**base, "signal_id": "ZON-1", "strategy_id": "ZONE-DIR"}))
    assert zone.approve is True and "kerak ≥2" in zone.reason
    n["i"] = 0
    reg = run(desk.review_signal({**base, "signal_id": "SIG-1", "strategy_id": "TF-PULLBACK"}))
    assert reg.approve is False and "kerak ≥3" in reg.reason


def test_dir1_veto_still_blocks_even_with_relaxed_zone_threshold(tmp_path):
    db = __import__("agent.trading.db", fromlist=["TradingDB"]).TradingDB(tmp_path / "v.db")

    async def llm(system, prompt):
        if "decision" in system:
            return '{"decision": "reject", "reason": "shubha"}'
        if "vote" in system:
            return '{"vote": "approve", "confidence": 9, "reason": "x"}'
        return "x"
    r = run(Desk(db, llm, zone_min_approvals=2).review_signal({"signal_id": "ZON-2", "strategy_id": "ZONE-DIR", "symbol": "X", "direction": "LONG", "analysis": "{}"}))
    assert r.approve is False  # 4/4 approve bo'lsa ham DIR-1 rad etsa — zdelka yo'q


def test_daily_target_counts_tashkent_day_and_pressure_mode(tmp_path):
    from datetime import datetime, timedelta, timezone
    svc, sv, tg, tr, zt = _env(tmp_path)
    assert zt.opened_today() == 0 and zt.behind() and zt._limits() == (3, 2.0)  # orqada: faolroq (3 urinish, 2 soat kuldaun)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=2)).isoformat(timespec="seconds")
    for i in range(10):
        svc.db.execute("INSERT INTO demo_groups(signal_id, symbol, side, status, opened_at) VALUES(?,?,?,?,?)", (f"ZON-T{i}", "BTCUSDT", "buy", "CLOSED", now.isoformat(timespec="seconds")))
    svc.db.execute("INSERT INTO demo_groups(signal_id, symbol, side, status, opened_at) VALUES('ZON-OLD','BTCUSDT','buy','CLOSED',?)", (old,))
    svc.db.execute("INSERT INTO demo_groups(signal_id, symbol, side, status, opened_at) VALUES('SIG-X','BTCUSDT','buy','CLOSED',?)", (now.isoformat(timespec="seconds"),))
    assert zt.opened_today() == 10  # kechagi va oddiy (SIG-) signallar sanalmaydi
    assert not zt.behind() and zt._limits() == (1, 6.0)  # maqsadga yetildi — odatiy tartib


def test_unexecutable_plan_never_becomes_a_signal(tmp_path):
    """Ochib bo'lmaydigan zona (spred/minimal-lot riski) signal sifatida yuborilmaydi va bahsga tushmaydi."""
    svc, sv, tg, tr, zt = _env(tmp_path)
    z = dict(svc.db.one("SELECT * FROM zones WHERE id='z1'"))
    ok_spec = tr.symbol_spec
    s, why, _ = zt._setup(z)
    assert s is not None  # oddiy sharoitda reja o'tadi
    tr.symbol_spec = lambda name: {**ok_spec(name), "spread": 5.0}  # spred riskdan ancha katta (eksotik juftlik kabi)
    s, why, _ = zt._setup(z)
    assert s is None and "zdelka rejasi" in why and "spred" in why
    run(zt.on_pass())
    assert svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == 0  # yuborilmadi, bahs bo'lmadi
    assert svc.db.one("SELECT COUNT(*) n FROM staff_decisions")["n"] == 0
    tr.symbol_spec = ok_spec


def test_zone_signal_is_published_without_buttons_in_auto(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    run(zt.on_pass())
    assert tg.sent, "signal yuborilishi kerak"
    markups = [x['markup'] for x in tg.sent if x['markup']]
    assert not markups, "AUTO zona signalida HA/YO'Q tugmasi bo'lmasligi kerak"
    assert "tasdiq SHART EMAS" in tg.sent[0]["text"]


def test_debaters_get_zone_specific_brief_not_trend_checklist_only(tmp_path):
    db = __import__("agent.trading.db", fromlist=["TradingDB"]).TradingDB(tmp_path / "b.db")
    desk = Desk(db, None)
    zone = desk._signal_brief({"signal_id": "ZON-1", "strategy_id": "ZONE-DIR", "symbol": "X", "direction": "LONG", "analysis": "{}"})
    reg = desk._signal_brief({"signal_id": "SIG-1", "strategy_id": "TF-PULLBACK", "symbol": "X", "direction": "LONG", "analysis": "{}"})
    assert "ZONA SIGNALI" in zone and "RANGE rejimi" in zone and "ZONA SIGNALI" not in reg  # oddiy signalga ta'sir qilmaydi


def test_progress_report_goes_to_chat_once_per_hour(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path)
    run(zt._progress_report(["X: sabab"]))
    run(zt._progress_report(["X: sabab"]))
    rows = svc.db.query("SELECT text FROM staff_messages WHERE role='DIR-1' AND kind='report' AND text LIKE 'Kunlik maqsad%'")
    assert len(rows) == 1 and "0/10" in rows[0]["text"] and "o'zgarmaydi" in rows[0]["text"]


def test_shortlist_screens_all_candidates_not_just_the_strongest_twelve(tmp_path):
    """Oldin eng kuchli 12 ta har gal bir xil rad etilib, qolganiga navbat yetmasdi. Endi hammasi tarmoqsiz saralanadi."""
    svc, sv, tg, tr, zt = _env(tmp_path)
    svc.db.execute("DELETE FROM zones")
    syms = [f"S{i}m" for i in range(20)] + ["GOODm"]
    zt.scanner.universe["mt5"] = syms
    zt.scanner.mt5_group = {s: "Forex" for s in syms}

    def zone(zid, sym, kind, low, high, strength, status="active"):
        svc.db.execute("INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, status, dist_atr, price, atr, first_seen, last_seen) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (zid, sym, "mt5", "ZONE-1", kind, "1h", low, high, strength, status, 0, 100.0, 1.0, "t", "t"))
    for i in range(20):  # kuchli zonalar, lekin yaqinida KUCHLI qarshi zona bor -> R/R yetmaydi
        zone(f"a{i}", f"S{i}m", "support", 99.5, 100.2, 80 - i)
        zone(f"o{i}", f"S{i}m", "resistance", 100.6, 101.0, 40, status="fresh")  # to'siq, nomzod emas
    zone("g1", "GOODm", "support", 99.5, 100.2, 25)  # eng kuchsiz — ro'yxat oxirida
    zone("g2", "GOODm", "liq-high", 100.5, 100.6, 5, status="fresh")  # kichik likvidlik zonasi to'siq EMAS
    zt.cfg["trade_min_rr"] = 1.5  # _env soddalik uchun 0.5 qo'ygan; haqiqiy chegara
    cands = zt._candidates()
    assert len(cands) == 21
    short, skipped = zt._shortlist(cands, test=False)
    assert [z["symbol"] for z in short] == ["GOODm"]
    assert len(skipped) == 20 and all("R/R" in x for x in skipped)


def test_near_swing_obstacle_is_screened_before_debate():
    from types import SimpleNamespace
    from agent.zones.trade import Setup, ZoneTrader

    class F:
        def __init__(self, highs, lows):
            self.h, self.l = highs, lows

        def __len__(self):
            return 100

        def swings(self, i, lookback=200):
            return self.h, self.l
    mk = lambda d, e, sl: Setup("X", {}, d, e, sl, 0, 2.0, 2.0, 1.0, "", None, "", 0.0, 0.0)  # noqa: E731
    long = mk("LONG", 100.0, 99.0)  # risk = 1.0
    assert "yaqin qarshilik" in ZoneTrader._near_obstacle(long, F([(1, 100.2)], []))  # 0.2R — to'silgan
    assert ZoneTrader._near_obstacle(long, F([(1, 101.5)], [])) is None  # 1.5R — yo'l ochiq
    assert ZoneTrader._near_obstacle(long, F([], [])) is None
    short = mk("SHORT", 100.0, 101.0)
    assert "yaqin support" in ZoneTrader._near_obstacle(short, F([], [(1, 99.7)]))
    assert ZoneTrader._near_obstacle(short, F([], [(1, 98.0)])) is None
    assert SimpleNamespace  # (import tekshiruvi)


def test_force_test_skips_debate_cooldown_and_obstacle_but_keeps_execution_guards(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path, approve=False)  # bahs HAMMASINI rad etardi
    run(zt.on_pass(manual=True))
    assert not tr.opens  # oddiy rejim: bahs rad etdi
    # kuldaun endi band; majburiy rejim uni va bahsni o'tkazib yuboradi
    assert zt._cooldown("BTCUSDT")
    zt._near_obstacle = lambda s, f1: "yaqin qarshilik — to'silgan"
    run(zt.on_pass(manual=True, test=True, force=True))
    assert tr.opens and all(o["sl"] for o in tr.opens)  # zdelka ochildi, SL bor
    msgs = [r["text"] for r in svc.db.query("SELECT text FROM staff_messages WHERE kind='assign'")]
    assert any("MAJBURIY SINOV" in t for t in msgs)  # ochiq yozilgan


def test_force_never_bypasses_plan_guards(tmp_path):
    svc, sv, tg, tr, zt = _env(tmp_path, approve=False)
    ok_spec = tr.symbol_spec
    tr.symbol_spec = lambda name: {**ok_spec(name), "spread": 50.0}  # spred riskdan ancha katta
    run(zt.on_pass(manual=True, test=True, force=True))
    assert not tr.opens and svc.db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR'")["n"] == 0  # himoya bahsdan qat'i nazar ishlaydi
    tr.symbol_spec = ok_spec
