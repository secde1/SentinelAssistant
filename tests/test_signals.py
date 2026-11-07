"""V22 signal tizimi: ball, xabar formati, callback tugmalar (faqat egasi, bir marta), dublikat himoyasi, paper pozitsiya,
muddat/bekor bo'lish, Telegram xatolari. Sintetik ma'lumot va soxta Telegram bilan (tarmoq, MT5 va real order YO'Q)."""
from __future__ import annotations

import ast
import asyncio
import inspect
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from test_trading import candles_from, make_service

from agent.telegram_api import TelegramError, TelegramNetworkError
from agent.trading import signal_score as ss
from agent.trading import signals as sg
from agent.trading.data import Candle
from agent.trading.indicators import Features

OWNER, STRANGER, GROUP = 871134228, 555, -5588340884
NOW = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)  # dushanba, 1H sham chegarasida
H, H4, M15 = 3600, 4 * 3600, 900


def trend_closes(n: int, up: bool = True, slope: float = 0.5) -> list[float]:
    s = 1 if up else -1
    return [200 + s * slope * t + 5.0 * math.sin(t / 6) for t in range(n)]  # swing nuqtalari bor trend


def feats(closes, sec=H, vol=100.0):
    cs = candles_from(closes, sec=sec, start=NOW - timedelta(seconds=sec * len(closes)))
    if vol != 100.0:
        cs = [Candle(c.ts, c.open, c.high, c.low, c.close, vol, c.seconds) for c in cs]
    return Features.build(cs)


# ------------------------------------------------------------------------------------------------ ball
def test_macd_hist_sign_follows_trend():
    up = ss.macd_hist([100 + 0.02 * t * t for t in range(120)])  # tezlashayotgan o'sish -> gistogramma > 0
    dn = ss.macd_hist([100 - 0.005 * t * t for t in range(120)])  # tezlashayotgan pasayish -> gistogramma < 0
    assert up[-1] > 0 > dn[-1]
    assert math.isnan(up[0]) and not math.isnan(up[-1])


@pytest.mark.parametrize("score,ok,blocked,tier", [
    (3, {}, None, "DROP"), (0, {}, None, "DROP"), (4, {}, None, "WATCH"), (5, {}, None, "WATCH"),
    (6, {"h4_trend": True, "h1_trend": True, "volume": True, "rr": True}, None, "CONFIRM"),
    (7, {"h4_trend": True, "h1_trend": True, "volume": False, "rr": True}, None, "WATCH"),  # qo'shimcha tasdiq yo'q
    (7, {"h4_trend": True, "h1_trend": True, "volume": True, "rr": True}, None, "CONFIRM"),
    (8, {}, None, "STRONG"), (10, {}, None, "STRONG"), (9, {}, "ma'lumot yo'q", "BLOCKED")])
def test_tier_boundaries(score, ok, blocked, tier):
    assert ss.tier_of(score, ok, blocked) == tier


def test_evaluate_long_in_uptrend_checks_every_criterion_from_data():
    f = feats(trend_closes(320))
    price = f.close[-1]
    sc = ss.evaluate(True, f, f, f, entry=price, sl=price - 3, tp=price + 6, rr_net=1.9, min_rr=1.5)
    by = {i.key: i for i in sc.items}
    assert len(sc.items) == 10 and sc.tier != "BLOCKED" and not sc.missing
    assert by["h4_trend"].ok and by["h1_trend"].ok and by["m15_ema"].ok and by["rr"].ok
    hist = ss.macd_hist(f.close)  # MACD mezoni haqiqatan hisoblangan gistogrammaga mos
    assert by["macd"].ok == (hist[-1] > 0 and hist[-1] >= hist[-2])
    assert "ADX" in by["h4_trend"].detail and "RSI14" in by["rsi"].detail and "EMA20" in by["m15_ema"].detail
    assert sc.score == sum(1 for i in sc.items if i.ok)  # ball = haqiqatan o'tgan mezonlar soni, boshqa narsa emas


