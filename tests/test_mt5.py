"""V19 MetaTrader 5: faqat o'qish ulanishi, tarixiy ma'lumot, server vaqti, ma'lumot yo'qligi, simvol nomlari, buyurtma
funksiyalari yo'qligi. Soxta MT5 moduli bilan (terminal kerak emas). Jonli testlar: MT5_LIVE=1."""
from __future__ import annotations

import ast
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from agent.trading import mt5_connector as m
from agent.trading.data import DataUnavailable, MarketData

NOW = datetime(2026, 11, 6, 13, 20, 30, tzinfo=timezone.utc)
OFFSET = 2 * 3600  # broker server vaqti UTC+2
RATE = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                 ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])


def bars(n: int, last_open_utc: datetime, sec: int = 3600, base: float = 1.08) -> np.ndarray:
    rows = []
    for i in range(n):
        ts = last_open_utc - timedelta(seconds=sec * (n - 1 - i))
        o = base + i * 0.0001
        rows.append((int(ts.timestamp()) + OFFSET, o, o + 0.0008, o - 0.0007, o + 0.0002, 100 + i, 5, 0))
    return np.array(rows, dtype=RATE)


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_H1, TIMEFRAME_H4 = 1, 16385, 16388
    TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_M30, TIMEFRAME_D1 = 5, 15, 30, 16408

    def __init__(self, trade_mode=0, logged_in=True, names=("EURUSD", "XAUUSDm", "BTCUSD"), tick_age=1, rates=None):
        self.calls: list[tuple] = []
        self.trade_mode, self.logged_in, self.names, self.tick_age = trade_mode, logged_in, names, tick_age
        self.rates = rates
        self.visible: set[str] = {"EURUSD"}
        self.shutdowns = 0

    def initialize(self, *args, **kw):
        self.calls.append(("initialize", args, kw))
        return True

    def shutdown(self):
        self.shutdowns += 1

    def last_error(self):
        return (1, "Success")

    def version(self):
        return (500, 5370, "06 Nov 2026")

    def terminal_info(self):
        return SimpleNamespace(connected=True, trade_allowed=False, name="MetaTrader 5")

    def account_info(self):
        if not self.logged_in:
            return None
        return SimpleNamespace(trade_mode=self.trade_mode, server="MetaQuotes-Demo", login=123456, balance=10000.0,
                               name="Owner")

    def symbols_total(self):
        return len(self.names)

    def symbols_get(self):
        return [SimpleNamespace(name=n) for n in self.names]

    def symbol_info(self, name):
        return SimpleNamespace(name=name, visible=name in self.visible) if name in self.names else None

    def symbol_select(self, name, enable):
        self.calls.append(("symbol_select", name, enable))
        self.visible.add(name)
        return True

    def symbol_info_tick(self, name):
        # jonli bozor: har chaqiruvda yangi tik; yopiq bozor (tick_age katta): tik o'zgarmaydi
        self.ticks = getattr(self, "ticks", 0) + (1 if self.tick_age < 60 else 0)
        t = int(NOW.timestamp()) + OFFSET - self.tick_age
        return SimpleNamespace(time=t, time_msc=t * 1000 + self.ticks)

    def copy_rates_from_pos(self, name, tf, pos, count):
        self.calls.append(("copy_rates_from_pos", name, tf, pos, count))
        if self.rates is not None:
            return self.rates
        # oxirgi (hali yopilmagan) sham 13:00 UTC da ochilgan
        return bars(count, NOW.replace(minute=0, second=0))

    def copy_rates_from(self, name, tf, date_from, count):
        self.calls.append(("copy_rates_from", name, tf, date_from, count))
        return bars(count, datetime.fromtimestamp(date_from.timestamp() - OFFSET, tz=timezone.utc)
                    .replace(minute=0, second=0))

    def copy_rates_range(self, name, tf, date_from, date_to):
        self.calls.append(("copy_rates_range", name, tf, date_from, date_to))
        start = datetime.fromtimestamp(date_from.timestamp() - OFFSET, tz=timezone.utc)
        n = int((date_to - date_from).total_seconds() // 60)
        return bars(n, start + timedelta(minutes=n - 1), sec=60)

    def order_send(self, request):  # haqiqiy paketda bor — qobiq orqali chaqirib bo'lmasligi kerak
        raise AssertionError("order_send chaqirildi!")


ME = m.current_user()
RUNNING = [{"path": r"C:\Program Files\MetaTrader 5\terminal64.exe", "name": "MetaTrader 5", "running": True,
            "user": ME, "pid": 1}]


def conn(fake=None, terminals=None, **kw) -> m.MT5Connector:
    return m.MT5Connector(module=fake or FakeMT5(), terminals=RUNNING if terminals is None else terminals,
                          clock=lambda: NOW, sleep=lambda s: None, **kw)


# ------------------------------------------------------------------------------------------------ ulanish
def test_connection_is_read_only_and_never_passes_credentials():
    fake = FakeMT5()
    c = conn(fake)
    info = c.connect()
    assert info["trade_mode"] == "DEMO" and info["server"] == "MetaQuotes-Demo" and info["build"] == 5370
    assert "login" not in info and "balance" not in info and "name" not in info  # hisob ma'lumoti saqlanmaydi
    _, args, kw = fake.calls[0]
    assert not args and set(kw) == {"path", "timeout"}  # login/parol/server berilmaydi
    with pytest.raises(PermissionError):
        c.mt5.order_send({"action": 1})
    for name in ("order_check", "positions_get", "orders_get", "history_deals_get"):
        with pytest.raises(PermissionError):
            getattr(c.mt5, name)


def test_connection_refusals_are_explicit():
    with pytest.raises(DataUnavailable, match="ochiq emas"):
        conn(terminals=[{**RUNNING[0], "running": False, "user": None}]).connect()
    with pytest.raises(DataUnavailable, match="boshqa foydalanuvchi"):
        conn(terminals=[{**RUNNING[0], "user": r"OTHERPC\someone"}]).connect()
    with pytest.raises(DataUnavailable, match="hisobga kirilmagan"):
        conn(FakeMT5(logged_in=False)).connect()
    real = FakeMT5(trade_mode=2)
    with pytest.raises(DataUnavailable, match="REAL"):
        conn(real).connect()
    assert real.shutdowns == 1  # rad etilganda ulanish yopiladi
    assert conn(FakeMT5(trade_mode=2), allow_real=True).connect()["trade_mode"] == "REAL"
    two = RUNNING + [{**RUNNING[0], "path": r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe",
                      "name": "MetaTrader 5 EXNESS"}]
    with pytest.raises(DataUnavailable, match="bir nechta"):
        conn(terminals=two).connect()
    assert conn(terminals=two, path=two[1]["path"]).connect()["terminal"] == "MetaTrader 5 EXNESS"
    with pytest.raises(DataUnavailable, match="topilmadi"):
        conn(terminals=[]).connect()


def test_choose_terminal_never_guesses_between_installs():
    a = {"path": "a", "name": "A", "running": False}
    b = {"path": "b", "name": "B", "running": False}
    assert m.choose_terminal([a])[0] is a
    assert m.choose_terminal([a, b])[0] is None
    assert m.choose_terminal([a, {**b, "running": True}])[0]["name"] == "B"


# ------------------------------------------------------------------------------------------------ tarixiy ma'lumot
def test_historical_retrieval_converts_server_time_to_utc_and_drops_forming_bar():
    c = conn()
    candles = c.candles("EUR/USD", "1h", 100)
    assert len(candles) == 100
    assert candles[-1].ts == datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)  # server 15:00 -> UTC 13:00
    assert all((b.ts - a.ts).total_seconds() == 3600 for a, b in zip(candles, candles[1:]))

    settings = SimpleNamespace(instrument=lambda s: {"provider": "mt5", "market": "forex"})
    md = MarketData(settings, {"mt5": m.MT5Provider(c)}, clock=lambda: NOW)
    bundle = md.history("EUR/USD", "1h", 60)
    assert bundle.candles[-1].end <= NOW  # shakllanayotgan sham tahlilga kirmaydi
    assert bundle.candles[-1].ts == datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)
    assert "MetaQuotes-Demo" in bundle.source and "DEMO" in bundle.source and "faqat o'qish" in bundle.source


