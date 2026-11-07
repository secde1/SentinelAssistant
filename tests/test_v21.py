"""V21: korrelyatsiya bo'yicha umumiy risk va zararli strategiyalarni arxivlash (kod o'chirilmaydi)."""
from __future__ import annotations

import pytest

from agent.trading import exposure as ex
from agent.trading.strategies import ARCHIVE_V21, DEFAULT_STRATEGIES, ENGINES, Registry


def P(sym, d="LONG", r=1.0):
    return ex.Position(sym, d, r)


def test_symbol_names_are_canonical():
    assert [ex.canon(s) for s in ("BTCUSDm", "BTC/USD", "BTCUSDT", "XAUUSDm", "XAU/USD", "USTECm", "USTEC_x100m",
                                  "US500m", "EURUSDm", "EUR/USD")] == \
        ["BTC", "BTC", "BTC", "XAU", "XAU", "USTEC", "USTEC", "US500", "EURUSD", "EURUSD"]


def test_effective_risk_math():
    assert ex.effective_risk([P("BTCUSDm")]) == pytest.approx(1.0)
    assert ex.effective_risk([P("BTCUSDm"), P("BTCUSDm")]) == pytest.approx(2.0)  # bir xil aktiv — to'liq takror
    assert ex.effective_risk([P("BTCUSDm"), P("ETHUSDm")]) == pytest.approx((2 + 2 * 0.91) ** 0.5)
    # qarama-qarshi yo'nalish xavfni kamaytiradi
    assert ex.effective_risk([P("BTCUSDm"), P("ETHUSDm", "SHORT")]) < 0.5


def test_correlated_duplicates_are_rejected_independent_allowed():
    assert not ex.check([P("BTCUSDm")], P("ETHUSDm")).allowed  # 1.95 > 1.75
    assert not ex.check([P("USTECm")], P("US500m")).allowed
    assert not ex.check([P("EURUSDm")], P("GBPUSDm")).allowed
    assert ex.check([P("BTCUSDm")], P("XAUUSDm")).allowed  # 1.69
    assert not ex.check([P("BTCUSDm"), P("XAUUSDm")], P("EURUSDm")).allowed  # uchinchi, korrelyatsiyali — chegaradan oshadi
    assert ex.check([P("BTCUSDm")], P("ETHUSDm", "SHORT")).allowed  # hedge
    v = ex.check([P("BTCUSDm")], P("ETHUSDm"))
    assert "samarali risk" in v.reason and v.effective_risk == pytest.approx(1.95, abs=0.01)


def test_unknown_pair_is_conservative_and_reported():
    v = ex.check([P("BTCUSDm")], P("USDJPYm"))
    assert v.unknown_pairs == ["BTC/USDJPY"] and v.effective_risk == pytest.approx((2 + 2 * 0.5) ** 0.5, abs=0.001)


def test_archive_keeps_code_and_marks_registry(tmp_path):
    from agent.trading.db import TradingDB
    db = TradingDB(tmp_path / "t.db")
    reg = Registry(db)
    reg.sync_defaults()
    active = set(reg.active())
    assert active == {"TF-PULLBACK", "MA-CROSS", "VOL-BRK"}
    rows = {r["strategy_id"]: r for r in reg.all()}
    for sid in ARCHIVE_V21:
        assert rows[sid]["status"] == "archived" and "arxivlandi" in rows[sid]["notes"]
        assert sid in ENGINES and any(s.strategy_id == sid for s in DEFAULT_STRATEGIES)  # kod o'chirilmagan
    # qayta sync: holat o'zgarmaydi; egasi faollashtirsa qayta arxivlanmaydi
    reg.sync_defaults()
    assert set(reg.active()) == active
    reg.activate("RSI-MR", 1, approved_by="test")
    reg.sync_defaults()
    assert "RSI-MR" in reg.active()
