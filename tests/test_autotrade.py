"""V28 AUTO rejim: 1% riskdan lot, zdelkani 2 ga bo'lish (A: yaqin TP, B: to'liq TP), himoyalar, boshqaruv (vaqt chegarasi),
aylanma o'chirgich, AUTO tasdiq va /trading_mode|stop|flat buyruqlari. Soxta MT5 va Telegram bilan (haqiqiy buyurtma YO'Q)."""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_signals import GROUP, NOW, OWNER, cand, make_signal_service, row, run, sent_signal

from agent.trading import autotrade as at

SPEC = {"tick_value": 0.01, "tick_size": 0.01, "volume_min": 0.01, "volume_step": 0.01, "volume_max": 5.0, "digits": 2}


def plan(**kw):
    base = dict(side="buy", price=100.0, sl=95.0, tp=110.0, atr=2.0, balance=100.0, spec=SPEC, risk_pct=1.0, max_lot=1.0)
    base.update(kw)
    return at.plan_group(**base)


# ------------------------------------------------------------------------------------------------ sof hisob
def test_plan_sizes_lot_from_risk_and_splits_in_two():
    p = plan()
    assert p.lot_total == pytest.approx(0.2) and p.risk_money == 1.0 and p.risk_actual == pytest.approx(1.0)
    a, b = p.legs
    assert (a.tag, a.lot, a.tp) == ("A", 0.1, 105.0) and (b.tag, b.lot, b.tp) == ("B", 0.1, 110.0)  # A: 1R, B: to'liq TP
    assert p.sl == 95.0 and not p.sl_adjusted and a.lot + b.lot == pytest.approx(p.lot_total)


def test_plan_sell_is_symmetric():
    p = plan(side="sell", sl=105.0, tp=90.0)
    assert [(leg.tag, leg.lot, leg.tp) for leg in p.legs] == [("A", 0.1, 95.0), ("B", 0.1, 90.0)]


def test_plan_widens_sl_to_min_atr_and_keeps_risk():
    p = plan(atr=10.0, tp=125.0)  # SL 5 < 1 ATR(10) -> 10
    assert p.sl == 90.0 and p.sl_adjusted and p.dist == 10.0
    assert p.lot_total == pytest.approx(0.1) and [leg.lot for leg in p.legs] == [0.05, 0.05]
    assert any("uzaytirildi" in n for n in p.notes)


@pytest.mark.parametrize("kw,msg", [
    (dict(atr=10.0), "R/R past"),  # SL uzaytirilgach R/R 1:1
    (dict(spread=1.0), "spred"),
    (dict(balance=0.5), "minimumi"),
    (dict(sl=101.0), "noto'g'ri tomonida"),
    (dict(tp=99.0), "noto'g'ri tomonida"),
    (dict(balance=0), "balans"),
    (dict(spec={**SPEC, "tick_value": 0}), "tick qiymati")])
def test_plan_refusals(kw, msg):
    with pytest.raises(at.PlanRefused, match=msg):
        plan(**kw)


def test_plan_lot_cap_reports_smaller_real_risk_and_single_leg_cases():
    p = plan(balance=10000.0, max_lot=0.1)
    assert p.lot_total == 0.1 and p.risk_actual < p.risk_money and any("max_lot" in n for n in p.notes)
    one = plan(balance=10.0, tp=106.0, min_rr=1.0)  # TP yaqin (1.2R): bo'linmaydi
    assert len(one.legs) == 1 and one.legs[0].tag == "S" and one.legs[0].tp == 106.0
    tiny = plan(balance=5.0)  # jami 0.01 lot: yarmi minimumdan kam
    assert len(tiny.legs) == 1 and tiny.lot_total == 0.01 and any("bo'linmaydi" in n for n in tiny.notes)


def test_min_lot_fallback_uses_min_lot_single_leg_with_risk_cap():
    p = plan(balance=1.0, min_lot_fallback=True)  # 1% = 0.01 -> lot 0.001 < min; min lot riski 5%
    assert p.lot_total == 0.01 and [leg.tag for leg in p.legs] == ["S"] and p.legs[0].tp == 110.0
    assert p.risk_actual == pytest.approx(0.05) and any("minimal lot" in n and "5.0%" in n for n in p.notes)
    with pytest.raises(at.PlanRefused, match="chegara"):  # risk 10% > 8%
        plan(balance=0.5, min_lot_fallback=True)
    assert plan(balance=0.5, min_lot_fallback=True, min_lot_max_risk_pct=12.0).lot_total == 0.01
    with pytest.raises(at.PlanRefused, match="minimumi"):  # fallback o'chiq bo'lsa — avvalgidek rad
        plan(balance=1.0)