def test_forward_and_range_queries_use_server_time_arguments():
    fake = FakeMT5()
    c = conn(fake)
    start = datetime(2026, 11, 6, 10, 0, tzinfo=timezone.utc)
    fine = c.candles("XAU/USD", "1min", 30, start=start, end=start + timedelta(minutes=30))
    call = next(x for x in fake.calls if x[0] == "copy_rates_range")
    assert call[1] == "XAUUSDm" and call[3].timestamp() == start.timestamp() + OFFSET
    assert fine[0].ts == start and len(fine) == 30
    assert ("symbol_select", "XAUUSDm", True) in fake.calls  # Market Watch ga qo'shildi (ko'rinmas edi)
    end = datetime(2026, 11, 5, 0, 0, tzinfo=timezone.utc)
    hist = c.candles("EUR/USD", "1h", 50, end=end)
    assert hist and hist[-1].ts < end


def test_server_offset_is_measured_or_cached_never_guessed(tmp_path):
    state = tmp_path / "mt5_state.json"
    c = conn(state_file=state)
    c.connect()
    assert c.server_offset(("EURUSD",)) == OFFSET and state.is_file()
    stale = conn(FakeMT5(tick_age=3 * 86400), state_file=state)  # dam olish kuni: yangi tik yo'q
    stale.connect()
    assert stale.server_offset(("EURUSD",)) == OFFSET  # 7 kunlik saqlangan o'lchov
    fresh_none = conn(FakeMT5(tick_age=3 * 86400), state_file=tmp_path / "none.json")
    fresh_none.connect()
    with pytest.raises(DataUnavailable, match="taxmin qilinmaydi"):
        fresh_none.server_offset(("EURUSD",))
    # bozor yopilganiga roppa-rosa 1 soat: eski tik +1 soat siljish "ko'rsatadi" — lekin u o'zgarmaydi, ishlatilmaydi
    just_closed = conn(FakeMT5(tick_age=3600), state_file=tmp_path / "none2.json")
    just_closed.connect()
    with pytest.raises(DataUnavailable):
        just_closed.server_offset(("EURUSD",))


