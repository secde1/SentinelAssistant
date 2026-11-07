"""V24 MT5 pozitsiya monitoringi: ochilish/o'zgarish/yopilish aniqlash (SL, TP, qo'lda), tarix tasdig'i, xabar navbati
(qayta yuborish, dublikat yo'q), uzilish ogohlantirishi, savdo tahlili. Soxta MT5 tarixi va soxta Telegram bilan."""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_trading import candles_from, make_service

from agent.telegram_api import TelegramError, TelegramNetworkError
from agent.trading import mt5_history as mh
from agent.trading import mt5_monitor as mm
from agent.trading.data import Candle, DataUnavailable

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
OPEN_T = datetime(2026, 11, 7, 16, 4, 4, tzinfo=timezone.utc)
CLOSE_T = datetime(2026, 11, 7, 17, 37, 5, tzinfo=timezone.utc)
GROUP, OWNER = -5588340884, 871134228
MAGIC = 20260711


def deal(ticket, pid, t, typ, entry, reason, vol, price, profit=0.0, comm=0.0, swap=0.0, magic=MAGIC, symbol="BTCUSDm",
         order=None, comment=""):
    return mh.Deal(ticket, pid if order is None else order, pid, t, typ, entry, mh.DEAL_REASONS[reason], reason, symbol, vol,
                   price, comm, swap, profit, 0.0, magic, comment)


def sl_deals(pid=2720676738, entry=75683.12, exit_=75740.66, profit=-1.73, reason=4):
    return [deal(2504749323, pid, OPEN_T, "SELL", "IN", 3, 0.03, entry),
            deal(2504827938, pid, CLOSE_T, "BUY", "OUT", reason, 0.03, exit_, profit=profit, order=0,
                 comment="[sl 75740.00000]" if reason == 4 else "")]


def pos(pid=2720676738, sl=75740.0, tp=75430.0, side="SELL", price=75683.12, t=OPEN_T, magic=MAGIC, symbol="BTCUSDm", vol=0.03):
    return {"ticket": pid, "symbol": symbol, "side": side, "volume": vol, "price_open": price, "sl": sl, "tp": tp,
            "profit": 0.0, "swap": 0.0, "magic": magic, "time": t}


class FakeHistory:
    def __init__(self):
        self.open: list[dict] = []
        self.deals: dict[int, list] = {}
        self.fail: DataUnavailable | None = None
        self.orders = {}

    def open_positions(self):
        if self.fail:
            raise self.fail
        return list(self.open)

    def deals_of_position(self, pid):
        if self.fail:
            raise self.fail
        return list(self.deals.get(pid, []))

    def deals_between(self, a, b):
        if self.fail:
            raise self.fail
        return sorted((d for ds in self.deals.values() for d in ds if a <= d.time <= b), key=lambda d: d.time)

    def orders_of_position(self, pid):
        return self.orders.get(pid, [])


class Tg:
    def __init__(self):
        self.sent, self.errors = [], []

    async def send(self, chat, text):
        if self.errors:
            raise self.errors.pop(0)
        self.sent.append((chat, text))
        return {"message_id": len(self.sent)}