def test_h4_trend_opposite_blocks_signal_regardless_of_score():
    f = feats(trend_closes(320))
    price = f.close[-1]
    sc = ss.evaluate(False, f, f, f, entry=price, sl=price + 3, tp=price - 6, rr_net=2.0, min_rr=1.5)
    assert sc.tier == "BLOCKED" and "4H trend signalga teskari" in sc.blocked


def test_missing_data_blocks_and_is_never_invented():
    short = feats(trend_closes(120))  # EMA200/ADX uchun yetarli emas
    sc = ss.evaluate(True, short, short, short, entry=100, sl=98, tp=104, rr_net=2.0, min_rr=1.5)
    assert sc.tier == "BLOCKED" and "ma'lumot yetarli emas" in sc.blocked
    assert "h4_trend" in sc.missing and sc.get("h4_trend").ok is None


def test_volume_uses_average_and_reports_tick_label():
    f = feats(trend_closes(320))
    cs = list(f.candles)
    cs[-1] = Candle(cs[-1].ts, cs[-1].open, cs[-1].high, cs[-1].low, cs[-1].close, 300.0, H)
    f2 = Features.build(cs)
    price = f2.close[-1]
    hi = ss.evaluate(True, f2, f2, f2, entry=price, sl=price - 3, tp=price + 6, rr_net=2, min_rr=1.5, volume_kind="tick")
    assert hi.get("volume").ok and "tick hajm" in hi.get("volume").detail and "3.00x" in hi.get("volume").detail
    zero = feats(trend_closes(320), vol=0.0)
    no = ss.evaluate(True, zero, zero, zero, entry=price, sl=price - 3, tp=price + 6, rr_net=2, min_rr=1.5)
    assert no.get("volume").ok is None and "volume" in no.missing and no.tier == "BLOCKED"


def test_rr_below_minimum_fails_criterion():
    f = feats(trend_closes(320))
    price = f.close[-1]
    sc = ss.evaluate(True, f, f, f, entry=price, sl=price - 3, tp=price + 3.3, rr_net=1.1, min_rr=1.5)
    assert sc.get("rr").ok is False


# ------------------------------------------------------------------------------------------------ format va tugmalar
def test_callback_format_and_length():
    d = sg.callback_data("confirm", "SIG-20261109-0001")
    assert d == "sentinel:confirm:SIG-20261109-0001" and len(d.encode()) <= 64
    assert sg.parse_callback(d) == ("confirm", "SIG-20261109-0001")
    assert sg.parse_callback("sentinel:reject:X") == ("reject", "X")
    for bad in ("ap:1:y", "sentinel:buy:X", "sentinel:confirm:", "sentinel:confirm", "", None, "sentinel:confirm:a:b"):
        assert sg.parse_callback(bad) is None


def test_keyboard_uses_callback_data_only_no_url():
    kb = sg.keyboard("SIG-20261109-0001", "SHORT")
    row = kb["inline_keyboard"][0]
    assert [b["text"] for b in row] == ["✅ HA — SELL", "❌ YO'Q"]
    assert all("url" not in b and b["callback_data"].startswith("sentinel:") for b in row)
    assert sg.keyboard("S", "LONG")["inline_keyboard"][0][0]["text"] == "✅ HA — BUY"


# ------------------------------------------------------------------------------------------------ servis
class Tg:
    """Soxta Telegram: yuborilgan va tahrirlangan xabarlar."""

    def __init__(self):
        self.sent, self.edits, self.fail = [], [], None
        self.n = 100

    async def send(self, chat, text, markup, reply_to):
        if self.fail:
            raise self.fail
        self.n += 1
        self.sent.append({"chat": chat, "text": text, "markup": markup, "reply_to": reply_to, "id": self.n})
        return {"message_id": self.n}

    async def edit(self, chat, mid, text):
        self.edits.append((chat, mid, text))


def price_series(now, sec, closes, symbol="BTCUSDT"):
    start = now - timedelta(seconds=sec * len(closes))
    return candles_from(closes, sec=sec, start=start)