# ------------------------------------------------------------------------------------------------ ma'lumot yo'qligi
def test_missing_data_is_reported_not_invented():
    class NoRates(FakeMT5):
        def copy_rates_from_pos(self, *a):
            return None

        def last_error(self):
            return (-1, "Terminal: Call failed")
    with pytest.raises(DataUnavailable, match="ma'lumot qaytmadi"):
        conn(NoRates()).candles("EUR/USD", "1h", 10)
    with pytest.raises(DataUnavailable, match="topilmadi"):
        conn().candles("GBP/JPY", "1h", 10)
    with pytest.raises(DataUnavailable, match="qo'llab-quvvatlanmaydi"):
        conn().candles("EUR/USD", "2h", 10)
    settings = SimpleNamespace(instrument=lambda s: {"provider": "mt5", "market": "forex"})
    short = conn(FakeMT5(rates=bars(10, NOW.replace(minute=0, second=0))))
    with pytest.raises(DataUnavailable, match="yetarli emas"):
        MarketData(settings, {"mt5": m.MT5Provider(short)}, clock=lambda: NOW).history("EUR/USD", "1h", 100)


def test_symbol_resolution_for_broker_suffixes_and_aliases():
    c = conn(FakeMT5(names=("EURUSD.a", "XAUUSDm", "BTCUSD")))
    c.connect()
    assert c.resolve("EUR/USD") == "EURUSD.a" and c.resolve("XAU/USD") == "XAUUSDm"
    c2 = conn(FakeMT5(names=("EURUSD", "GOLD")))
    c2.connect()
    assert c2.resolve("XAU/USD") == "GOLD"


def test_module_source_contains_no_order_calls():
    src = Path(m.__file__).read_text(encoding="utf-8")
    called = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)}
    forbidden = {"order_send", "order_check", "order_calc_margin", "positions_get", "orders_get", "history_deals_get",
                 "history_orders_get", "login"}
    assert not (called & forbidden)
    assert not (m.ALLOWED & forbidden)