def test_breaker_helpers():
    assert at.consecutive_losses([-1, -2, 3, -1]) == 2 and at.consecutive_losses([5, -1]) == 0 and at.consecutive_losses([]) == 0
    assert at.drawdown_pct([10, -4, -3, 5], 100) == pytest.approx(7.0)
    assert at.drawdown_pct([5, 5], 100) == 0.0 and at.drawdown_pct([-5], 0) == 0.0


# ------------------------------------------------------------------------------------------------ servis
class GTrader:
    max_lot = 1.0

    def __init__(self, balance=100.0, spread=0.2, fail_second=False, positions=()):
        self.opens, self.closed, self.pos = [], [], list(positions)
        self.spread, self.fail_second, self.n = spread, fail_second, 0
        self.c = SimpleNamespace(resolve=lambda n: n + "m")

    def positions(self):
        return list(self.pos)

    def symbol_spec(self, name):
        return {**SPEC, "symbol": name, "ask": self.last + self.spread / 2, "bid": self.last - self.spread / 2, "spread": self.spread}

    def open(self, symbol, side, lot, sl, tp=None, dry_run=False, comment=None):
        from agent.trading.mt5_trade import TradeRefused
        if self.fail_second and self.opens:
            raise TradeRefused("ikkinchi buyurtma rad etildi")
        self.n += 1
        self.opens.append({"symbol": symbol, "side": side, "lot": lot, "sl": sl, "tp": tp, "comment": comment})
        ticket = 9000 + self.n
        self.pos.append({"ticket": ticket, "symbol": symbol + "m", "side": side, "lot": lot})
        return {"ok": True, "stage": "order_send", "retcode": 10009, "order": ticket, "price": self.last}

    def close(self, ticket):
        self.closed.append(ticket)
        self.pos = [p for p in self.pos if p["ticket"] != ticket]
        return {"ok": True}


class GHistory:
    def __init__(self, trader, balance=100.0, loss=0.0):
        self.t, self.bal, self.loss = trader, balance, loss

    def balance(self):
        return self.bal

    def open_positions(self):
        return [{**p, "ticket": p["ticket"], "profit": 0.0, "swap": 0.0, "magic": 20260711, "time": NOW} for p in self.t.pos]

    def deals_between(self, a, b):
        from agent.trading.mt5_history import Deal
        return [Deal(1, 0, 9, NOW, "BUY", "OUT", "SL", 4, "BTCUSDm", 0.01, 1.0, 0.0, 0.0, -self.loss, 0.0, 1, "")] if self.loss else []


def auto_service(tmp_path, trader=None, history=None, **cfg):
    svc, sv, tg = make_signal_service(tmp_path)
    trader = trader or GTrader()
    trader.last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
    sv.trader, sv.history = trader, history if history is not None else GHistory(trader)
    svc.settings.data["signals"].update({"demo_orders": True, "sizing": "risk", "split": True, "risk_pct": 1.0, "max_groups": 1,
                                         "tp1_r": 1.0, "time_stop_h": 48, "trade_mode": "confirm", "min_sl_atr": 1.0, **cfg})
    svc.settings.data["private_chat_id"] = OWNER
    return svc, sv, tg, trader


async def confirm(svc, sv, **kw):
    sid = await sent_signal(svc, sv, **kw)
    ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
    return sid, ans