def make_signal_service(tmp_path, mode="live", closes_15m=None, now=NOW, extra_series=None):
    h1 = trend_closes(320)
    series = {("BTCUSDT", "1h"): price_series(now, H, h1), ("BTCUSDT", "4h"): price_series(now, H4, h1),
              ("BTCUSDT", "15m"): price_series(now, M15, closes_15m or ([h1[-1]] * 320))}
    series.update(extra_series or {})
    svc = make_service(tmp_path / "h", series, now)
    svc.settings.data["group_chat_id"] = GROUP
    svc.settings.data["signals"] = {"mode": mode, "scan_sec": 900, "cooldown_h": 4, "tolerance_atr": 1.0,
                                    "universe": ["BTCUSDT"]}
    tg = Tg()
    return svc, sg.SignalService(svc, tg.send, tg.edit, OWNER), tg


def cand(svc, tier="STRONG", score=8, direction="LONG", entry=None, sl=None, tp=None, valid_h=6, symbol="BTCUSDT",
         entry_type="buy_stop"):
    last = svc.market.history(symbol, "1h", 50, need=30).candles[-1].close
    entry = entry if entry is not None else last
    long = direction == "LONG"
    sl = sl if sl is not None else (entry - 5 if long else entry + 5)
    tp = tp if tp is not None else (entry + 10 if long else entry - 10)
    items = [ss.Item(k, k, True if n < score else False, f"{k} detail") for n, k in enumerate(
        ("h4_trend", "h1_trend", "m15_ema", "rsi", "macd", "sr", "breakout", "volume", "structure", "rr"))]
    sc = ss.Score(score, items, tier)
    inv = {"type": "close_below" if long else "close_above", "level": sl, "text": "yopilish SL ortida"}
    return sg.Candidate(symbol, "1h", direction, "TF-PULLBACK", 1, entry_type, entry, sl, tp, 2.0, 1.9, inv,
                        svc.clock() + timedelta(hours=valid_h), svc.clock(), "synthetic test feed", 0.0, 0.0, sc, {}, "HH+HL")


def run(coro):
    return asyncio.run(coro)


async def sent_signal(svc, sv, **kw):
    c = cand(svc, **kw)
    sig = sv.store(c, svc.clock(), "NEW")
    assert await sv.publish(sig["signal_id"], c)
    return sig["signal_id"]


def row(svc, sid):
    return svc.db.one("SELECT * FROM signals WHERE signal_id=?", (sid,))