# ------------------------------------------------------------------------------------------------ jonli (MT5_LIVE=1)
live = pytest.mark.skipif(os.environ.get("MT5_LIVE") != "1", reason="jonli MT5 testi: MT5_LIVE=1")


@live
def test_live_terminal_connection():
    c = m.MT5Connector.from_env(os.environ)
    info = c.connect()
    assert info["trade_mode"] in ("DEMO", "CONTEST") and info["symbols"] > 0
    c.close()


@live
def test_live_historical_retrieval():
    c = m.MT5Connector.from_env(os.environ)
    candles = c.candles("EUR/USD", "1h", 200)
    assert len(candles) >= 150 and all(x.high >= x.low > 0 for x in candles)
    c.close()


# ------------------------------------------------------------------------------------------------ gate va tool
def test_gate_requires_approval_for_orders_and_direct_mt5():
    from agent import gate
    for cmd in ('python -c "import MetaTrader5 as mt5; mt5.order_send({})"', "client.create_order(symbol='BTCUSDT')",
                "trade.PositionClose(ticket)", "req = {'action': mt5.TRADE_ACTION_DEAL}"):
        assert gate.classify_powershell(cmd).level == gate.DANGER, cmd
    for cmd in (r"& 'D:\it-agent\.venv\Scripts\python.exe' -c 'import MetaTrader5'",
                r"Start-Process 'C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe'"):
        assert gate.classify_powershell(cmd).level == gate.DANGER, cmd
    for cmd in ("Get-Process terminal64 | Select Id, Path", r"Get-ChildItem 'C:\Program Files' -Filter terminal64.exe"):
        assert gate.classify_powershell(cmd).level == gate.READ, cmd
    # skript matni ham tekshiriladi (referenced_scripts orqali)
    assert gate.classify_powershell("python run.py", extra_texts=["mt5.order_send(request)"]).level == gate.DANGER


def _ctx(tmp_path):
    from agent.config import Config
    from agent.inventory import Inventory
    from agent.journal import Journal
    from agent.redact import Redactor
    from agent.tools import ToolContext
    from agent.workspace import ensure_workspace

    paths = ensure_workspace(tmp_path / "home")
    inv = Inventory(paths.inventory_json)
    red = Redactor(inv.secret_values)

    class Ch:
        async def send(self, t): pass
        async def send_file(self, p, c=""): pass
        async def ask(self, q): return None
        async def request_approval(self, t): return False
        async def request_secret(self, p): return None
    return ToolContext(task_id="T-MT5", cfg=Config(agent_home=paths.home), paths=paths, inventory=inv, redactor=red,
                       journal=Journal(paths.jurnal, red), channel=Ch())


def test_write_file_with_order_code_is_blocked(tmp_path):
    import asyncio

    from agent.tools import ToolExecutor
    ctx = _ctx(tmp_path)
    out, err = asyncio.run(ToolExecutor().execute(ctx, "write_file", {
        "path": "skript/trade.py", "content": "import MetaTrader5 as mt5\nmt5.order_send({'action': 1})\n"}))
    assert err and not (ctx.paths.skript / "trade.py").exists()
    ok, err2 = asyncio.run(ToolExecutor().execute(ctx, "write_file", {"path": "skript/note.txt", "content": "EURUSD 1h"}))
    assert not err2


def test_mt5_status_tool_reports_connection_and_history(tmp_path):
    import asyncio

    from agent.tools import ToolExecutor
    from agent.tools.trading import _service
    ctx = _ctx(tmp_path)
    svc = _service(ctx)
    svc._mt5 = conn()
    out, err = asyncio.run(ToolExecutor().execute(ctx, "trading_mt5_status", {"symbol": "EUR/USD", "timeframe": "1h"}))
    assert not err and "Ulanish: OK" in out and "DEMO" in out and "EURUSD 1h: 200 ta yopilgan sham" in out
    assert "UTC+2.0" in out and "12:00 UTC" in out
    svc._mt5 = conn(terminals=[{**RUNNING[0], "running": False, "user": None}])
    out2, err2 = asyncio.run(ToolExecutor().execute(ctx, "trading_mt5_status", {}))
    assert err2 and "Ulanish: YO'Q" in out2 and "ishga tushirmaydi" in out2