def test_ha_opens_two_position_group_with_risk_lot_and_split_tp(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid, ans = await confirm(svc, sv)
        assert "MT5 DEMO zdelka ochildi" in ans
        r = row(svc, sid)
        assert len(tr.opens) == 2 and [o["comment"] for o in tr.opens] == [f"{sid}A", f"{sid}B"]
        a, b = tr.opens
        assert abs(a["lot"] - b["lot"]) <= 0.011 and a["lot"] >= 0.01 and a["sl"] == b["sl"] == r["sl"] and a["side"] == "buy"
        assert a["lot"] + b["lot"] == pytest.approx(0.19, abs=0.011)  # jami lot 1% riskdan (qoldiq B ga)
        risk = abs(tr.last + 0.1 - r["sl"])  # narx = ask
        assert a["tp"] == pytest.approx(round(tr.last + 0.1 + risk, 2), abs=0.02) and b["tp"] == pytest.approx(r["tp"], abs=0.01)
        g = svc.db.one("SELECT * FROM demo_groups WHERE signal_id=?", (sid,))
        assert g["status"] == "OPEN" and len(json.loads(g["tickets"])) == 2 and g["mode"] == "confirm"
        text = tg.edits[-1][2]
        assert "MT5 DEMO guruh ochildi" in text and "A:" in text and "B:" in text and "risk" in text
    run(go())


def test_group_guards_limit_duplicates_correlation_balance_loss(tmp_path):
    async def go():
        # 1) guruhlar chegarasi
        svc, sv, tg, tr = auto_service(tmp_path / "a")
        await confirm(svc, sv)
        sid2 = await sent_signal(svc, sv, direction="SHORT")
        ans = await sv.handle_callback(f"sentinel:confirm:{sid2}", OWNER, GROUP)
        assert "guruhlari chegarasi" in ans and len(tr.opens) == 2
        # 2) shu simvol va yo'nalishda pozitsiya allaqachon bor
        svc, sv, tg, tr = auto_service(tmp_path / "b", GTrader(positions=[{"ticket": 1, "symbol": "BTCUSDm", "side": "buy"}]))
        assert "allaqachon ochiq" in (await confirm(svc, sv))[1] and tr.opens == []
        # 3) korrelyatsiya: ETH long (ikki yarim) + BTC long -> samarali risk > 1.75%
        svc, sv, tg, tr = auto_service(tmp_path / "c", GTrader(positions=[
            {"ticket": 1, "symbol": "ETHUSDm", "side": "buy"}, {"ticket": 2, "symbol": "ETHUSDm", "side": "buy"}]))
        assert "korrelyatsiya himoyasi" in (await confirm(svc, sv))[1] and tr.opens == []
        # 4) balans/tarix ulanmagan -> lot hisoblanmaydi, zdelka ochilmaydi
        svc, sv, tg, tr = auto_service(tmp_path / "d")
        sv.history = None
        assert "balans o'qilmadi" in (await confirm(svc, sv))[1] and tr.opens == []
        # 5) kunlik zarar chegarasi
        svc, sv, tg, tr = auto_service(tmp_path / "e")
        sv.history = GHistory(tr, balance=10000.0, loss=600.0)
        assert "kunlik zarar chegarasi" in (await confirm(svc, sv))[1] and tr.opens == []
        # 6) spred riskka nisbatan katta
        svc, sv, tg, tr = auto_service(tmp_path / "f", GTrader(spread=2.0))
        assert "spred" in (await confirm(svc, sv))[1] and tr.opens == []
    run(go())


def test_second_leg_failure_keeps_first_and_reports_partial(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, GTrader(fail_second=True))

    async def go():
        sid, ans = await confirm(svc, sv)
        assert "MT5 DEMO zdelka ochildi" in ans and len(tr.opens) == 1
        g = svc.db.one("SELECT * FROM demo_groups WHERE signal_id=?", (sid,))
        assert len(json.loads(g["tickets"])) == 1
        assert "to'liq ochilmadi" in tg.edits[-1][2] and "B: OCHILMADI" in tg.edits[-1][2]
    run(go())


def test_time_stop_closes_remaining_positions_once_and_reconcile_marks_closed(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid, _ = await confirm(svc, sv)
        assert await sv.manage(NOW + timedelta(hours=10)) == []  # hali muddat o'tmagan
        svc.clock.now = NOW + timedelta(hours=49)
        acts = await sv.manage(svc.clock())
        assert acts == [f"time_stop:{sid}"] and sorted(tr.closed) == [9001, 9002]
        g = svc.db.one("SELECT * FROM demo_groups WHERE signal_id=?", (sid,))
        assert g["status"] == "CLOSED" and "vaqt chegarasi" in g["note"]
        assert any("vaqt chegarasi" in m["text"] and m["reply_to"] for m in tg.sent)
        assert await sv.manage(svc.clock()) == [] and sorted(tr.closed) == [9001, 9002]  # takror yopilmaydi
    run(go())


def test_group_marked_closed_when_positions_disappear_naturally(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)

    async def go():
        sid, _ = await confirm(svc, sv)
        tr.pos.clear()  # SL/TP bilan yopildi
        await sv.manage(NOW + timedelta(hours=1))
        assert svc.db.one("SELECT status FROM demo_groups")["status"] == "CLOSED" and tr.closed == []
        # keyingi signal uchun joy bor
        sid2 = await sent_signal(svc, sv, direction="SHORT")
        assert "MT5 DEMO zdelka ochildi" in await sv.handle_callback(f"sentinel:confirm:{sid2}", OWNER, GROUP)
    run(go())


def closed_group(svc, sid, net, minutes, tickets):
    now = NOW + timedelta(minutes=minutes)
    svc.db.execute("INSERT INTO demo_groups(signal_id, symbol, side, tickets, legs, sl, status, opened_at, closed_at) "
                   "VALUES(?,?,?,?,?,?,'CLOSED',?,?)", (sid, "BTCUSDm", "buy", json.dumps(tickets), "[]", 1.0, now.isoformat(), now.isoformat()))
    for t in tickets:
        svc.db.execute("INSERT INTO live_trades(position_id, strategy, symbol, direction, opened_at, closed_at, net, reason, source) "
                       "VALUES(?,?,?,?,?,?,?,?,?)", (t, "S", "BTCUSDm", "BUY", now.isoformat(), now.isoformat(), net / len(tickets), "SL", "SENTINAL"))


def test_circuit_breaker_stops_auto_after_consecutive_group_losses(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto")

    async def go():
        sv.set_trade_mode("auto")
        for k in range(3):
            closed_group(svc, f"G{k}", -2.0, k, [100 + 2 * k, 101 + 2 * k])
        assert "breaker" in await sv.manage(NOW + timedelta(hours=1))
        assert sv.trade_mode == "confirm" and svc.settings.data["signals"]["trade_mode"] == "confirm"
        msgs = [m for m in tg.sent if m["chat"] == OWNER and "AUTO O'CHIRILDI" in m["text"]]
        assert len(msgs) == 1 and "ketma-ket 3" in msgs[0]["text"]
        assert await sv.manage(NOW + timedelta(hours=2)) == []  # o'chgan rejimda takror ishlamaydi
    run(go())


def test_breaker_not_tripped_by_win_in_between_or_unfinished_groups_and_drawdown_trips(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto", breaker_losses=3)

    async def go():
        sv.set_trade_mode("auto")
        closed_group(svc, "G0", -2.0, 0, [1, 2])
        closed_group(svc, "G1", +3.0, 1, [3, 4])
        closed_group(svc, "G2", -2.0, 2, [5, 6])
        closed_group(svc, "G3", -2.0, 3, [7, 8])
        svc.db.execute("INSERT INTO demo_groups(signal_id, symbol, side, tickets, legs, sl, status, opened_at, closed_at) VALUES"
                       "('G4','BTCUSDm','buy','[11,12]','[]',1.0,'CLOSED',?,?)", (NOW.isoformat(), NOW.isoformat()))  # live_trades yo'q
        assert "breaker" not in await sv.manage(NOW + timedelta(hours=1)) and sv.trade_mode == "auto"
        # cho'qqidan pasayish: boshlang'ich balans ~100 (balans 100 - jami natija)
        closed_group(svc, "G5", -12.0, 4, [21, 22])
        svc.settings.data["signals"]["breaker_losses"] = 99
        assert "breaker" in await sv.manage(NOW + timedelta(hours=2)) and "pasayish" in svc.db.one(
            "SELECT detail FROM signal_events WHERE kind='breaker'")["detail"]
    run(go())


def test_auto_mode_confirms_strong_and_confirm_signals_without_button(tmp_path, monkeypatch):
    svc, sv, tg, tr = auto_service(tmp_path, trade_mode="auto")

    async def go():
        sv.set_trade_mode("auto")
        monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier="CONFIRM", score=7))
        r = await sv.scan_once()
        assert r["sent"] == 1 and r["auto"] == 1 and len(tr.opens) == 2
        r0 = svc.db.one("SELECT * FROM signals WHERE status='CONFIRMED'")
        assert r0["decided_by"] == 0 and "AUTO" in tg.edits[-1][2] and "MT5 DEMO zdelka" in tg.edits[-1][2]
        assert svc.db.one("SELECT mode FROM demo_groups")["mode"] == "auto"
    run(go())


def test_auto_mode_off_or_weak_tier_or_demo_disabled_never_auto_confirms(tmp_path, monkeypatch):
    async def scenario(tmp, mode, tier, demo=True):
        svc, sv, tg, tr = auto_service(tmp, trade_mode=mode, demo_orders=demo)
        monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier=tier, score=7 if tier == "CONFIRM" else 4))
        await sv.scan_once()
        return tr.opens
    assert run(scenario(tmp_path / "a", "confirm", "CONFIRM")) == []  # CONFIRMATION: faqat tugma
    assert run(scenario(tmp_path / "b", "auto", "WATCH")) == []  # zaif daraja
    assert run(scenario(tmp_path / "c", "auto", "CONFIRM", demo=False)) == []  # demo yoqilmagan
    svc, sv, tg, tr = auto_service(tmp_path / "d", trade_mode="auto", auto_min_tier="STRONG")
    monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier="CONFIRM", score=7))
    run(sv.scan_once())
    assert tr.opens == []  # auto_min_tier=STRONG: CONFIRM yetmaydi


