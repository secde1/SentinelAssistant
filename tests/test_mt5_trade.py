"""V20 MT5 DEMO savdo: faqat DEMO, SL majburiy, lot/pozitsiya chegarasi, faqat o'zimizning pozitsiyalar, haqiqiy natija.
Soxta MT5 moduli bilan (terminal va hisob kerak emas)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from test_mt5 import RUNNING, FakeMT5

from agent.trading import mt5_connector as m
from agent.trading import mt5_trade as t

OWN, FOREIGN = t.MAGIC, 777


class TradeMT5(FakeMT5):
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TIME_GTC = 1, 0, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2

    def __init__(self, check_code=0, send_code=10009, **kw):
        super().__init__(**kw)
        self.check_code, self.send_code = check_code, send_code
        self.sent, self.checked = [], []
        self.pos = [SimpleNamespace(ticket=1, symbol="EURUSD", type=0, volume=0.01, price_open=1.08, sl=1.0, tp=0.0,
                                    profit=1.5, magic=OWN),
                    SimpleNamespace(ticket=2, symbol="EURUSD", type=1, volume=0.5, price_open=1.09, sl=0.0, tp=0.0,
                                    profit=-9.0, magic=FOREIGN)]

    def symbol_info(self, name):
        if name not in self.names:
            return None
        return SimpleNamespace(name=name, visible=True, volume_min=0.01, volume_step=0.01, filling_mode=2)

    def symbol_info_tick(self, name):
        if name == "NOTICK":
            return None
        return SimpleNamespace(ask=1.1000, bid=1.0998, time=0, time_msc=0)

    def positions_get(self):
        return list(self.pos)

    def order_check(self, req):
        self.checked.append(req)
        return SimpleNamespace(retcode=self.check_code, comment="Done" if not self.check_code else "No money")

    def order_send(self, req):
        self.sent.append(req)
        return SimpleNamespace(retcode=self.send_code, comment="Request executed", order=55, deal=66, price=1.1, volume=0.01)


def trader(fake=None, tmp_path=None, **kw) -> t.DemoTrader:
    c = m.MT5Connector(module=fake or TradeMT5(), terminals=RUNNING, sleep=lambda s: None)
    return t.DemoTrader(c, log_file=(tmp_path / "log.jsonl") if tmp_path else None, **kw)


def test_dry_run_checks_but_never_sends():
    f = TradeMT5()
    r = trader(f).open("EUR/USD", "buy", 0.01, sl=1.095, tp=1.11, dry_run=True)
    assert r["ok"] and r["stage"] == "order_check" and "YUBORILMADI" in r["comment"]
    assert len(f.checked) == 1 and f.sent == []


def test_open_sends_checked_demo_order_and_logs_without_account_data(tmp_path):
    f = TradeMT5()
    r = trader(f, tmp_path).open("EUR/USD", "buy", 0.01, sl=1.095, tp=1.11)
    assert r["ok"] and r["retcode"] == 10009 and r["order"] == 55
    req = f.sent[0]
    assert req["magic"] == OWN and req["sl"] == 1.095 and req["tp"] == 1.11 and req["price"] == 1.1000
    assert req["type_filling"] == f.ORDER_FILLING_IOC  # broker IOC ni qo'llaydi
    log = (tmp_path / "log.jsonl").read_text(encoding="utf-8")
    assert "123456" not in log and "Owner" not in log and "10000" not in log and "MetaQuotes-Demo" in log


def test_sell_uses_bid_and_sl_above():
    f = TradeMT5()
    assert trader(f).open("EURUSD", "sell", 0.01, sl=1.105)["ok"]
    assert f.sent[0]["price"] == 1.0998
    with pytest.raises(t.TradeRefused, match="noto'g'ri tomonida"):
        trader(TradeMT5()).open("EURUSD", "sell", 0.01, sl=1.09)


@pytest.mark.parametrize("mode", [1, 2])
def test_real_and_contest_accounts_are_refused(mode):
    f = TradeMT5(trade_mode=mode)
    with pytest.raises(t.TradeRefused, match="REAL|DEMO emas"):
        trader(f).open("EURUSD", "buy", 0.01, sl=1.09)
    assert f.sent == [] and f.checked == []


def test_real_account_refused_even_if_read_access_is_allowed():
    f = TradeMT5(trade_mode=2)
    c = m.MT5Connector(module=f, terminals=RUNNING, allow_real=True, sleep=lambda s: None)
    with pytest.raises(t.TradeRefused, match="DEMO emas"):
        t.DemoTrader(c).open("EURUSD", "buy", 0.01, sl=1.09)
    assert f.sent == []


def test_parameter_limits():
    f = TradeMT5()
    tr = trader(f)
    for kw, msg in (({"sl": 0}, "majburiy"), ({"sl": 1.09, "lot": 0.5}, "chegaradan"), ({"sl": 1.09, "lot": 0}, "chegaradan"),
                    ({"sl": 1.09, "lot": 0.015}, "qadam"), ({"sl": 1.09, "tp": 1.05}, "TP")):
        with pytest.raises(t.TradeRefused, match=msg):
            tr.open("EURUSD", "buy", kw.pop("lot", 0.01), **kw)
    with pytest.raises(t.TradeRefused, match="side"):
        tr.open("EURUSD", "hold", 0.01, sl=1.09)
    with pytest.raises(t.TradeRefused, match="topilmadi"):
        tr.open("NOPE", "buy", 0.01, sl=1.09)
    assert f.sent == []


def test_open_positions_limit_counts_only_own():
    f = TradeMT5()
    assert trader(f, max_positions=2).open("EURUSD", "buy", 0.01, sl=1.09)["ok"]  # 1 ta o'zimizniki, begonaniki sanalmaydi
    with pytest.raises(t.TradeRefused, match="chegarasi"):
        trader(f, max_positions=1).open("EURUSD", "buy", 0.01, sl=1.09)


def test_order_check_failure_is_reported_and_nothing_sent():
    f = TradeMT5(check_code=10019)
    r = trader(f).open("EURUSD", "buy", 0.01, sl=1.09)
    assert not r["ok"] and r["stage"] == "order_check" and r["retcode"] == 10019 and f.sent == []


def test_send_failure_is_not_reported_as_success():
    r = trader(TradeMT5(send_code=10006)).open("EURUSD", "buy", 0.01, sl=1.09)
    assert not r["ok"] and r["retcode"] == 10006


def test_positions_show_only_own_and_close_only_own():
    f = TradeMT5()
    tr = trader(f)
    assert [p["ticket"] for p in tr.positions()] == [1]
    with pytest.raises(t.TradeRefused, match="bizning"):
        tr.close(2)  # qo'lda/EA ochgan pozitsiya
    assert f.sent == []
    r = tr.close(1)
    assert r["ok"] and f.sent[0]["position"] == 1 and f.sent[0]["type"] == f.ORDER_TYPE_SELL and f.sent[0]["price"] == 1.0998


def test_trade_api_wrapper_is_narrow():
    api = t._TradeAPI(TradeMT5())
    for name in ("initialize", "shutdown", "history_deals_get", "order_calc_margin", "symbol_select"):
        with pytest.raises(PermissionError):
            getattr(api, name)
    assert api.TRADE_ACTION_DEAL == 1


def test_connector_module_still_has_no_order_code():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(m))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"order_send", "order_check", "positions_get"}


def test_tool_gate_levels_and_flow(tmp_path):
    import asyncio

    from agent import gate
    from agent.tools import ToolExecutor
    from agent.tools.trading import _service, classify_mt5_order
    assert classify_mt5_order(None, {"action": "open"}).level == gate.DANGER
    assert classify_mt5_order(None, {"action": "close"}).level == gate.DANGER
    assert classify_mt5_order(None, {"action": "check"}).level == gate.READ
    assert classify_mt5_order(None, {"action": "positions"}).level == gate.READ
    from test_mt5 import _ctx
    ctx = _ctx(tmp_path)
    f = TradeMT5()
    svc = _service(ctx)
    svc.mt5._module, svc.mt5._terminals = f, RUNNING
    svc.mt5._sleep = lambda s: None
    out, err = asyncio.run(ToolExecutor().execute(ctx, "trading_mt5_order", {
        "action": "check", "symbol": "EUR/USD", "side": "buy", "lot": 0.01, "sl": 1.095}))
    assert not err and "TEKSHIRUV O'TDI" in out and f.sent == []
    out, err = asyncio.run(ToolExecutor().execute(ctx, "trading_mt5_order", {
        "action": "open", "symbol": "EUR/USD", "side": "buy", "lot": 0.01}))
    assert err and "tasdiqlamadi" in out and f.sent == []  # open har safar tasdiq so'raydi; tasdiqsiz yuborilmaydi