def synth_candles(sym, tf, limit, end):
    """Sintetik, ochilishgacha pasayish trendi (4H/1H/15M) va 1m yo'l: pastga, keyin SL ga qaytish."""
    sec = {"4h": 14400, "1h": 3600, "15m": 900, "1m": 60}[tf]
    if tf == "1m":
        n = int((end - OPEN_T).total_seconds() // 60) + 10
        out = []
        for k in range(n):
            ts = OPEN_T - timedelta(minutes=5) + timedelta(minutes=k)
            p = 75683.0 - min(k, 25) * 3.7 + max(0, k - 80) * 5.2  # 25 daqiqada -92.5 gacha, keyin SL ga qaytadi
            out.append(Candle(ts, p, p + 4, p - 4, p, 1.0, 60))
        return out
    closes = [90000 - 30 * k for k in range(320)]
    return candles_from(closes, sec=sec, start=end - timedelta(seconds=sec * 320), pad=60.0)


def make(tmp_path, group=GROUP, **kw):
    svc = make_service(tmp_path / "h", {}, NOW)
    svc.settings.data["group_chat_id"] = group
    h, tg = FakeHistory(), Tg()
    clock = SimpleNamespace(now=NOW)
    svc.settings.data["private_chat_id"] = OWNER  # shaxsiy chat guruhdan ALOHIDA saqlanadi
    q = mm.NotificationQueue(svc.db, tg.send, mm.private_chat_resolver(svc.settings, OWNER), lambda: clock.now)
    mon = mm.PositionMonitor(svc, h, q, synth_candles, currency_fn=lambda: "USD", contract_fn=lambda s: 1.0,
                             analysis_path=tmp_path / "trading" / "post_trade_analysis.json", **kw)
    return svc, h, tg, q, mon, clock


def run(c):
    return asyncio.run(c)


def texts(tg):
    return [t for _, t in tg.sent]


# ------------------------------------------------------------------------------------------------ ochilish / o'zgarish
def test_new_position_is_announced_once_and_modification_detected(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    h.open = [pos()]
    r = mon.poll_once(NOW)
    assert r.opened == 1 and mon.poll_once(NOW).opened == 0
    run(q.flush())
    assert len(tg.sent) == 1 and tg.sent[0][0] == OWNER
    t = texts(tg)[0]
    assert "POSITION OPENED" in t and "BTCUSDm" in t and "SELL" in t and "75 740" in t and "STATUS: OPEN" in t
    h.open = [pos(sl=75800.0)]
    assert mon.poll_once(NOW).modified == 1 and mon.poll_once(NOW).modified == 0
    run(q.flush())
    assert "POSITION MODIFIED" in texts(tg)[1] and "75 740 → 75 800" in texts(tg)[1]
    assert len(tg.sent) == 2


def test_position_without_sl_is_flagged(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos(sl=0.0)]
    mon.poll_once(NOW)
    run(q.flush())
    assert "Stop Loss yo'q" in texts(tg)[0]


def test_preexisting_position_gets_monitoring_note(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos(t=NOW - timedelta(hours=8))]
    mon.poll_once(NOW)
    run(q.flush())
    assert "allaqachon ochiq edi" in texts(tg)[0]


# ------------------------------------------------------------------------------------------------ yopilish
def test_sl_close_is_reported_only_after_history_confirms(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    h.open = [pos()]
    mon.poll_once(NOW)
    run(q.flush())
    h.open = []  # pozitsiya ro'yxatdan yo'qoldi, lekin tarixda hali OUT bitimi yo'q
    h.deals[2720676738] = [sl_deals()[0]]
    r = mon.poll_once(NOW)
    assert r.closed == 0 and r.pending_close == 1
    run(q.flush())
    assert len(tg.sent) == 1  # yopilish xabari YO'Q (tasdiqlanmagan)
    h.deals[2720676738] = sl_deals()  # tarixda paydo bo'ldi
    r = mon.poll_once(NOW)
    assert r.closed == 1
    run(q.flush())
    t = texts(tg)[1]
    for need in ("🔴 SENTINEL | STOP LOSS HIT", "Symbol: BTCUSDm", "Direction: SELL", "Volume: 0.03", "Entry: 75 683.12",
                 "SL: 75 740", "TP: 75 430", "Exit: 75 740.66", "Result: -1.73 USD", "Commission: +0.00 USD", "Swap: +0.00 USD",
                 "Reason: STOP LOSS", "Duration: 1 soat 33 daqiqa", "STATUS: CLOSED", "⚠️ Analysis:", "#2720676738"):
        assert need in t, need
    assert mon.poll_once(NOW).closed == 0  # takroran xabar yo'q
    run(q.flush())
    assert len(tg.sent) == 3  # opened + closed + POST-TRADE REPORT; takror yo'q


def test_close_reasons_titles(tmp_path):
    cases = [(5, "🟢 SENTINEL | TAKE PROFIT HIT", "TAKE PROFIT"), (0, "MANUAL CLOSE", "MANUAL (terminal)"),
             (1, "MANUAL CLOSE", "MANUAL (mobil)"), (3, "CLOSED BY EXPERT/BOT", "EXPERT/BOT"),
             (6, "STOP OUT", "STOP OUT")]
    for k, (code, title, why) in enumerate(cases):
        svc, h, tg, q, mon, _ = make(tmp_path / str(k))
        pid = 2720000000 + k
        h.open = [pos(pid=pid)]
        mon.poll_once(NOW)
        h.open = []
        h.deals[pid] = sl_deals(pid=pid, reason=code, exit_=75430.0 if code == 5 else 75700.0,
                                profit=7.59 if code == 5 else -1.0)
        assert mon.poll_once(NOW).closed == 1
        run(q.flush())
        t = [x for x in texts(tg) if "CLOSED" in x][0]
        assert title in t and why in t, (code, t)


def test_partial_close_is_not_reported_as_closed(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos()]
    mon.poll_once(NOW)
    h.open = []
    d = sl_deals()
    d[1].volume = 0.01  # faqat 0.01 yopilgan
    h.deals[2720676738] = d
    assert mon.poll_once(NOW).closed == 0
    run(q.flush())
    assert not [x for x in texts(tg) if "STATUS: CLOSED" in x]


def test_position_still_open_is_never_reported_closed(tmp_path):
    """ETH holati: pozitsiya ochiq, tarixda faqat IN bitimi — hech qachon 'SL' deb xabar yuborilmaydi."""
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos(pid=2720305695, side="SELL", price=2244.73, sl=2253.0, tp=2224.0, symbol="ETHUSDm", vol=0.1)]
    h.deals[2720305695] = [deal(2504430931, 2720305695, OPEN_T, "SELL", "IN", 3, 0.1, 2244.73, symbol="ETHUSDm")]
    for _ in range(3):
        mon.poll_once(NOW)
    run(q.flush())
    assert len(tg.sent) == 1 and "POSITION OPENED" in texts(tg)[0] and not any("HIT" in x for x in texts(tg))


def test_backfill_reports_position_closed_while_monitor_was_off(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.deals[2720676738] = sl_deals()  # hech qachon ko'rilmagan, yopilgan pozitsiya
    r = mon.poll_once(NOW)
    assert r.backfilled == 1
    run(q.flush())
    t = texts(tg)[0]
    assert "STOP LOSS HIT" in t and "Kechikkan xabar" in t and "Result: -1.73 USD" in t
    assert mon.poll_once(NOW).backfilled == 0
    run(q.flush())
    assert len(tg.sent) == 2 and "POST-TRADE REPORT" in texts(tg)[1]  # natija + hisobot, takror yo'q


def test_backfill_window_limits_old_history(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    old = [mh.Deal(d.ticket, d.order, d.position_id, d.time - timedelta(days=10), d.type, d.entry, d.reason, d.reason_code,
                   d.symbol, d.volume, d.price, d.commission, d.swap, d.profit, d.fee, d.magic, d.comment) for d in sl_deals()]
    h.deals[2720676738] = old
    assert mon.poll_once(NOW).backfilled == 0  # 48 soatdan eski


def test_position_that_opened_and_closed_between_polls_is_still_reported(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    mon.poll_once(NOW)  # birinchi poll: hech narsa
    h.deals[2720676738] = sl_deals()
    assert mon.poll_once(NOW).backfilled == 1
    run(q.flush())
    assert "STOP LOSS HIT" in texts(tg)[0]


# ------------------------------------------------------------------------------------------------ tahlil va statistika
def test_post_trade_analysis_file_stats_and_idempotency(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos()]
    mon.poll_once(NOW)
    h.open = []
    h.deals[2720676738] = sl_deals()
    mon.poll_once(NOW)
    data = json.loads((tmp_path / "trading" / "post_trade_analysis.json").read_text(encoding="utf-8"))
    assert data["version"] == 1 and len(data["trades"]) == 1
    a = data["trades"][0]
    assert a["position_id"] == 2720676738 and a["reason"] == "SL" and a["net"] == -1.73
    assert a["r_multiple"] == pytest.approx(-1.01, abs=0.02)  # (-1.73)/(56.88*0.03*1)
    assert a["sl_atr_1h"] < 0.5 and any("SL juda yaqin" in x for x in a["verdict"]["failed"])
    assert any("Gipoteza" in x for x in a["verdict"]["improve"])  # o'zgarish tavsiya emas, gipoteza
    assert a["mae_r"] is not None and a["mfe_r"] >= 1.0 and a["mfe_of_tp"] > 0
    assert "yetarli emas" in a["short"] and "bitta savdo asosida strategiya o'zgartirilmaydi" in a["sample"]["warning"]
    mon._save_analysis(a)  # takror yozish dublikat qilmaydi
    assert len(json.loads((tmp_path / "trading" / "post_trade_analysis.json").read_text(encoding="utf-8"))["trades"]) == 1
    st = mon.live_stats()
    assert st["n"] == 1 and st["wins"] == 0 and st["net"] == -1.73 and st["by_reason"] == {"SL": 1} and st["note"]


def test_analysis_never_blocks_the_notification(tmp_path):
    def broken(*a):
        raise DataUnavailable("MT5 yo'q")
    svc, h, tg, q, mon, _ = make(tmp_path)
    mon.candles_fn = broken
    h.open = [pos()]
    mon.poll_once(NOW)
    h.open = []
    h.deals[2720676738] = sl_deals()
    assert mon.poll_once(NOW).closed == 1
    run(q.flush())
    assert "STOP LOSS HIT" in texts(tg)[-1]
    a = json.loads((tmp_path / "trading" / "post_trade_analysis.json").read_text(encoding="utf-8"))["trades"][0]
    assert any("tiklanmadi" in n for n in a["notes"]) and a["net"] == -1.73


def test_analysis_uses_only_data_before_open_and_reports_failed_criteria():
    s = mh.summarize(sl_deals())
    seen = []

    def spy(sym, tf, limit, end):
        seen.append((tf, end))
        return synth_candles(sym, tf, limit, end)
    a = mm.analyze_trade(s, 75740.0, 75430.0, 1.0, spy, {"n": 1})
    assert all(end == OPEN_T for tf, end in seen if tf != "1m")  # kontekst faqat ochilishgacha
    assert a["context"]["h4_trend"] == "TREND_DOWN" and any("4H va 1H trendiga mos" in x for x in a["verdict"]["worked"])
    assert a["rr_planned"] == pytest.approx(4.45, abs=0.01) and any("R/R" in x for x in a["verdict"]["failed"])


# ------------------------------------------------------------------------------------------------ navbat
def test_queue_retries_after_telegram_error_and_delivers_exactly_once(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    q.enqueue("closed:1", "closed", "private", "hello")
    assert not q.enqueue("closed:1", "closed", "private", "hello again")  # bir kalit — bir xabar
    tg.errors = [TelegramError("Bad Gateway")]
    assert run(q.flush())["failed"] == 1 and not tg.sent
    assert run(q.flush())["sent"] == 0  # backoff: hali vaqti kelmadi
    clock.now = NOW + timedelta(seconds=31)
    assert run(q.flush())["sent"] == 1 and texts(tg) == ["hello"]
    clock.now = NOW + timedelta(hours=3)
    assert run(q.flush())["sent"] == 0 and len(tg.sent) == 1


def test_queue_survives_restart_and_sends_pending(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    q.enqueue("closed:7", "closed", "private", "saqlangan xabar")
    tg2 = Tg()
    q2 = mm.NotificationQueue(svc.db, tg2.send, lambda t: GROUP, lambda: clock.now)  # "qayta ishga tushgan" navbat
    assert run(q2.flush())["sent"] == 1 and texts(tg2) == ["saqlangan xabar"] and not tg.sent


def test_ambiguous_network_error_resends_with_marker_and_third_failure_alerts_owner(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    q.enqueue("closed:9", "closed", "private", "natija")
    tg.errors = [TelegramNetworkError("ReadError"), TelegramNetworkError("ReadError"), TelegramNetworkError("ReadError")]
    for k in range(3):
        clock.now = NOW + timedelta(hours=k * 2)
        run(q.flush())
    row = svc.db.one("SELECT * FROM notifications WHERE key='closed:9'")
    assert row["attempts"] == 3 and row["status"] == "PENDING" and row["ambiguous"] == 1
    alert = svc.db.one("SELECT * FROM notifications WHERE key='pv:sendfail:closed:9'")
    assert alert and alert["target"] == "private" and "telegram send failed" in alert["text"]
    clock.now = NOW + timedelta(hours=8)
    run(q.flush())
    delivered = texts(tg)
    assert any(t.startswith("↻ natija") for t in delivered) and any("telegram send failed" in t for t in delivered)
    assert sum(1 for t in delivered if t.endswith("natija")) == 1


def test_queue_gives_up_after_24h(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    q.enqueue("closed:4", "closed", "private", "y")
    tg.errors = [TelegramError("down")]
    clock.now = NOW + timedelta(hours=25)
    svc.db.execute("UPDATE notifications SET created_at=? WHERE key='closed:4'", ((NOW - timedelta(hours=1)).isoformat(),))
    run(q.flush())
    assert svc.db.one("SELECT status FROM notifications WHERE key='closed:4'")["status"] == "FAILED"


# ------------------------------------------------------------------------------------------------ uzilish va monitor to'xtashi
def test_connection_loss_alert_once_and_restore_notice(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.fail = DataUnavailable("IPC timeout")
    for _ in range(6):
        r = mon.poll_once(NOW)
    assert "IPC timeout" in r.error
    run(q.flush())
    alerts = [t for t in texts(tg) if "MT5 CONNECTION LOST" in t]
    assert len(alerts) == 1 and all(c == OWNER for c, t in tg.sent if "MT5 CONNECTION LOST" in t)
    h.fail = None
    mon.poll_once(NOW)
    run(q.flush())
    assert len([t for t in texts(tg) if "CONNECTION RESTORED" in t]) == 1


def test_unconfirmed_close_alert_after_30_minutes(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos()]
    mon.poll_once(NOW)
    h.open = []
    h.deals[2720676738] = [sl_deals()[0]]
    mon.poll_once(NOW + timedelta(minutes=45))
    run(q.flush())
    assert any("close not confirmed" in t for t in texts(tg)) and not any("STATUS: CLOSED" in t for t in texts(tg))


def test_downtime_alert_on_restart(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    mon.poll_once(NOW)
    svc.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('monitor_last_ok', ?)", ((NOW - timedelta(hours=3)).isoformat(),))
    mon.downtime_alert(NOW)
    mon.downtime_alert(NOW)  # takror yuborilmaydi
    run(q.flush())
    assert len([t for t in texts(tg) if "monitor was down" in t]) == 1


def test_scheduler_runs_monitor_and_flushes_queue(tmp_path):
    from agent.trading.publish import Publisher
    from agent.trading.scheduler import TradingScheduler
    svc, h, tg, q, mon, clock = make(tmp_path)
    h.open = [pos()]

    async def notify(text):
        pass
    sch = TradingScheduler(svc, Publisher(svc.db, svc.settings, lambda *a: None, clock=svc.clock), notify)
    sch.monitor = mon
    run(sch._monitor(NOW))
    assert len(tg.sent) == 1 and "POSITION OPENED" in texts(tg)[0]
    run(sch._monitor(NOW + timedelta(seconds=30)))  # poll oralig'i o'tmagan: qayta so'ralmaydi, takror xabar yo'q
    assert len(tg.sent) == 1


# ------------------------------------------------------------------------------------------------ MT5 tarixi (o'qish)
def test_history_reader_converts_times_and_maps_reasons():
    from test_mt5 import NOW as T_NOW
    from test_mt5 import OFFSET, RUNNING, FakeMT5

    from agent.trading import mt5_connector as m

    class HistMT5(FakeMT5):
        def history_deals_get(self, *a, **kw):
            t_in = int(T_NOW.timestamp()) + OFFSET - 5600
            t_out = int(T_NOW.timestamp()) + OFFSET
            d = lambda **k: SimpleNamespace(**k)  # noqa: E731
            return [d(ticket=1, order=77, position_id=77, time=t_in, time_msc=t_in * 1000, type=1, entry=0, magic=MAGIC,
                      reason=3, volume=0.03, price=75683.12, commission=0.0, swap=0.0, profit=0.0, fee=0.0, symbol="BTCUSD",
                      comment="x"),
                    d(ticket=2, order=0, position_id=77, time=t_out, time_msc=t_out * 1000 + 826, type=0, entry=1, magic=MAGIC,
                      reason=4, volume=0.03, price=75740.66, commission=-0.1, swap=-0.2, profit=-1.73, fee=0.0,
                      symbol="BTCUSD", comment="[sl 75740.00000]")]
    fake = HistMT5()
    c = m.MT5Connector(module=fake, terminals=RUNNING, clock=lambda: T_NOW, sleep=lambda s: None)
    deals = mh.MT5History(c).deals_of_position(77)
    s = mh.summarize(deals)
    assert deals[0].time == T_NOW - timedelta(seconds=5600) and deals[1].reason == "SL"  # server vaqti UTC ga o'girilgan
    assert s["reason"] == "SL" and s["net"] == pytest.approx(-2.03) and s["commission"] == -0.1 and s["swap"] == -0.2
    assert s["duration_s"] == 5600 and s["order_in"] == 77 and s["order_out"] == 0 and s["position_id"] == 77
    assert mh.summarize(deals[:1]) is None  # yopilmagan — yakun yo'q


def test_history_api_is_read_only():
    api = mh._HistoryAPI(SimpleNamespace(history_deals_get=lambda **k: [], positions_get=lambda: [], order_send=lambda r: 1,
                                         TRADE_ACTION_DEAL=1))
    for bad in ("order_send", "order_check", "positions_close", "orders_get", "TRADE_ACTION_DEAL"):
        with pytest.raises(PermissionError):
            getattr(api, bad)
    assert api.history_deals_get(position=1) == [] and api.positions_get() == []


def test_monitor_modules_have_no_order_or_credential_code():
    src = inspect.getsource(mh) + inspect.getsource(mm)
    names = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    assert not names & {"order_send", "order_check", "DemoTrader", "mt5_trader", "TRADE_ACTION_DEAL", "initialize", "login"}
    assert "bot_env" not in src and "token" not in src.lower() and "password" not in src.lower()


# ------------------------------------------------------------------------------------------------ V25: faqat shaxsiy chat
@pytest.mark.parametrize("private,group,owner", [(None, GROUP, OWNER), (-100123, GROUP, -100123), (GROUP, GROUP, GROUP),
                                                 (OWNER, GROUP, 555), (OWNER, OWNER, OWNER)])
def test_invalid_private_chat_never_redirects_anywhere(tmp_path, private, group, owner):
    svc, h, tg, q, mon, clock = make(tmp_path)
    svc.settings.data["private_chat_id"] = private
    svc.settings.data["group_chat_id"] = group
    q.chat_for = mm.private_chat_resolver(svc.settings, owner)
    q.enqueue("pv:closed:1", "closed", "private", "natija")
    r = run(q.flush())
    assert r["sent"] == 0 and r["waiting"] == 1 and not tg.sent  # hech qayerga yuborilmaydi
    assert svc.db.one("SELECT status FROM notifications WHERE key='pv:closed:1'")["status"] == "PENDING"  # navbatda saqlanadi


def test_group_target_is_never_resolved_and_all_monitor_messages_go_to_private(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    assert q.chat_for("group") is None and q.chat_for("private") == OWNER
    assert svc.settings.group_chat_id == GROUP and svc.settings.private_chat_id == OWNER  # alohida saqlanadi
    h.open = [pos()]
    mon.poll_once(NOW)
    h.open = []
    h.deals[2720676738] = sl_deals()
    mon.poll_once(NOW)
    h.fail = DataUnavailable("IPC timeout")
    for _ in range(4):
        mon.poll_once(NOW)
    run(q.flush())
    kinds = [t.split("\n")[0] for t in texts(tg)]
    assert any("POSITION OPENED" in k for k in kinds) and any("STOP LOSS HIT" in k for k in kinds)
    assert any("POST-TRADE REPORT" in k for k in kinds) and any("MT5 CONNECTION LOST" in k for k in kinds)
    assert {c for c, _ in tg.sent} == {OWNER}  # guruhga bitta xabar ham yo'q


def test_post_trade_report_has_eight_sections_with_real_numbers(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.open = [pos()]
    mon.poll_once(NOW)
    h.open = []
    h.deals[2720676738] = sl_deals()
    mon.poll_once(NOW)
    run(q.flush())
    rep = [t for t in texts(tg) if "POST-TRADE REPORT" in t][0]
    for n in range(1, 9):
        assert f"\n{n}) " in rep or rep.startswith(f"{n}) "), n
    assert "-1.73 USD" in rep and "-1.01R" in rep and "ATR(1h)" in rep and "Namuna: 1 savdo" in rep
    assert "GIPOTEZA" in rep and "bitta savdo asosida strategiya o'zgartirilmaydi" in rep


def test_startup_test_message_is_sent_once_to_private_chat(tmp_path):
    svc, h, tg, q, mon, clock = make(tmp_path)
    svc.settings.data["monitor"] = {"enabled": False, "test_pending": True, "republish": []}
    assert mon.startup_tasks(NOW) == ["test"]
    assert mon.startup_tasks(NOW) == []  # bayroq tozalangan: ikkinchi marta yuborilmaydi
    run(q.flush())
    assert len(tg.sent) == 1 and tg.sent[0][0] == OWNER and "TEST" in tg.sent[0][1] and "FAQAT shu shaxsiy chatga" in tg.sent[0][1]
    assert svc.db.one("SELECT status, message_id FROM notifications WHERE kind='test'")["status"] == "SENT"
    assert svc.settings.data["monitor"]["test_pending"] is False


def test_republish_resends_closed_and_report_to_private_once(tmp_path):
    svc, h, tg, q, mon, _ = make(tmp_path)
    h.deals[2720676738] = sl_deals()
    svc.db.execute("INSERT INTO mt5_positions(position_id, symbol, direction, volume, entry, state) VALUES(2720676738, "
                   "'BTCUSDm', 'SELL', 0.03, 75683.12, 'CLOSED')")
    h.open = [pos(pid=2720305695, symbol="ETHUSDm", price=2244.73, sl=2253.0, tp=2224.0, side="SELL", vol=0.1)]
    svc.settings.data["monitor"] = {"enabled": True, "test_pending": False, "republish": [2720676738, 2720305695]}
    assert mon.startup_tasks(NOW) == ["republish:2720676738", "republish:2720305695"]
    assert mon.startup_tasks(NOW) == []
    run(q.flush())
    ts = texts(tg)
    assert len(ts) == 3 and {c for c, _ in tg.sent} == {OWNER}
    assert any("STOP LOSS HIT" in x and "qayta yuborildi" in x for x in ts) and any("POST-TRADE REPORT" in x for x in ts)
    assert any("POSITION OPENED" in x and "ETHUSDm" in x for x in ts)
    # monitor keyin bu pozitsiyalarni takror e'lon qilmaydi (kalitlar yagona)
    mon.poll_once(NOW)
    run(q.flush())
    assert len(tg.sent) == 3


def test_scheduler_runs_startup_tasks_even_when_monitoring_is_disabled(tmp_path):
    from agent.trading.publish import Publisher
    from agent.trading.scheduler import TradingScheduler
    svc, h, tg, q, mon, _ = make(tmp_path)
    svc.settings.data["monitor"] = {"enabled": False, "poll_sec": 60, "test_pending": True, "republish": []}
    h.open = [pos()]

    async def notify(text):
        pass
    sch = TradingScheduler(svc, Publisher(svc.db, svc.settings, lambda *a: None, clock=svc.clock), notify)
    sch.monitor = mon
    run(sch._monitor(NOW))
    assert len(tg.sent) == 1 and "TEST" in tg.sent[0][1]  # test ketdi, lekin monitoring ishga tushmadi
    assert svc.db.one("SELECT COUNT(*) n FROM mt5_positions")["n"] == 0
    svc.settings.data["monitor"]["enabled"] = True
    run(sch._monitor(NOW + timedelta(seconds=61)))
    assert any("POSITION OPENED" in t for _, t in tg.sent)


def test_monitor_internal_error_goes_to_private_chat_as_alert(tmp_path):
    from agent.trading.publish import Publisher
    from agent.trading.scheduler import TradingScheduler
    svc, h, tg, q, mon, _ = make(tmp_path)

    def boom(now):
        raise RuntimeError("test")
    mon.poll_once = boom

    async def notify(text):
        pass
    sch = TradingScheduler(svc, Publisher(svc.db, svc.settings, lambda *a: None, clock=svc.clock), notify)
    sch.monitor = mon
    run(sch._monitor(NOW))
    run(sch._monitor(NOW + timedelta(seconds=61)))  # bir soat ichida ikkinchi xato — takror alert yo'q
    run(q.flush())
    errs = [t for _, t in tg.sent if "MONITORING ERROR" in t]
    assert len(errs) == 1 and tg.sent[0][0] == OWNER