def test_legacy_fixed_lot_path_unchanged_when_sizing_is_fixed(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, sizing="fixed", demo_lot=0.01)

    async def go():
        sid, ans = await confirm(svc, sv)
        assert "MT5 DEMO zdelka ochildi" in ans and len(tr.opens) == 1 and tr.opens[0]["lot"] == 0.01
        assert svc.db.one("SELECT COUNT(*) n FROM demo_groups")["n"] == 0
    run(go())


# ------------------------------------------------------------------------------------------------ buyruqlar
def make_bot(svc, sv, approve=True):
    from agent.bot import TelegramBot
    sent = []

    class Journal:
        def event(self, *a, **k):
            pass

    async def send_text(t, *a, **k):
        sent.append(t)

    async def request_approval(task, text):
        sent.append("TASDIQ: " + text)
        return approve
    bot = TelegramBot.__new__(TelegramBot)
    bot.trading, bot.signals, bot.journal, bot.send_text, bot.request_approval = svc, sv, Journal(), send_text, request_approval
    bot.trading_scheduler = None
    return bot, sent


def test_trading_mode_commands(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path)
    bot, sent = make_bot(svc, sv)
    cfg = svc.settings.data["signals"]

    async def go():
        await bot._trading_command("/trading_mode", "")
        assert "AUTO" not in cfg["trade_mode"].upper() and "analysis" in sent[-1]
        await bot._trading_command("/trading_mode", "auto")
        assert cfg["trade_mode"] == "auto" and cfg["mode"] == "live" and cfg["auto_since"] and "AUTO yoqildi" in sent[-1]
        await bot._trading_command("/trading_stop", "")
        assert cfg["trade_mode"] == "confirm" and "AUTO to'xtatildi" in sent[-1]
        await bot._trading_command("/trading_mode", "analysis")
        assert cfg["mode"] == "dry" and cfg["trade_mode"] == "confirm"
        cfg["sizing"] = "fixed"
        await bot._trading_command("/trading_mode", "auto")
        assert cfg["trade_mode"] == "confirm" and "AUTO yoqilmadi" in sent[-1]  # sizing=risk kerak
    run(go())


