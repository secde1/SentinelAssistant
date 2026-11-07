"""V17 TradingView: Pine generatsiyasi va tekshiruvi, annotatsiyalar soni, instrument/taymfreym, integratsiya yo'qligi,
rost holat, mavjud fayllarni saqlash, dublikat annotatsiyaning oldini olish. Tarmoq, TradingView va Telegram'siz."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent import gate
from agent.trading import tradingview as tv
from agent.verification import Facts, decide

BTC = {"id": "BTC-SHORT-20261106-01", "symbol": "BTCUSDT", "timeframe": "1h", "direction": "SHORT",
       "entry_type": "sell_limit", "entry": 76600, "sl": 77500, "tp": [75250, 74400], "strategy": "Manual-Research",
       "version": "0", "created": "2026-11-06T15:25:00+05:00",
       "invalidation": "1H close above 77500 voids it; no entry if price never reaches 76600"}


def manual(**kw) -> tv.Scenario:
    return tv.scenario_manual({**BTC, **kw})


# ------------------------------------------------------------------------------------------------ generatsiya
def test_pine_generation_preserves_scenario_and_labels():
    sc = manual()
    code = tv.generate(sc)
    assert code.startswith("//@version=5\n")
    for price in ("76600.0", "77500.0", "75250.0", "74400.0"):
        assert f"hline({price}," in code
    for need in (tv.DISCLAIMER, "ID BTC-SHORT-20261106-01", "Manual-Research v0 SHORT", "Created 2026-11-06T15:25:00+05:00",
                 "INVALID: 1H close above 77500", 'EXPECT_TICKER = "BTCUSDT"', 'EXPECT_TF = "60"', tv.MATCH_TEXT,
                 "not guaranteed"):
        assert need in code, need
    v = tv.validate_pine(code, sc)
    assert v.ok, v.errors
    assert "tasdiqlanmagan" in v.compiled  # statik tekshiruv kompilyatsiya emas


def test_expected_annotation_count():
    sc = manual()
    v = tv.validate_pine(tv.generate(sc), sc)
    assert len([a for a in v.annotations if a.startswith("SIM ")]) == 4  # entry + SL + 2 TP
    sc3 = manual(tp=[75250, 74400, 73500])
    code3 = tv.generate(sc3)
    assert code3.count("\nhline(") == 5 and tv.validate_pine(code3, sc3).ok


def test_instrument_identification():
    assert tv.tv_ticker("XAU/USD") == "XAUUSD" and tv.tv_ticker("btcusdt") == "BTCUSDT"
    assert tv.exchange_for("BTCUSDT", "Binance public market data") == "BINANCE"
    assert tv.exchange_for("EUR/USD") == "OANDA"
    with pytest.raises(tv.ScenarioError):
        tv.tv_ticker("??")
    sc = manual()
    assert sc.chart_url() == "https://www.tradingview.com/chart/?symbol=BINANCE:BTCUSDT&interval=60"


def test_timeframe_identification():
    assert [tv.tf_code(t) for t in ("1h", "4h", "1d", "15m", "1H")] == ["60", "240", "D", "15", "60"]
    with pytest.raises(tv.ScenarioError, match="taymfreym"):
        tv.tf_code("7h")
    assert 'EXPECT_TF = "240"' in tv.generate(manual(timeframe="4h"))


def test_numeric_inputs_and_order_are_validated():
    with pytest.raises(tv.ScenarioError, match="mantiqsiz"):
        manual(sl=76000)  # SHORT uchun SL kirishdan past
    with pytest.raises(tv.ScenarioError, match="dublikat"):
        manual(tp=[75250, 75250])
    with pytest.raises(tv.ScenarioError):
        manual(entry=float("nan"))
    with pytest.raises(tv.ScenarioError, match="mintaqa"):
        manual(created="2026-11-06T15:25:00")


def test_validator_rejects_unsafe_or_wrong_pine():
    sc = manual()
    good = tv.generate(sc)
    bad = {
        "v4": good.replace("@version=5", "@version=4"),
        "order": good + 'strategy.entry("x", strategy.short)\n',
        "other_data": good + 'x = request.security("BINANCE:ETHUSDT", "60", close)\n',
        "paren": good.replace("overlay=true)", "overlay=true", 1),
        "missing_level": good.replace(
            'hline(74400.0, "SIM TP2 74400", color=color.green, linewidth=2, linestyle=hline.style_solid)\n', ""),
        "changed_price": good.replace("hline(76600.0", "hline(76601.0"),
        "duplicate": good.replace('hline(77500.0, "SIM SL 77500"', 'hline(76600.0, "SIM ENTRY 76600"'),
        "no_label": good.replace(tv.DISCLAIMER, "RESEARCH"),
        "plot_spam": good + "plot(close)\n",
        "guarantee": good.replace("not guaranteed", "guaranteed profit"),
        "tab": good.replace("    table.cell(info, 0, 0", "\ttable.cell(info, 0, 0", 1),
    }
    for name, code in bad.items():
        assert not tv.validate_pine(code, sc).ok, name


def test_non_ascii_texts_are_transliterated():
    sc = manual(invalidation=tv.ascii_text("Кириш: 1H шам 77 500 дан юқорида ёпилса — бекор"))
    assert sc.invalidation.startswith("Kirish: 1H sham 77 500") and tv.validate_pine(tv.generate(sc), sc).ok


def test_scenario_from_research_analysis_keeps_original_levels():
    rec = {"analysis_id": "TA-20261106-06", "kind": "TRADE", "symbol": "ETHUSDT", "timeframe": "4h", "direction": "SHORT",
           "entry_type": "next_open", "entry": 2239.1, "sl": 2290.5, "tp": 2136.3, "strategy_id": "MA-CROSS",
           "strategy_version": 1, "created_at": "2026-11-06T11:20:00+00:00", "data_source": "Binance public market data",
           "invalidation": {"type": "close_above", "level": 2255.4, "text": "kirishdan oldin EMA9 yana EMA21 dan yuqoriga chiqsa"},
           "content_hash": "abc"}
    sc = tv.scenario_from_analysis(rec)
    assert (sc.entry, sc.sl, sc.tps) == (2239.1, 2290.5, [2136.3]) and sc.exchange == "BINANCE" and sc.tf == "240"
    assert "2255.4" in sc.invalidation and sc.strategy == "MA-CROSS" and sc.version == "1"
    with pytest.raises(tv.ScenarioError, match="NO-TRADE"):
        tv.scenario_from_analysis({**rec, "kind": "NO_TRADE"})


# ------------------------------------------------------------------------------------------------ saqlash
def test_existing_files_preserved_and_duplicates_prevented(tmp_path):
    store = tv.PineStore(tmp_path / "pine")
    sc = manual()
    code = tv.generate(sc)
    v = tv.validate_pine(code, sc)
    first = store.save(sc, code, v)
    assert first["status"] == "saved"
    assert store.save(sc, code, v)["status"] == "duplicate"  # bir xil ssenariy qayta yaratilmaydi
    assert len(list((tmp_path / "pine").glob("*.pine"))) == 1
    # Boshqa (masalan foydalanuvchi o'zgartirgan) fayl ustiga yozilmaydi — yangi versiya nomi
    sc2 = manual(tp=[75000, 74400])
    path = Path(first["file"])
    original = path.read_text(encoding="ascii")
    path2 = path.parent / f"{sc2.ticker}_{sc2.tf}_{sc2.id}.pine"
    assert path2 == path  # bir xil nom
    second = store.save(sc2, tv.generate(sc2), tv.validate_pine(tv.generate(sc2), sc2))
    assert second["status"] == "saved" and second["file"].endswith("_v2.pine")
    assert path.read_text(encoding="ascii") == original
    assert store.find(sc.id)["file"] == second["file"]  # eng yangisi


# ------------------------------------------------------------------------------------------------ qurilma
def test_device_identification_never_confuses_laptops():
    remote = {"nb-xs-tex02"}
    assert tv.resolve_device("local", "XS-NB-AUP06", remote) == ("local", "XS-NB-AUP06")
    assert tv.resolve_device("XS-NB-AUP06", "XS-NB-AUP06", remote)[0] == "local"
    assert tv.resolve_device("NB-XS-TEX02.xonsaroy.local", "XS-NB-AUP06", remote)[0] == "remote"
    assert tv.resolve_device("", "XS-NB-AUP06", remote)[0] == "local"
    assert tv.resolve_device("ноутбук-3", "XS-NB-AUP06", remote)[0] == "ambiguous"


def test_remote_device_reports_needs_setup(monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "XS-NB-AUP06")
    env = tv.environment("nb-xs-tex02", {"nb-xs-tex02"})
    assert env["state"] == "needs_setup" and "ish stoli yo'q" in env["reason"]
    assert tv.environment("qaysidir", {"nb-xs-tex02"})["state"] == "ambiguous"


def test_missing_integration_paths(monkeypatch):
    monkeypatch.setenv("COMPUTERNAME", "XS-NB-AUP06")
    monkeypatch.setattr(tv, "tradingview_installed", lambda: (False, "TradingView Desktop (MSIX) topilmadi"))
    monkeypatch.setattr(tv, "interactive_session", lambda: (True, "ok"))
    monkeypatch.setattr(tv, "find_windows", lambda target="auto", ticker="": [])
    assert tv.environment("local")["state"] == "needs_setup"
    monkeypatch.setattr(tv, "tradingview_installed", lambda: (True, "TradingView Desktop 3.5"))
    monkeypatch.setattr(tv, "interactive_session", lambda: (False, "ish stoli qulflangan"))
    assert tv.environment("local")["state"] == "needs_setup"
    monkeypatch.setattr(tv, "interactive_session", lambda: (True, "ok"))
    assert tv.environment("local")["state"] == "unverified"  # ilova bor, oyna yopiq
    monkeypatch.setattr(tv, "find_windows", lambda target="auto", ticker="": [
        {"hwnd": 123, "title": "BTCUSDT 76 100", "kind": "desktop"}])
    env = tv.environment("local")
    assert env["state"] == "ready" and env["window_title"] == "BTCUSDT 76 100"
    # Desktop o'rnatilmagan, lekin brauzerda TradingView yorlig'i ochiq — veb versiya tekshiriladi
    monkeypatch.setattr(tv, "tradingview_installed", lambda: (False, "TradingView Desktop (MSIX) topilmadi"))
    monkeypatch.setattr(tv, "find_windows", lambda target="auto", ticker="": [] if target == "desktop" else [
        {"hwnd": 7, "title": "BTCUSDT 76 100 ▼ -0.2% Unnamed - Google Chrome", "kind": "browser"}])
    assert tv.environment("local")["state"] == "ready"
    assert tv.environment("local", target="desktop")["state"] == "needs_setup"
    monkeypatch.setattr(tv, "find_windows", lambda target="auto", ticker="": [])
    env = tv.environment("local", target="browser")
    assert env["state"] == "unverified" and "faol" in env["reason"]


def test_browser_window_selection_uses_title_only_to_locate():
    assert tv.tv_like_title("BTCUSD 75 817,22 ▼ −0.25% Unnamed - Google Chrome")
    assert tv.tv_like_title("Supercharts — TradingView - Microsoft Edge")
    assert tv.tv_like_title("BTCUSDT chart - Google Chrome", "BTCUSDT")
    assert not tv.tv_like_title("Inbox (3) - Gmail - Google Chrome", "BTCUSDT")
    sc = manual()
    assert tv.is_tradingview_page(_ocr("ru.tradingview.com/chart/EAx2S11D"), sc)
    assert tv.is_tradingview_page(_ocr(f"ID {sc.id}"), sc)
    assert not tv.is_tradingview_page(_ocr("Inbox", "BTCUSDT 76 100"), sc)


# ------------------------------------------------------------------------------------------------ vizual dalil va holat
def _ocr(*texts):
    return [(t, 0.3) for t in texts]


def test_ocr_evaluation_requires_full_evidence_not_window_title():
    sc = manual()
    full = _ocr("BTCUSDT", tv.DISCLAIMER, "ID BTC-SHORT-20261106-01", "SIM ENTRY 76600", "SIM SL 77500", "SIM TP1 75250",
                "SIM TP2 74400", tv.MATCH_TEXT)
    ev = tv.evaluate(full, sc)
    assert ev["confirmed"] and tv.chart_status(True, "ready", ev) == "SUCCESS"
    title_only = tv.evaluate(_ocr("BTCUSDT 76 147,80"), sc)  # faqat sarlavha — dalil emas
    assert not title_only["confirmed"] and "chart_match" in title_only["missing"]
    assert tv.chart_status(True, "ready", title_only) == "PARTIAL"
    wrong = tv.evaluate(full[:-1] + _ocr("WRONG CHART: expected BTCUSDT 60"), sc)
    assert wrong["wrong_chart"] and not wrong["confirmed"]
    missing_tp = tv.evaluate([x for x in full if "TP2" not in x[0]], sc)
    assert missing_tp["missing"] == ["SIM TP2 74400"]
    dup = tv.evaluate(full + _ocr("ID BTC-SHORT-20261106-01"), sc)  # indikator ikki marta qo'shilgan
    assert dup["duplicate_indicator"] and not dup["confirmed"]


def test_task_status_reporting_rules():
    assert tv.chart_status(False, "ready", None) == "FAILED"
    assert tv.chart_status(True, "needs_setup", None) == "NEEDS_SETUP"
    assert tv.chart_status(True, "unverified", None) == "PARTIAL"
    assert tv.chart_status(True, "ready", None) == "PARTIAL"  # Pine tayyor — grafik tasdiqlanmagan
    base = dict(mutated=False, verified=True, verify_failed=False, run_code="ok")
    assert decide("SUCCESS", Facts(**base, chart_state="unverified"))[0] == "PARTIAL"
    assert decide("SUCCESS", Facts(**base, chart_state="needs_setup"))[0] == "NEEDS_SETUP"
    assert decide("SUCCESS", Facts(**base, chart_state="invalid"))[0] == "FAILED"
    assert decide("SUCCESS", Facts(**base, chart_state="confirmed")) == ("SUCCESS", None)


def test_blind_gui_input_requires_owner_approval():
    for cmd in ('[System.Windows.Forms.SendKeys]::SendWait("^v")', "python -c \"import pyautogui; pyautogui.click(5,5)\"",
                "$el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()"):
        assert gate.classify_powershell(cmd).level == gate.DANGER, cmd
    assert gate.classify_powershell("Get-Process TradingView | Select MainWindowTitle").level == gate.READ


# ------------------------------------------------------------------------------------------------ tool oqimi
def test_prepare_tool_flow_sets_partial_and_never_success(tmp_path, monkeypatch):
    from agent.config import Config
    from agent.inventory import Inventory
    from agent.journal import Journal
    from agent.redact import Redactor
    from agent.tools import ToolContext, ToolExecutor
    from agent.workspace import ensure_workspace

    monkeypatch.setattr(tv, "environment", lambda device, known=None, *a, **kw: {
        "device": "XS-NB-AUP06", "kind": "local", "computer": "XS-NB-AUP06", "ready": True, "state": "ready",
        "reason": "oyna bor", "installed": True, "install_info": "TV 3.5", "interactive": True, "session_info": "1",
        "window": True, "window_title": "BTCUSDT"})
    clip: list[str] = []
    monkeypatch.setattr(tv, "copy_to_clipboard", lambda text: clip.append(text) or True)
    paths = ensure_workspace(tmp_path / "home")
    inv = Inventory(paths.inventory_json)
    red = Redactor(inv.secret_values)

    class Ch:
        async def send(self, t): pass
        async def send_file(self, p, c=""): pass
        async def ask(self, q): return None
        async def request_approval(self, t): return False
        async def request_secret(self, p): return None

    ctx = ToolContext(task_id="T-TV", cfg=Config(agent_home=paths.home), paths=paths, inventory=inv, redactor=red,
                      journal=Journal(paths.jurnal, red), channel=Ch())
    ex = ToolExecutor()
    out, err = asyncio.run(ex.execute(ctx, "tradingview_prepare", {**BTC, "device": "local"}))
    assert not err and "Holat: PARTIAL" in out and "TASDIQLANMAGAN" in out and "Pine Editor" in out
    assert ctx.chart["state"] == "unverified" and clip and clip[0].startswith("//@version=5")
    out2, _ = asyncio.run(ex.execute(ctx, "tradingview_prepare", {**BTC, "device": "local"}))
    assert "dublikat yo'q" in out2  # qayta chaqiruv — yangi fayl yo'q
    pine_dir = paths.home / "trading_memory" / "pine"
    assert len(list(pine_dir.glob("*.pine"))) == 1
    index = json.loads((pine_dir / "index.json").read_text(encoding="utf-8"))
    assert list(index.values())[0]["scenario"]["entry"] == 76600
    bad, err3 = asyncio.run(ex.execute(ctx, "tradingview_prepare", {**BTC, "sl": 70000, "device": "local"}))
    assert err3 and "FAILED" in bad and ctx.chart["state"] == "invalid"
    # verify: oynadan dalil yo'q -> PARTIAL; to'liq dalil -> SUCCESS
    asyncio.run(ex.execute(ctx, "tradingview_prepare", {**BTC, "device": "local"}))
    shot_dir = paths.home / "trading_memory" / "chart_checks"
    monkeypatch.setattr(tv, "find_windows", lambda target="auto", ticker="": [
        {"hwnd": 1, "title": "BTCUSDT", "kind": "desktop"}])
    monkeypatch.setattr(tv, "capture", lambda h, p: (Path(p).parent.mkdir(parents=True, exist_ok=True) or
                                                     Path(p).write_bytes(b"png") or True, str(p)))
    monkeypatch.setattr(tv, "ocr_items", lambda p: [("BTCUSDT 76 100", 0.1)])
    v1, _ = asyncio.run(ex.execute(ctx, "tradingview_verify", {"scenario_id": BTC["id"], "device": "local"}))
    assert "Holat: PARTIAL" in v1 and ctx.chart["state"] == "unverified"
    sc = manual()
    monkeypatch.setattr(tv, "ocr_items", lambda p: [(t, 0.3) for t in
                        [tv.DISCLAIMER, f"ID {sc.id}", *[title for _, title, _ in sc.levels()], tv.MATCH_TEXT]])
    v2, _ = asyncio.run(ex.execute(ctx, "tradingview_verify", {"scenario_id": BTC["id"], "device": "local"}))
    assert "Holat: SUCCESS" in v2 and ctx.chart["state"] == "confirmed"
    assert list(shot_dir.glob("*.png"))
    # Desktop boshqa grafikda (XAUUSD), indikator Chrome'dagi to'g'ri grafikda; uchinchi brauzer oynasi — begona sahifa
    for f in shot_dir.glob("*.png"):
        f.unlink()
    wins = [{"hwnd": 1, "title": "XAUUSD 4 059", "kind": "desktop"},
            {"hwnd": 2, "title": "BTCUSDT 76 100 ▼ Unnamed - Google Chrome", "kind": "browser"},
            {"hwnd": 3, "title": "BTCUSDT news - Google Chrome", "kind": "browser"}]
    monkeypatch.setattr(tv, "find_windows", lambda target="auto", ticker="": [
        w for w in wins if target == "auto" or w["kind"] == target])
    full = [tv.DISCLAIMER, f"ID {sc.id}", *[title for _, title, _ in sc.levels()], tv.MATCH_TEXT,
            "ru.tradingview.com/chart"]
    by_window = {"desktop1": ["XAUUSD 4 059,45"], "browser2": full, "browser3": ["BTCUSDT news", "Inbox"]}
    monkeypatch.setattr(tv, "ocr_items", lambda p: [(t, 0.3) for t in by_window[Path(p).stem.rsplit("_", 1)[1]]])
    v3, _ = asyncio.run(ex.execute(ctx, "tradingview_verify", {"scenario_id": BTC["id"], "device": "local"}))
    assert "Holat: SUCCESS" in v3 and "brauzer (faol yorliq): TASDIQLANDI" in v3
    assert "TradingView sahifasi emas" in v3 and "XAUUSD" not in v3
    assert sorted(f.stem.rsplit("_", 1)[1] for f in shot_dir.glob("*.png")) == ["browser2", "desktop1"]
    # indikator noto'g'ri grafikda (BTCUSD) — WRONG CHART, to'g'ri grafik havolasi beriladi
    by_window["browser2"] = [x for x in full if x != tv.MATCH_TEXT] + ["WRONG CHART: expected BTCUSDT 60", "BTCUSD"]
    v4, _ = asyncio.run(ex.execute(ctx, "tradingview_verify", {"scenario_id": BTC["id"], "device": "local",
                                                               "window": "browser"}))
    assert "Holat: PARTIAL" in v4 and "WRONG CHART ko'rindi" in v4 and sc.chart_url() in v4
    assert ctx.chart["state"] == "unverified"


def test_dataclass_roundtrip_for_store_entries(tmp_path):
    sc = manual()
    store = tv.PineStore(tmp_path)
    store.save(sc, tv.generate(sc), tv.validate_pine(tv.generate(sc), sc))
    again = tv.Scenario(**store.find(sc.id)["scenario"])
    assert again == sc and replace(again, entry=1.0) != sc
