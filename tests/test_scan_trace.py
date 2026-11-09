"""Audit tuzatishlari: (1) skaner voronkasi scan_log'ga ANIQ sabab bilan yoziladi; (2) forex/metall sessiya bo'shlig'i xato emas (kripto uchun — xato)."""
from __future__ import annotations

import json

import pytest
from test_signals import make_signal_service, run

from agent.trading.data import DataUnavailable

GAP = "159 ta sham tushib qolgan (bozor yopiq bo'lgan vaqt bo'lishi mumkin)"


def _gap_everywhere(svc):
    real = svc.market.history

    def history(*a, **k):
        b = real(*a, **k)
        b.warnings = [GAP]
        return b
    svc.market.history = history


def test_scan_log_records_funnel_summary_and_specific_reasons(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)
    res = run(sv.scan_once())
    rows = svc.db.query("SELECT symbol, stage, strategy, outcome, reason FROM scan_log ORDER BY id")
    summary = [r for r in rows if r["stage"] == "summary"]
    assert len(summary) == 1 and json.loads(summary[0]["reason"])["scanned"] == res["scanned"] == 1  # voronka hisoblagichlari saqlandi
    stages = {r["stage"] for r in rows if r["symbol"] == "BTCUSDT"}
    assert "regime" in stages and ("strategy" in stages or "score" in stages or "decision" in stages)
    reasons = [r["reason"] for r in rows if r["symbol"] == "BTCUSDT" and r["outcome"] == "reject"]
    assert all(len(x) > 15 and x != "Conditions not met" for x in reasons)  # umumiy xabar emas, kod sharti


def test_scan_log_records_data_rejection_reason(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)
    _gap_everywhere(svc)  # kripto: bo'shliq — haqiqiy xato
    res = run(sv.scan_once())
    assert res["data_unavailable"] == 1
    r = svc.db.one("SELECT stage, outcome, reason FROM scan_log WHERE symbol='BTCUSDT'")
    assert r["stage"] == "data" and r["outcome"] == "reject" and "tushib qolgan" in r["reason"]


def test_session_gaps_do_not_disable_forex_instruments(tmp_path):
    """Regressiya: 320 ta 1H sham doim dam olish kunini qamraydi -> XAU/USD va EUR/USD hech qachon tahlil qilinmasdi."""
    svc, sv, tg = make_signal_service(tmp_path)
    _gap_everywhere(svc)
    svc.settings.data.setdefault("instruments", {})["BTCUSDT"] = {"provider": "binance", "market": "forex", "spread_bps": 1.0, "commission_pct": 0.0}
    sv.scan_symbol("BTCUSDT")  # DataUnavailable KO'TARILMASLIGI kerak
    traced = [x for x in sv._trace["BTCUSDT"] if x[0] == "data"]
    assert traced and "sessiya bo'shlig'i e'tiborga olinmadi" in traced[0][3]
    svc.settings.data["instruments"]["BTCUSDT"]["market"] = "crypto"
    with pytest.raises(DataUnavailable):
        sv.scan_symbol("BTCUSDT")