def test_trading_flat_closes_only_after_approval(tmp_path):
    svc, sv, tg, tr = auto_service(tmp_path, GTrader(positions=[{"ticket": 7, "symbol": "BTCUSDm", "side": "buy"},
                                                               {"ticket": 8, "symbol": "ETHUSDm", "side": "sell"}]))
    bot, sent = make_bot(svc, sv, approve=False)

    async def go():
        await bot._trading_command("/trading_flat", "")
        assert tr.closed == [] and "TASDIQ" in sent[-1]  # rad etilsa hech narsa yopilmaydi
        bot2, sent2 = make_bot(svc, sv, approve=True)
        await bot2._trading_command("/trading_flat", "")
        assert sorted(tr.closed) == [7, 8] and "#7 BTCUSDm: yopildi" in sent2[-1]
    run(go())


# ------------------------------------------------------------------------------------------------ DemoTrader: izoh va spetsifikatsiya
def test_demotrader_comment_and_symbol_spec():
    from types import SimpleNamespace as NS

    from test_mt5_trade import TradeMT5, trader

    class SpecMT5(TradeMT5):
        def symbol_info(self, name):
            base = super().symbol_info(name)
            if base is None:
                return None
            return NS(**vars(base), trade_tick_value=0.01, trade_tick_size=0.01, volume_max=5.0, digits=2)
    f = SpecMT5()
    t = trader(f)
    spec = t.symbol_spec("EURUSD")
    assert spec["symbol"] == "EURUSD" and spec["tick_value"] == 0.01 and spec["volume_max"] == 5.0 and spec["spread"] == pytest.approx(0.0002)
    assert t.open("EURUSD", "buy", 0.01, sl=1.09, comment="SIG-20261108-0001A-uzun-izoh-uzun-izoh-uzun")["ok"]
    assert f.sent[0]["comment"] == "SIG-20261108-0001A-uzun-izoh-uz"[:31] and len(f.sent[0]["comment"]) == 31
    assert t.open("EURUSD", "buy", 0.01, sl=1.09)["ok"] and f.sent[1]["comment"] == "SENTINAL-demo"