def test_publish_stores_everything_and_sends_buttons(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        r = row(svc, sid)
        assert r["status"] == "SENT" and r["message_id"] == 101 and r["chat_id"] == GROUP
        assert r["entry"] and r["sl"] and r["tp"] and r["score"] == 8 and r["tier"] == "STRONG" and r["created_at"]
        assert json.loads(r["analysis"])["items"][0]["key"] == "h4_trend"  # tahlil natijalari saqlanadi
        m = tg.sent[0]
        assert m["chat"] == GROUP and m["markup"]["inline_keyboard"][0][0]["callback_data"] == f"sentinel:confirm:{sid}"
        t = m["text"]
        for need in ("🚨 SENTINEL | STRONG SIGNAL", "💎 Symbol: BTCUSDT", "📊 Direction: BUY", "⭐ Score: 8/10", "ENTRY:",
                     "STOP LOSS:", "TAKE PROFIT 1:", "📈 MARKET ANALYSIS:", "🎯 SIGNAL REASONS:", "⚠️ INVALIDATION:",
                     "🕒 Time: UTC+5", "📡 Source: real market data", sid, "PAPER"):
            assert need in t, need
        assert "TAKE PROFIT 2" not in t and "TAKE PROFIT 3" not in t  # hisoblanmagan TP yozilmaydi
        assert "g'alaba ehtimoli emas" in t and "foyda kafolatlanmaydi" in t
    run(go())


def test_owner_confirm_opens_paper_position_only(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "PAPER" in ans
        r = row(svc, sid)
        assert r["status"] == "CONFIRMED" and r["decided_by"] == OWNER
        p = svc.db.one("SELECT * FROM paper_positions WHERE signal_id=?", (sid,))
        assert p["status"] == "PENDING" and p["entry_signal"] == r["entry"] and p["sl"] == r["sl"] and p["tp"] == r["tp"]
        assert p["confirmed_at"] and p["symbol"] == "BTCUSDT" and p["direction"] == "LONG"
        chat, mid, text = tg.edits[-1]
        assert (chat, mid) == (GROUP, 101) and "TASDIQLANDI" in text and "real order emas" in text
    run(go())


def test_reject_opens_nothing_and_marks_rejected(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        assert "Rad etildi" in await sv.handle_callback(f"sentinel:reject:{sid}", OWNER, GROUP)
        assert row(svc, sid)["status"] == "REJECTED"
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 0
        assert "RAD ETILDI" in tg.edits[-1][2]
        assert "Allaqachon rad etilgan" in await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 0
    run(go())


def test_double_press_is_blocked(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "Allaqachon tasdiqlangan" in await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "Allaqachon tasdiqlangan" in await sv.handle_callback(f"sentinel:reject:{sid}", OWNER, GROUP)
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 1
        assert row(svc, sid)["status"] == "CONFIRMED"
    run(go())


def test_simultaneous_presses_only_one_wins(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        res = await asyncio.gather(sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP),
                                   sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP),
                                   sv.handle_callback(f"sentinel:reject:{sid}", OWNER, GROUP))
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] <= 1
        final = row(svc, sid)["status"]
        assert final in ("CONFIRMED", "REJECTED")
        assert (svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 1) == (final == "CONFIRMED")
        assert sum(1 for r in res if r.startswith(("Tasdiqlandi", "Rad etildi"))) == 1
    run(go())


def test_other_group_member_cannot_decide(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        for action in ("confirm", "reject"):
            assert "Faqat egasi" in await sv.handle_callback(f"sentinel:{action}:{sid}", STRANGER, GROUP)
        assert "Faqat egasi" in await sv.handle_callback(f"sentinel:confirm:{sid}", None, GROUP)
        assert row(svc, sid)["status"] == "SENT" and not tg.edits
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 0
        assert svc.db.one("SELECT COUNT(*) n FROM signal_events WHERE kind='denied'")["n"] == 3
        # keyin egasi hali tasdiqlay oladi
        assert "PAPER" in await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
    run(go())


def test_owner_in_wrong_chat_is_refused(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        assert "guruhda" in await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, -100999)
        assert "guruhda" in await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, OWNER)
        assert row(svc, sid)["status"] == "SENT"
    run(go())


def test_unknown_and_malformed_callbacks(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)

    async def go():
        assert await sv.handle_callback("sentinel:confirm:SIG-NOPE", OWNER, GROUP) == "Signal topilmadi"
        assert await sv.handle_callback("garbage", OWNER, GROUP) == "Noto'g'ri tugma"
    run(go())


def test_expired_signal_cannot_be_confirmed(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv, valid_h=1)
        svc.clock.now = NOW + timedelta(hours=2)
        assert "Muddati o'tgan" in await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert row(svc, sid)["status"] == "EXPIRED" and "MUDDATI O'TDI" in tg.edits[-1][2]
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 0
    run(go())


def test_price_moved_far_from_entry_is_refused(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
        sid = await sent_signal(svc, sv, entry=last - 50, sl=last - 55, tp=last - 40)  # narx kirishdan ancha uzoqda
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert "ancha o'zgargan" in ans or "SL" in ans or "TP" in ans
        assert row(svc, sid)["status"] == "INVALIDATED"
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 0
        assert "BEKOR BO'LDI" in tg.edits[-1][2]
    run(go())


def test_price_already_past_sl_or_tp_is_refused(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)

    async def go():
        last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
        sl_case = await sent_signal(svc, sv, entry=last + 1, sl=last + 0.5, tp=last + 9, symbol="BTCUSDT")
        assert "SL" in await sv.handle_callback(f"sentinel:confirm:{sl_case}", OWNER, GROUP)
        assert row(svc, sl_case)["status"] == "INVALIDATED"
    run(go())


def test_revalidation_with_stale_data_refuses(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        svc.clock.now = NOW + timedelta(hours=5, minutes=30)  # ma'lumot eskirgan (15m ortda qolgan)
        svc.settings.data["signals"]["tolerance_atr"] = 1.0
        ans = await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        assert ans.startswith(("Tasdiqlanmadi", "Muddati")) and row(svc, sid)["status"] in ("INVALIDATED", "EXPIRED")
        assert svc.db.one("SELECT COUNT(*) n FROM paper_positions")["n"] == 0
    run(go())


# ------------------------------------------------------------------------------------------------ dublikat va rejimlar
def test_active_signal_blocks_duplicate_and_cooldown(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv)
        c = cand(svc)
        assert "hali faol" in sv._duplicate(c, svc.clock())
        await sv.handle_callback(f"sentinel:reject:{sid}", OWNER, GROUP)
        assert "cooldown" in sv._duplicate(c, svc.clock())  # rad etilgan bo'lsa ham 4 soat ichida qayta yuborilmaydi
        assert sv._duplicate(c, svc.clock() + timedelta(hours=5)) is None
        assert sv._duplicate(cand(svc, direction="SHORT"), svc.clock()) is None  # teskari yo'nalish — boshqa signal
    run(go())


def test_scan_once_modes(tmp_path, monkeypatch):
    svc, sv, tg = make_signal_service(tmp_path, mode="off")
    strong = cand(svc)
    monkeypatch.setattr(sv, "scan_symbol", lambda s: strong)

    async def go():
        assert (await sv.scan_once())["scanned"] == 0 and not tg.sent  # off
        svc.settings.data["signals"]["mode"] = "dry"
        r = await sv.scan_once()
        assert r["dry"] == 1 and not tg.sent and row(svc, "SIG-20261109-0001")["status"] == "DRY"
        svc.settings.data["signals"]["mode"] = "live"
        r = await sv.scan_once()
        assert r["sent"] == 1 and len(tg.sent) == 1  # dry yozuvi dublikat hisoblanmaydi
        r = await sv.scan_once()
        assert r["duplicate"] == 1 and r["sent"] == 0 and len(tg.sent) == 1  # takror yuborilmaydi
    run(go())


def test_weak_and_blocked_signals_are_not_sent(tmp_path, monkeypatch):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        for tier, key in (("DROP", "dropped"), ("BLOCKED", "blocked"), ("WATCH", "watch")):
            monkeypatch.setattr(sv, "scan_symbol", lambda s, t=tier: cand(svc, tier=t, score=4))
            r = await sv.scan_once()
            assert r[key] == 1 and r["sent"] == 0
        assert not tg.sent
        statuses = [r["status"] for r in svc.db.query("SELECT status FROM signals")]
        assert statuses == ["WATCH"]  # faqat kuzatuv ro'yxati yoziladi; DROP/BLOCKED — baza ham to'lmaydi
    run(go())


def test_scan_handles_missing_data_and_unconfigured_provider(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)
    svc.settings.data["signals"]["universe"] = ["BTCUSDT", "ETHUSDT", "XAU/USD"]  # ETH: ma'lumot yo'q, XAU: mt5 sozlanmagan

    async def go():
        r = await sv.scan_once()
        assert r["data_unavailable"] >= 2 and r["sent"] == 0
        assert any("XAU/USD" in e for e in r["errors"]) and any("ETHUSDT" in e for e in r["errors"])
    run(go())


def test_real_scan_pipeline_on_synthetic_uptrend(tmp_path):
    """Haqiqiy skaner yo'li: strategiya -> ball -> daraja. Signal chiqsa ham, chiqmasa ham — xato bermasligi va mantiqi."""
    svc, sv, tg = make_signal_service(tmp_path, mode="dry")

    async def go():
        r = await sv.scan_once()
        assert r["scanned"] == 1 and not r["errors"] and not tg.sent
        for s in svc.db.query("SELECT * FROM signals"):
            a = json.loads(s["analysis"])
            assert len(a["items"]) == 10 and s["status"] in ("DRY", "WATCH")
    run(go())


def test_telegram_failures_do_not_duplicate(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        tg.fail = TelegramError("Bad Request: chat not found")
        c = cand(svc)
        s1 = sv.store(c, svc.clock(), "NEW")
        assert not await sv.publish(s1["signal_id"], c) and row(svc, s1["signal_id"])["status"] == "FAILED"
        tg.fail = TelegramNetworkError("ReadError")
        c2 = cand(svc, direction="SHORT")
        s2 = sv.store(c2, svc.clock(), "NEW")
        assert not await sv.publish(s2["signal_id"], c2) and row(svc, s2["signal_id"])["status"] == "UNKNOWN"
        tg.fail = None
        assert not await sv.publish(s2["signal_id"], c2)  # noma'lum holat qayta yuborilmaydi
        assert not tg.sent
    run(go())


def test_publish_requires_authorized_group(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)
    svc.settings.data["group_chat_id"] = None

    async def go():
        c = cand(svc)
        s = sv.store(c, svc.clock(), "NEW")
        assert not await sv.publish(s["signal_id"], c) and not tg.sent and row(svc, s["signal_id"])["status"] == "NEW"
    run(go())


# ------------------------------------------------------------------------------------------------ kuzatuv va paper natija
def test_paper_position_tracks_to_tp_and_notifies_once(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
        sid = await sent_signal(svc, sv, entry=last + 0.2, sl=last - 6, tp=last + 8)
        await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        p = svc.db.one("SELECT * FROM paper_positions WHERE signal_id=?", (sid,))
        start = datetime.fromisoformat(p["data_end"])
        # tasdiqdan keyingi 15M shamlar: 1-sham kirishga tegadi, keyin TP
        bars = [Candle(start, last, last + 0.5, last - 0.5, last + 0.3, 1, M15),
                Candle(start + timedelta(seconds=M15), last + 0.3, last + 4, last, last + 3, 1, M15),
                Candle(start + timedelta(seconds=2 * M15), last + 3, last + 9, last + 2, last + 8.5, 1, M15)]
        svc.market.providers["binance"].series[("BTCUSDT", "15m")] += bars
        svc.clock.now = start + timedelta(seconds=3 * M15 + 5)
        n = await sv.track()
        p = svc.db.one("SELECT * FROM paper_positions WHERE signal_id=?", (sid,))
        assert p["status"] == "TP_HIT" and p["r_multiple"] > 0 and p["entry_price"] and p["exit_price"] == pytest.approx(last + 8)
        replies = [m for m in tg.sent if m["reply_to"] == 101]
        assert n >= 1 and len(replies) == 1 and "virtual TP" in replies[0]["text"] and "real order yo'q" in replies[0]["text"]
        await sv.track()
        assert len([m for m in tg.sent if m["reply_to"] == 101]) == 1  # ikkinchi marta xabar yuborilmaydi
        st = sv.stats()
        assert st["closed"] == 1 and st["total_r"] > 0 and st["signals"]["CONFIRMED"] == 1
    run(go())


def test_paper_position_sl_hit_is_recorded_honestly(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
        sid = await sent_signal(svc, sv, entry=last + 0.2, sl=last - 3, tp=last + 8)
        await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        start = datetime.fromisoformat(svc.db.one("SELECT data_end FROM paper_positions")["data_end"])
        bars = [Candle(start, last, last + 0.5, last - 0.5, last + 0.3, 1, M15),
                Candle(start + timedelta(seconds=M15), last + 0.3, last + 0.4, last - 5, last - 4, 1, M15)]
        svc.market.providers["binance"].series[("BTCUSDT", "15m")] += bars
        svc.clock.now = start + timedelta(seconds=2 * M15 + 5)
        await sv.track()
        p = svc.db.one("SELECT * FROM paper_positions")
        assert p["status"] == "SL_HIT" and p["r_multiple"] < 0
        assert "virtual SL" in [m for m in tg.sent if m["reply_to"] == 101][0]["text"]
    run(go())


def test_unconfirmed_signal_expires_with_message(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        sid = await sent_signal(svc, sv, valid_h=1)
        svc.clock.now = NOW + timedelta(hours=2)
        assert await sv.track() >= 1
        assert row(svc, sid)["status"] == "EXPIRED" and "MUDDATI O'TDI" in tg.edits[-1][2]
        assert any("bekor bo'ldi" in m["text"] and m["reply_to"] == 101 for m in tg.sent)
        n = len(tg.sent)
        await sv.track()
        assert len(tg.sent) == n  # qayta xabar yo'q
    run(go())


def test_sent_signal_invalidated_when_price_breaks_invalidation_level(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
        sid = await sent_signal(svc, sv, entry=last + 1, sl=last - 2, tp=last + 8)
        bars = [Candle(NOW, last, last + 0.1, last - 6, last - 5, 1, M15)]
        svc.market.providers["binance"].series[("BTCUSDT", "15m")] += bars
        svc.clock.now = NOW + timedelta(seconds=M15 + 5)
        await sv.track()
        assert row(svc, sid)["status"] == "INVALIDATED"
        assert any("bekor bo'ldi" in m["text"] for m in tg.sent)
    run(go())


def test_trend_reversal_warning_sent_once_for_open_position(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        last = svc.market.history("BTCUSDT", "15m", 5, need=3).candles[-1].close
        sid = await sent_signal(svc, sv, entry=last + 0.5, sl=last - 6, tp=last + 12)
        await sv.handle_callback(f"sentinel:confirm:{sid}", OWNER, GROUP)
        down = price_series(NOW, H4, trend_closes(320, up=False))
        svc.market.providers["binance"].series[("BTCUSDT", "4h")] = down
        await sv.track()
        warn = [m for m in tg.sent if "4H trend teskariga" in m["text"]]
        assert len(warn) == 1 and warn[0]["reply_to"] == 101
        await sv.track()
        assert len([m for m in tg.sent if "4H trend teskariga" in m["text"]]) == 1
    run(go())


def test_stats_empty_and_filled(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)
    assert sv.stats() == {"signals": {}, "paper": {}, "closed": 0, "total_r": 0.0, "avg_r": None}


# ------------------------------------------------------------------------------------------------ bot, sozlama, xavfsizlik
def test_bot_signal_callback_answers_always_and_blocks_strangers(tmp_path):
    from agent.bot import TelegramBot
    svc, sv, _ = make_signal_service(tmp_path)
    answers = []

    class Api:
        async def answer_callback(self, cid, text=""):
            answers.append((cid, text))

    class Journal:
        def event(self, *a, **k):
            pass
    bot = TelegramBot.__new__(TelegramBot)
    bot.api, bot.signals, bot.journal = Api(), sv, Journal()

    async def go():
        sid = await sent_signal(svc, sv)
        cq = {"id": "c1", "data": f"sentinel:confirm:{sid}", "from": {"id": STRANGER}, "message": {"chat": {"id": GROUP}}}
        await bot._on_callback(cq)
        assert answers[-1] == ("c1", "Faqat egasi tasdiqlay oladi") and row(svc, sid)["status"] == "SENT"
        cq["from"], cq["id"] = {"id": OWNER}, "c2"
        await bot._on_callback(cq)
        assert "PAPER" in answers[-1][1] and row(svc, sid)["status"] == "CONFIRMED"
        bot.signals = None
        await bot._on_callback({"id": "c3", "data": "sentinel:confirm:X", "from": {"id": OWNER}, "message": {"chat": {"id": GROUP}}})
        assert answers[-1] == ("c3", "Signal tizimi o'chiq")

        async def boom(*a):
            raise RuntimeError("test xatosi")
        bot.signals = SimpleNamespace(handle_callback=boom)
        await bot._on_callback({"id": "c4", "data": "sentinel:confirm:X", "from": {"id": OWNER}, "message": {"chat": {"id": GROUP}}})
        assert "Xatolik" in answers[-1][1]  # xato bo'lsa ham tugma "osilib qolmaydi"
    run(go())


def test_old_approval_buttons_still_use_owner_chat_check(tmp_path):
    """Mavjud 'ap:' tugmalari o'zgarmagan: guruhdan kelgan ap: tugmasi rad etiladi."""
    from agent.bot import TelegramBot
    answers = []

    class Api:
        async def answer_callback(self, cid, text=""):
            answers.append(text)

    class Journal:
        events = []

        def event(self, kind, *a, **k):
            Journal.events.append(kind)
    bot = TelegramBot.__new__(TelegramBot)
    bot.api, bot.journal = Api(), Journal()
    bot.cfg = SimpleNamespace(allowed_chat_id=OWNER, allowed_user_id=OWNER)
    run(bot._on_callback({"id": "c", "data": "ap:xyz:y", "from": {"id": OWNER}, "message": {"chat": {"id": GROUP}}}))
    assert "unauthorized" in Journal.events and not answers


def test_research_analysis_posts_are_suppressed_but_stored(tmp_path):
    svc, sv, tg = make_signal_service(tmp_path)
    from agent.trading.publish import Publisher

    async def send(chat, text, reply_to):
        tg.sent.append(text)
        return {"message_id": 1}
    pub = Publisher(svc.db, svc.settings, send, clock=svc.clock)
    svc.settings.data["publish"]["analyses"] = False  # jonli sozlamada shunday (V22: guruhga faqat signal)
    rec = svc.create_analysis("BTCUSDT", "1h")
    assert run(pub.publish_analysis(rec)) == "disabled" and not tg.sent
    assert svc.db.analysis(rec["analysis_id"])  # bazada saqlangan
    svc.settings.data["publish"]["analyses"] = True
    assert run(pub.publish_analysis(rec)) in ("sent", "stale")


def test_forex_provider_migrates_to_mt5_only_without_twelvedata(tmp_path):
    svc, _, _ = make_signal_service(tmp_path)
    prov = {"binance": object(), "mt5": object()}
    assert svc.settings.instrument("XAU/USD")["provider"] == "twelvedata"
    svc._migrate_forex_provider({**prov, "twelvedata": object()})
    assert svc.settings.instrument("XAU/USD")["provider"] == "twelvedata"  # kalit bor — o'zgarmaydi
    svc._migrate_forex_provider(prov)
    assert svc.settings.instrument("XAU/USD")["provider"] == "mt5" and svc.settings.instrument("EUR/USD")["provider"] == "mt5"
    assert svc.settings.instrument("BTCUSDT")["provider"] == "binance"


def test_signal_module_has_no_order_calls_or_broker_access():
    src = inspect.getsource(sg) + inspect.getsource(ss)
    tree = ast.parse(src)
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    forbidden = {"order_send", "order_check", "positions_get", "OrderSend", "mt5_trader", "DemoTrader", "create_order"}
    assert not names & forbidden
    assert "MetaTrader5" not in src and "bot_env" not in src and "token" not in src.lower()


def test_signal_ids_are_unique_and_sequential(tmp_path):
    svc, sv, _ = make_signal_service(tmp_path)
    ids = [sv.store(cand(svc), svc.clock(), "WATCH")["signal_id"] for _ in range(3)]
    assert ids == ["SIG-20261109-0001", "SIG-20261109-0002", "SIG-20261109-0003"]


# ------------------------------------------------------------------------------------------------ test signal (tugma sinovi)
def test_send_test_uses_real_setup_marks_test_and_is_excluded_from_stats(tmp_path, monkeypatch):
    svc, sv, tg = make_signal_service(tmp_path)

    async def go():
        monkeypatch.setattr(sv, "scan_symbol", lambda s: None)  # setup yo'q -> hech narsa to'qilmaydi
        assert "haqiqiy setup yo'q" in await sv.send_test() and not tg.sent
        monkeypatch.setattr(sv, "scan_symbol", lambda s: cand(svc, tier="WATCH", score=6))
        msg = await sv.send_test("BTCUSDT")
        assert "TST-20261109-0001" in msg
        assert tg.sent[0]["text"].startswith("🧪 TEST — bu real signal EMAS")
        assert tg.sent[0]["markup"]["inline_keyboard"][0][0]["callback_data"] == "sentinel:confirm:TST-20261109-0001"
        assert "PAPER" in await sv.handle_callback("sentinel:confirm:TST-20261109-0001", OWNER, GROUP)
        assert svc.db.one("SELECT status FROM paper_positions")["status"] == "PENDING"
        assert sv.stats() == {"signals": {}, "paper": {}, "closed": 0, "total_r": 0.0, "avg_r": None}  # statistikaga kirmaydi
        # haqiqiy signal dublikat hisobida TEST ni e'tiborga olmaydi
        assert sv._duplicate(cand(svc), svc.clock()) is None
    run(go())
