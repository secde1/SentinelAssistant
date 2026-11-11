"""Savdo (trading) tizimi bu loyihadan ajratilgan (D:\\sentinel-trading). IT-agent unga tegmasligi shart:
savdo moduli yo'q, savdo tool'lari yo'q, MT5 buyurtma kodini yozish bloklanadi."""
from __future__ import annotations

import asyncio
from pathlib import Path

from ctx_helper import _ctx

ROOT = Path(__file__).resolve().parents[1]


def test_trading_packages_and_tools_are_gone():
    for rel in ("agent/trading", "agent/zones", "agent/staff", "agent/webcontrol.py", "agent/tools/trading.py",
                "agent/tools/tradingview.py", "agent/dashboard/desk_api.py", "agent/dashboard/trading_api.py"):
        assert not (ROOT / rel).exists(), rel
    from agent.tools import ToolExecutor
    names = {s.name for s in ToolExecutor().specs}
    assert len(names) > 10 and not [n for n in names if n.startswith("trading")]


def test_config_has_no_trading_switch():
    from agent.config import Config
    assert not hasattr(Config(), "trading_enabled")


def test_write_file_with_order_code_is_still_blocked(tmp_path):
    from agent.tools import ToolExecutor
    ctx = _ctx(tmp_path)
    out, err = asyncio.run(ToolExecutor().execute(ctx, "write_file", {
        "path": "skript/trade.py", "content": "import MetaTrader5 as mt5\nmt5.order_send({'action': 1})\n"}))
    assert err and not (ctx.paths.skript / "trade.py").exists()
    ok, err2 = asyncio.run(ToolExecutor().execute(ctx, "write_file", {"path": "skript/note.txt", "content": "EURUSD 1h"}))
    assert not err2


def test_bot_has_no_trading_commands():
    src = (ROOT / "agent" / "bot.py").read_text(encoding="utf-8")
    assert "/trading" not in src and "_on_signal_callback" not in src
