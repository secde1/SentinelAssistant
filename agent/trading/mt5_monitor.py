"""MT5 pozitsiyalarini kuzatish va Telegram xabarlari (V24). FAQAT O'QISH: pozitsiya ochilmaydi, o'zgartirilmaydi, yopilmaydi.

Nima kuzatiladi (har ~60 s): ochiq pozitsiyalar (yangi / SL-TP o'zgargan) va yopilganlar. Yopilish xabari FAQAT MT5 bitim tarixida
OUT bitimi tasdiqlangandan keyin yuboriladi; sabab bitimning `reason` maydonidan (SL, TP, CLIENT=qo'lda, EXPERT, STOP_OUT ...).
POSITION_ID — pozitsiyani, DEAL — bitimlarni (IN/OUT), ORDER — buyurtmani bildiradi: bozor buyrug'ida IN bitimning order
raqami = position_id; SL/TP bilan yopilganda OUT bitimda order=0 (server yopgan), qo'lda yopilsa — alohida order raqami.

Xabarlar yo'qolmasligi uchun bazada navbat (notifications): har xabarning yagona kaliti (opened:<id>, closed:<id> ...) bor, bir kalit
ikki marta yuborilmaydi (UNIQUE). Telegram ishlamasa — qayta urinish (30 s, 2, 10, 30, 60 daqiqa...). Faqat natijasi noma'lum
(tarmoq o'qish xatosi) holatda qayta yuboriladi va xabarga "↻" belgisi qo'yiladi (yo'qotishdan ko'ra takror afzal).
Yopilgan har savdo uchun avtomatik tahlil data/trading/post_trade_analysis.json ga yoziladi. Bitta savdo asosida strategiya
o'zgartirilmaydi: tahlil faqat gipoteza beradi, xulosa uchun ko'p savdo statistikasi va tarixiy sinov kerak.
"""
from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable

from .data import DataUnavailable
from .mt5_history import fmt_duration, summarize

log = logging.getLogger(__name__)

SENTINAL_MAGIC = 20260711  # mt5_trade.MAGIC (import qilinmaydi: bu modulda buyurtma kodi bo'lmasligi kerak)
BACKOFF = [30, 120, 600, 1800, 3600]
GIVE_UP = timedelta(hours=24)
DISCONNECT_AFTER = 3  # ketma-ket muvaffaqiyatsiz so'rovlar

TITLES = {"SL": ("🔴", "STOP LOSS HIT"), "TP": ("🟢", "TAKE PROFIT HIT"), "STOP_OUT": ("🔴", "STOP OUT (margin)")}
MANUAL = ("CLIENT", "MOBILE", "WEB")


def now_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _px(x: float | None) -> str:
    return "—" if x is None else f"{x:,.5f}".rstrip("0").rstrip(".").replace(",", " ")


def _money(x: float, ccy: str) -> str:
    return f"{x:+.2f} {ccy}"


def private_chat_resolver(settings, owner_chat_id: int) -> Callable[[str], int | None]:
    """Monitoring/tahlil xabarlari FAQAT egasining shaxsiy chatiga. Manzil noto'g'ri bo'lsa (yo'q, guruh, ALLOWED_CHAT_ID ga teng
    emas, guruh manziliga teng) — None: xabar navbatda kutadi, boshqa joyga yo'naltirilmaydi."""
    def chat_for(target: str) -> int | None:
        pid = settings.private_chat_id
        if target != "private" or not pid or pid != owner_chat_id or pid == settings.group_chat_id:
            return None
        return pid
    return chat_for


# -------------------------------------------------------------------------------------------- xabar matnlari
def reason_title(reason: str, net: float) -> tuple[str, str]:
    if reason in TITLES:
        return TITLES[reason]
    if reason in MANUAL:
        return ("🟢" if net > 0 else "🔴" if net < 0 else "⚪"), "MANUAL CLOSE"
    if reason == "EXPERT":
        return ("🟢" if net > 0 else "🔴" if net < 0 else "⚪"), "CLOSED BY EXPERT/BOT"
    return "⚪", f"POSITION CLOSED ({reason})"


def format_opened(p: dict, ccy: str, late: bool, tz) -> str:
    src = "SENTINAL (bot)" if p["magic"] == SENTINAL_MAGIC else "boshqa (qo'lda yoki EA)"
    lines = ["🟦 SENTINEL | POSITION OPENED", "",
             f"Symbol: {p['symbol']}", f"Direction: {p['side']}", f"Volume: {p['volume']:.2f}", "",
             f"Entry: {_px(p['price_open'])}", f"SL: {_px(p['sl']) if p['sl'] else 'YO‘Q ⚠️'}",
             f"TP: {_px(p['tp']) if p['tp'] else '—'}", f"Opened: {p['time'].astimezone(tz):%d.%m %H:%M} (UTC+5)",
             f"Source: {src}", f"Magic: {p['magic']}", "", "📊 STATUS: OPEN"]
    if late:
        lines.append("ℹ️ Monitoring boshlanganda pozitsiya allaqachon ochiq edi.")
    if not p["sl"]:
        lines.append("⚠️ Stop Loss yo'q — risk cheklanmagan.")
    return "\n".join(lines)


def format_modified(p: dict, old: dict) -> str:
    ch = []
    if old["sl"] != p["sl"]:
        ch.append(f"SL: {_px(old['sl'])} → {_px(p['sl'])}")
    if old["tp"] != p["tp"]:
        ch.append(f"TP: {_px(old['tp'])} → {_px(p['tp'])}")
    return "\n".join(["🟡 SENTINEL | POSITION MODIFIED", "", f"Symbol: {p['symbol']}", f"Direction: {p['side']}",
                      f"Position: #{p['ticket']}", *ch, "", "📊 STATUS: OPEN"])


def format_closed(s: dict, ccy: str, analysis: dict | None, tz, late_note: str = "", sl: float | None = None,
                  tp: float | None = None) -> str:
    emoji, title = reason_title(s["reason"], s["net"])
    reason_txt = {"SL": "STOP LOSS", "TP": "TAKE PROFIT", "CLIENT": "MANUAL (terminal)", "MOBILE": "MANUAL (mobil)",
                  "WEB": "MANUAL (veb)", "EXPERT": "EXPERT/BOT (dastur yopdi)", "STOP_OUT": "STOP OUT (margin)"}.get(
        s["reason"], s["reason"])
    lines = [f"{emoji} SENTINEL | {title}", "",
             f"Symbol: {s['symbol']}", f"Direction: {s['direction']}", f"Volume: {s['volume']:.2f}", "",
             f"Entry: {_px(s['entry_price'])}", f"SL: {_px(sl) if sl else '—'}", f"TP: {_px(tp) if tp else '—'}",
             f"Exit: {_px(s['exit_price'])}", "",
             f"Result: {_money(s['net'], ccy)}  (profit {s['profit']:+.2f})", f"Commission: {s['commission']:+.2f} {ccy}",
             f"Swap: {s['swap']:+.2f} {ccy}", "",
             f"Reason: {reason_txt}", f"Duration: {fmt_duration(s['duration_s'])}",
             f"Closed: {s['closed_at'].astimezone(tz):%d.%m %H:%M} (UTC+5)", f"Position: #{s['position_id']}", "",
             "📊 STATUS: CLOSED", "(MT5 bitim tarixida tasdiqlangan)"]
    if analysis:
        lines += ["", "⚠️ Analysis: " + analysis["short"]]
    if late_note:
        lines += ["", late_note]
    return "\n".join(lines)


def format_report(s: dict, a: dict | None, ccy: str, tz) -> str:
    """Yopilgan savdo bo'yicha 8 bandli POST-TRADE REPORT (faqat shaxsiy chatga). Hammasi tahlil natijasidan; to'qilmaydi."""
    emoji, title = reason_title(s["reason"], s["net"])
    v = (a or {}).get("verdict") or {}
    sc = (a or {}).get("score") or {}
    why_sl = {"SL": "narx stop-lossga yetdi", "TP": "narx take-profitga yetdi", "STOP_OUT": "margin yetishmadi (stop-out)"}.get(
        s["reason"], "pozitsiya qo'lda yoki dastur tomonidan yopildi")
    r_txt = f", {a['r_multiple']:+.2f}R" if a and a.get("r_multiple") is not None else ""
    lines = [f"📝 SENTINEL | POST-TRADE REPORT  #{s['position_id']}  ({s['symbol']} {s['direction']})", "",
             f"1) Natija: {emoji} {title}: {_money(s['net'], ccy)}{r_txt}, {fmt_duration(s['duration_s'])}", ""]
    if a is None:
        lines.append("Tahlil hisoblanmadi (ma'lumot yetishmadi) — xulosa chiqarilmaydi.")
        return "\n".join(lines)
    move = ""
    if "mfe_r" in a:
        move = (f" Savdo davomida foyda tomonga eng ko'pi {a['mfe_r']}R (TP ga {a.get('mfe_of_tp', 0) * 100:.0f}%), "
                f"qarshi tomonga {a['mae_r']}R.")
    lines.append(f"2) Nega {s['reason']}: {why_sl}.{move}")
    if sc:
        aligned = any("trendiga mos edi" in x for x in v.get("worked", []))
        wrong = ", ".join(x.split(":")[0] for x in v.get("wrong_indicators", [])[:4])
        lines.append(f"3) Kirish: {sc['score']}/10 (daraja {sc['tier']}). " +
                     ("Yo'nalish 4H va 1H trendga mos." if aligned else "Yo'nalish trendga to'liq mos emas.") +
                     (f" Tasdiqlanmagan: {wrong}." if wrong else ""))
    else:
        lines.append("3) Kirish: ball hisoblanmadi (SL/TP yo'q yoki ma'lumot yetishmadi).")
    sl_txt = (f"SL {a['sl_atr_1h']} ATR(1h) / {a['sl_atr_15m']} ATR(15m)" if a.get("sl_atr_1h") is not None
              else "SL ma'lumoti yo'q")
    sl_notes = "; ".join(x for x in v.get("failed", []) if "SL" in x or "R/R" in x)
    lines.append(f"4) SL/TP: {sl_txt}; R/R {a.get('rr_planned') or '—'}. {sl_notes}")
    lines.append("5) Tasdiq bergan: " + (", ".join(v.get("worked", [])[:6]) or "—"))
    errs = v.get("wrong_indicators", [])[:4] + [x for x in v.get("failed", []) if "SL" not in x and "R/R" not in x][:3]
    lines.append("6) Xato/tasdiqlanmagan: " + ("; ".join(errs) or "aniq xato topilmadi"))
    defects = v.get("failed", [])[:3]
    lines.append("7) Kamchilik: " + ("; ".join(defects) if defects else "aniq kamchilik topilmadi") +
                 f". Namuna: {a['sample'].get('n', '?')} savdo — bitta savdo asosida strategiya o'zgartirilmaydi.")
    lines.append("8) Taklif (GIPOTEZA, avval tarixiy sinov va paper bilan tekshiriladi): " +
                 ("; ".join(v.get("improve", [])) or "yangi taklif yo'q"))
    return "\n".join(lines)[:3800]


# -------------------------------------------------------------------------------------------- savdo tahlili
def _swing_state(f, i: int):
    highs, lows = f.swings(i, lookback=200)
    if len(highs) < 2 or len(lows) < 2:
        return None
    return highs[-1][1] > highs[-2][1], lows[-1][1] > lows[-2][1]


def analyze_trade(s: dict, sl: float | None, tp: float | None, contract: float | None, candles_fn,
                  sample: dict | None = None) -> dict:
    """Yopilgan savdoning qisqa tahlili. candles_fn(symbol, tf, limit, end) -> list[Candle] (faqat ochilishdan oldingi ma'lumot
    ishlatiladi). Ma'lumot yetishmasa — tegishli maydon None va sabab yoziladi; hech narsa to'qilmaydi."""
    from .indicators import Features
    from .signal_score import evaluate, macd_hist, trend_of

    long = s["direction"] == "BUY"
    entry, exit_, net = s["entry_price"], s["exit_price"], s["net"]
    out: dict = {"position_id": s["position_id"], "symbol": s["symbol"], "direction": s["direction"],
                 "volume": s["volume"], "opened_at": s["opened_at"].isoformat(), "closed_at": s["closed_at"].isoformat(),
                 "duration_s": s["duration_s"], "entry": entry, "sl": sl, "tp": tp, "exit": exit_, "reason": s["reason"],
                 "profit": s["profit"], "commission": s["commission"], "swap": s["swap"], "net": net,
                 "source": "SENTINAL" if s["magic"] == SENTINAL_MAGIC else "OTHER", "notes": []}
    risk_px = abs(entry - sl) if sl else None
    if risk_px and contract:
        out["risk_money"] = round(risk_px * s["volume"] * contract, 4)
        out["r_multiple"] = round(net / out["risk_money"], 3) if out["risk_money"] else None
    out["rr_planned"] = round(abs(tp - entry) / risk_px, 2) if (tp and risk_px) else None
    worked, failed, wrong, improve = [], [], [], []
    # --- ochilish paytidagi kontekst (faqat o'sha paytgacha yopilgan shamlar)
    ctx = None
    try:
        t0 = s["opened_at"]

        def closed(tf: str):  # faqat ochilishgacha YOPILGAN shamlar (kelajak ma'lumoti aralashmaydi)
            return [c for c in candles_fn(s["symbol"], tf, 320, t0) if c.end <= t0]
        f4, f1, f15 = Features.build(closed("4h")), Features.build(closed("1h")), Features.build(closed("15m"))
        atr1, atr15 = f1.atr14[-1], f15.atr14[-1]
        out["atr_1h"], out["atr_15m"] = round(atr1, 6), round(atr15, 6)
        if risk_px:
            out["sl_atr_1h"], out["sl_atr_15m"] = round(risk_px / atr1, 2), round(risk_px / atr15, 2)
        rr_net = (out["rr_planned"] or 0)
        sc = evaluate(long, f15, f1, f4, entry=entry, sl=sl or entry, tp=tp or entry,
                      rr_net=rr_net, min_rr=1.5, volume_kind="tick") if sl and tp else None
        ctx = {"h4_trend": trend_of(f4), "h1_trend": trend_of(f1),
               "rsi_1h": round(f1.rsi14[-1], 1) if not math.isnan(f1.rsi14[-1]) else None,
               "macd_hist_1h": round(macd_hist(f1.close)[-1], 4), "structure": _swing_state(f1, len(f1) - 1)}
        if sc:
            out["score"] = {"score": sc.score, "tier": sc.tier, "items": [
                {"key": i.key, "ok": i.ok, "detail": i.detail} for i in sc.items]}
            wrong = [i.label + ": " + i.detail for i in sc.items if i.ok is False]
            worked = [i.label for i in sc.items if i.ok]
        out["context"] = ctx
    except (DataUnavailable, IndexError, ValueError, KeyError) as exc:
        out["notes"].append(f"ochilish konteksti tiklanmadi: {str(exc)[:120]}")
    # --- savdo davomidagi yo'l (1 daqiqalik): eng yomon / eng yaxshi harakat
    try:
        end = s["closed_at"] + timedelta(minutes=1)
        mins = [c for c in candles_fn(s["symbol"], "1m", 1000, end) if s["opened_at"] - timedelta(minutes=1) <= c.ts <= end]
        if mins:
            hi, lo = max(c.high for c in mins), min(c.low for c in mins)
            mae = (hi - entry) if not long else (entry - lo)  # eng yomon qarshi harakat (narx birligida)
            mfe = (entry - lo) if not long else (hi - entry)
            out["mae"], out["mfe"] = round(max(mae, 0), 6), round(max(mfe, 0), 6)
            if risk_px:
                out["mae_r"], out["mfe_r"] = round(max(mae, 0) / risk_px, 2), round(max(mfe, 0) / risk_px, 2)
            tp_px = abs(tp - entry) if tp else None
            if tp_px:
                out["mfe_of_tp"] = round(max(mfe, 0) / tp_px, 2)
    except (DataUnavailable, ValueError) as exc:
        out["notes"].append(f"yo'l ma'lumoti yo'q: {str(exc)[:100]}")
    # --- xulosalar (qoidaga asoslangan)
    verdict = {"worked": worked, "failed": failed, "wrong_indicators": wrong, "improve": improve}
    if ctx:
        want = "TREND_DOWN" if not long else "TREND_UP"
        if ctx["h4_trend"] == want and ctx["h1_trend"] == want:
            worked.append("yo'nalish 4H va 1H trendiga mos edi")
        else:
            failed.append(f"yo'nalish trendga mos emas (4H {ctx['h4_trend']}, 1H {ctx['h1_trend']})")
    sl_atr = out.get("sl_atr_1h")
    if sl_atr is not None:
        if sl_atr < 0.5:
            failed.append(f"SL juda yaqin: {sl_atr} ATR(1h) — oddiy bozor shovqini ichida")
            improve.append("Gipoteza: SL ni kamida 1 ATR(1h) masofada qo'yish (lotni kamaytirib riskni saqlash) — avval tarixiy "
                           "sinov va paper bilan tekshirilsin")
        elif sl_atr < 1.0:
            failed.append(f"SL tor: {sl_atr} ATR(1h)")
        else:
            worked.append(f"SL masofasi asosli: {sl_atr} ATR(1h)")
    if out.get("rr_planned") and out["rr_planned"] > 3 and s["reason"] == "SL":
        failed.append(f"R/R {out['rr_planned']} juda katta: TP uzoq, tor SL bilan birga ehtimol past")
    if s["reason"] == "SL" and "mfe_r" in out:
        if out["mfe_r"] >= 1.0:
            failed.append(f"savdo SL gacha {out['mfe_r']}R foydaga chiqqan (TP ga {out.get('mfe_of_tp', 0) * 100:.0f}%) — chiqish "
                          "qoidasi (qisman yopish/trailing) kerak bo'lishi mumkin")
        else:
            failed.append(f"foyda yo'nalishida eng ko'pi {out['mfe_r']}R")
    if "sr" in [i["key"] for i in (out.get("score") or {}).get("items", []) if i["ok"] is False]:
        failed.append("kirish qo'llab-quvvatlash/qarshilik darajasi yonida (R/R sifatsiz)")
    if s["reason"] == "TP":
        worked.append("TP ga yetdi")
    if s["commission"] and abs(s["commission"]) > 0:
        out["notes"].append(f"komissiya {s['commission']:+.2f}")
    n = (sample or {}).get("n")
    out["verdict"] = verdict
    out["sample"] = {**(sample or {}), "warning": "bitta savdo asosida strategiya o'zgartirilmaydi — kamida o'nlab savdo "
                                                     "statistikasi va tarixiy sinov kerak"}
    parts = []
    if s["reason"] == "SL":
        parts.append(f"SL ishladi ({out.get('r_multiple', '?')}R)")
    elif s["reason"] == "TP":
        parts.append(f"TP ga yetdi ({out.get('r_multiple', '?')}R)")
    parts += [x for x in failed[:2]] or [x for x in worked[:1]]
    out["short"] = "; ".join(parts) + f". Namuna: {n if n is not None else '?'} savdo — xulosa uchun yetarli emas." \
        if (n or 0) < 30 else "; ".join(parts) + f". Namuna: {n} savdo."
    return out


# -------------------------------------------------------------------------------------------- navbat
SendFn = Callable[[int, str], Awaitable[dict]]


class NotificationQueue:
    """Bazadagi navbat: kalit bo'yicha yagona, qayta urinish bilan. send(chat_id, text)."""

    def __init__(self, db, send: SendFn, chat_for: Callable[[str], int | None], clock=None):
        self.db = db
        self.send = send
        self.chat_for = chat_for
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def enqueue(self, key: str, kind: str, target: str, text: str) -> bool:
        now = now_iso(self.clock())
        cur = self.db.execute("INSERT OR IGNORE INTO notifications(key, kind, target, text, status, attempts, next_try, "
                              "created_at) VALUES(?,?,?,?,'PENDING',0,?,?)", (key, kind, target, text, now, now))
        return cur.rowcount == 1

    def pending(self) -> list[dict]:
        return self.db.query("SELECT * FROM notifications WHERE status='PENDING' ORDER BY id")

    async def flush(self) -> dict:
        from ..telegram_api import TelegramError, TelegramNetworkError
        now = self.clock()
        res = {"sent": 0, "failed": 0, "waiting": 0, "gave_up": 0}
        for n in self.db.query("SELECT * FROM notifications WHERE status='PENDING' AND next_try<=? ORDER BY id", (now_iso(now),)):
            chat = self.chat_for(n["target"])
            if chat is None:
                res["waiting"] += 1
                continue
            # ikki oqim bir xabarni yubormasligi uchun band qilamiz
            if self.db.execute("UPDATE notifications SET status='SENDING' WHERE id=? AND status='PENDING'",
                               (n["id"],)).rowcount != 1:
                continue
            text = ("↻ " + n["text"]) if n["ambiguous"] else n["text"]
            try:
                msg = await self.send(chat, text)
            except TelegramNetworkError as exc:  # yetib borgan-bormagani noma'lum -> qayta yuboriladi (↻)
                self._fail(n, now, f"tarmoq: {exc}", ambiguous=True)
                res["failed"] += 1
            except TelegramError as exc:
                self._fail(n, now, str(exc)[:200], ambiguous=n["ambiguous"])
                res["failed"] += 1
            else:
                self.db.execute("UPDATE notifications SET status='SENT', sent_at=?, message_id=?, error=NULL WHERE id=?",
                                (now_iso(now), (msg or {}).get("message_id"), n["id"]))
                res["sent"] += 1
        res["gave_up"] = self.db.one("SELECT COUNT(*) n FROM notifications WHERE status='FAILED'")["n"]
        return res

    def _fail(self, n: dict, now: datetime, error: str, ambiguous: bool) -> None:
        attempts = n["attempts"] + 1
        age = now - datetime.fromisoformat(n["created_at"])
        if age > GIVE_UP:
            self.db.execute("UPDATE notifications SET status='FAILED', attempts=?, error=? WHERE id=?",
                            (attempts, error, n["id"]))
            return
        delay = BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
        self.db.execute("UPDATE notifications SET status='PENDING', attempts=?, next_try=?, error=?, ambiguous=? WHERE id=?",
                        (attempts, now_iso(now + timedelta(seconds=delay)), error, 1 if ambiguous else 0, n["id"]))
        if attempts == 3 and n["kind"] != "alert":  # MONITORING ERROR (telegram send failed) — egasiga alohida texnik ogohlantirish
            self.enqueue(f"pv:sendfail:{n['key']}", "alert", "private",
                         f"⚠️ SENTINEL | MONITORING ERROR (telegram send failed)\nXabar ({n['kind']}, {n['key']}) {attempts} urinishdan keyin ham "
                         f"yuborilmadi: {error[:150]}\nXabar navbatda saqlanadi va qayta yuboriladi — yo'qolmaydi.")


# -------------------------------------------------------------------------------------------- monitor
@dataclass
class Counters:
    opened: int = 0
    modified: int = 0
    closed: int = 0
    backfilled: int = 0
    pending_close: int = 0
    error: str = ""


class PositionMonitor:
    def __init__(self, svc, history, queue: NotificationQueue, candles_fn, currency_fn=lambda: "USD",
                 analysis_path: Path | None = None, journal=None, contract_fn=lambda sym: None):
        self.svc = svc
        self.db = svc.db
        self.h = history
        self.q = queue
        self.candles_fn = candles_fn
        self.currency_fn = currency_fn
        self.contract_fn = contract_fn
        self.journal = journal
        self.analysis_path = Path(analysis_path or (Path(svc.memory.root).parent / "trading" / "post_trade_analysis.json"))
        self.fail_streak = 0
        self.down_alerted = False
        self._first = True

    @property
    def cfg(self) -> dict:
        return {"enabled": True, "poll_sec": 60, "backfill_h": 48, **(self.svc.settings.get("monitor") or {})}

    def _ev(self, kind: str, text: str, **kw) -> None:
        if self.journal is not None:
            self.journal.event(kind, text, **kw)

    # ------------------------------------------------------------------ yordamchi
    def _row(self, pid: int) -> dict | None:
        return self.db.one("SELECT * FROM mt5_positions WHERE position_id=?", (pid,))

    def _target(self) -> str:
        return "private"  # monitoring va tahlil FAQAT shaxsiy chatga (guruhga hech qachon)

    def _sample(self) -> dict:
        r = self.db.one("SELECT COUNT(*) n, SUM(CASE WHEN net>0 THEN 1 ELSE 0 END) w, ROUND(SUM(net),2) net, "
                        "ROUND(SUM(r_multiple),2) r FROM live_trades")
        return {"n": r["n"], "wins": r["w"] or 0, "net": r["net"] or 0.0, "total_r": r["r"] or 0.0}

    def live_stats(self) -> dict:
        s = self._sample()
        by = {r["reason"]: r["n"] for r in self.db.query("SELECT reason, COUNT(*) n FROM live_trades GROUP BY reason")}
        return {**s, "win_rate": round(s["wins"] / s["n"] * 100, 1) if s["n"] else None, "by_reason": by,
                "note": "namuna kichik bo'lsa xulosa chiqarilmaydi" if s["n"] < 30 else ""}

    # ------------------------------------------------------------------ asosiy sikl
    def poll_once(self, now: datetime) -> Counters:
        c = Counters()
        tz = self.svc.settings.tz
        ccy = self.currency_fn()
        try:
            open_now = self.h.open_positions()
        except DataUnavailable as exc:
            self.fail_streak += 1
            c.error = str(exc)[:200]
            if self.fail_streak >= DISCONNECT_AFTER and not self.down_alerted:
                self.down_alerted = True
                self.q.enqueue(f"pv:mt5down:{now_iso(now)}", "alert", "private",
                               "🔌 SENTINEL | MT5 CONNECTION LOST\n"
                               f"{self.fail_streak} marta ketma-ket o'qib bo'lmadi: {c.error}\n"
                               "Pozitsiya monitoringi to'xtab turibdi (terminal ochiq va hisobga kirilganini tekshiring). "
                               "Tiklanganda yopilishlar tarixdan to'ldiriladi.")
                self._ev("mt5_monitor", "MT5 uzildi — monitoring to'xtadi", error=c.error)
            return c
        if self.down_alerted:
            self.down_alerted = False
            self.q.enqueue(f"pv:mt5up:{now_iso(now)}", "alert", "private",
                           f"✅ SENTINEL | MT5 CONNECTION RESTORED\nMonitoring davom etmoqda (uzilish: {self.fail_streak} so'rov).")
        self.fail_streak = 0
        first = self._first
        self._first = False
        seen = {p["ticket"] for p in open_now}
        # 1. ochiq pozitsiyalar: yangi yoki SL/TP o'zgargan
        for p in open_now:
            row = self._row(p["ticket"])
            if row is None:
                late = first and (now - p["time"]) > timedelta(minutes=5)
                self.db.execute(
                    "INSERT INTO mt5_positions(position_id, symbol, direction, volume, entry, sl, tp, opened_at, magic, state, "
                    "first_seen_at, last_sl, last_tp) VALUES(?,?,?,?,?,?,?,?,?,'OPEN',?,?,?)",
                    (p["ticket"], p["symbol"], p["side"], p["volume"], p["price_open"], p["sl"], p["tp"], now_iso(p["time"]),
                     p["magic"], now_iso(now), p["sl"], p["tp"]))
                self.q.enqueue(f"pv:opened:{p['ticket']}", "opened", self._target(), format_opened(p, ccy, late, tz))
                c.opened += 1
            elif row["state"] == "OPEN" and (row["last_sl"] != p["sl"] or row["last_tp"] != p["tp"]):
                old = {"sl": row["last_sl"], "tp": row["last_tp"]}
                self.q.enqueue(f"pv:modified:{p['ticket']}:{p['sl']}:{p['tp']}", "modified", self._target(), format_modified(p, old))
                self.db.execute("UPDATE mt5_positions SET last_sl=?, last_tp=? WHERE position_id=?",
                                (p["sl"], p["tp"], p["ticket"]))
                c.modified += 1
        # 2. oldin ochiq bo'lgan, endi yo'q: yopilgan bo'lishi kerak — tarix tasdiqlasa xabar
        for row in self.db.query("SELECT * FROM mt5_positions WHERE state='OPEN'"):
            if row["position_id"] in seen:
                continue
            if self._finalize(row["position_id"], now, ccy, tz, late_note=""):
                c.closed += 1
            else:
                c.pending_close += 1
                self._warn_unconfirmed(row, now)
        # 3. tarixdan to'ldirish: monitor ko'rmagan (tez ochilib yopilgan yoki o'chiq payti yopilgan) pozitsiyalar
        hours = float(self.cfg["backfill_h"]) if first else 3.0
        try:
            deals = self.h.deals_between(now - timedelta(hours=hours), now + timedelta(minutes=5))
        except DataUnavailable:
            deals = []
        for pid in sorted({d.position_id for d in deals if d.entry in ("OUT", "OUT_BY", "INOUT")}):
            if pid in seen or self._row(pid) is not None:
                continue
            ins = [d for d in self.h.deals_of_position(pid)]
            if not ins:
                continue
            first_in = next((d for d in ins if d.entry == "IN"), None)
            if first_in is None:
                continue
            self.db.execute("INSERT INTO mt5_positions(position_id, symbol, direction, volume, entry, opened_at, magic, state, "
                            "first_seen_at, notified_open) VALUES(?,?,?,?,?,?,?,'OPEN',?,0)",
                            (pid, first_in.symbol, "BUY" if first_in.type == "BUY" else "SELL", first_in.volume,
                             first_in.price, now_iso(first_in.time), first_in.magic, now_iso(now)))
            late_note = ("ℹ️ Kechikkan xabar: pozitsiya monitoring ishlamayotgan paytda yoki oraliqda yopilgan; ma'lumot MT5 "
                         "tarixidan olindi.")
            if self._finalize(pid, now, ccy, tz, late_note=late_note):
                c.backfilled += 1
        self._first = False
        self.db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('monitor_last_ok', ?)", (now_iso(now),))
        return c

    def _warn_unconfirmed(self, row: dict, now: datetime) -> None:
        key = f"pv:unconfirmed:{row['position_id']}"
        gone = datetime.fromisoformat(row["first_seen_at"])
        if now - gone > timedelta(minutes=30):
            self.q.enqueue(key, "alert", "private", f"⚠️ SENTINEL | MONITORING ERROR (close not confirmed)\nPozitsiya #{row['position_id']} "
                           f"({row['symbol']}) ochiq ro'yxatda yo'q, lekin MT5 tarixida yopilish bitimi topilmayapti. "
                           "Tasdiqlanmaguncha yopilish xabari yuborilmaydi.")

    def _closed_parts(self, pid: int):
        """Tarixdan yopilish ma'lumoti: (summary, sl, tp, analysis) yoki None (tarixda to'liq yopilish tasdiqlanmagan)."""
        try:
            deals = self.h.deals_of_position(pid)
        except DataUnavailable:
            return None
        s = summarize(deals)
        if s is None:
            return None
        row = self._row(pid) or {}
        orders = []
        try:
            orders = self.h.orders_of_position(pid)
        except DataUnavailable:
            pass
        sl = row.get("last_sl") or row.get("sl") or (orders[0]["sl"] if orders and orders[0]["sl"] else None)
        tp = row.get("last_tp") or row.get("tp") or (orders[0]["tp"] if orders and orders[0]["tp"] else None)
        if not sl and s["reason"] == "SL":  # SL bitim izohidan: "[sl 75740.00000]"
            import re
            m = re.search(r"\[sl ([0-9.]+)\]", s["comment"] or "")
            sl = float(m.group(1)) if m else None
        try:
            sample = self._sample()
            if not self.db.one("SELECT 1 FROM live_trades WHERE position_id=?", (pid,)):
                sample["n"] += 1  # shu savdo ham namunaga kiradi
            analysis = analyze_trade(s, sl, tp, self.contract_fn(s["symbol"]), self.candles_fn, sample)
        except Exception as exc:  # noqa: BLE001 — tahlil xatosi xabarni to'xtatmasin
            log.exception("savdo tahlili %s", pid)
            analysis = None
            self._ev("mt5_monitor", f"tahlil xatosi {pid}: {type(exc).__name__}")
            self.q.enqueue(f"pv:analysiserr:{pid}", "alert", "private",
                           f"⚠️ SENTINEL | MONITORING ERROR (analysis)\nPozitsiya #{pid}: tahlil hisoblanmadi "
                           f"({type(exc).__name__}). Natija xabari yuborildi, tahlil keyinroq qo'lda tekshiriladi.")
        return s, sl, tp, analysis

    def _enqueue_closed(self, parts, ccy: str, tz, late_note: str) -> None:
        s, sl, tp, analysis = parts
        pid = s["position_id"]
        self.q.enqueue(f"pv:closed:{pid}", "closed", self._target(), format_closed(s, ccy, analysis, tz, late_note, sl, tp))
        self.q.enqueue(f"pv:report:{pid}", "report", self._target(), format_report(s, analysis, ccy, tz))

    def _finalize(self, pid: int, now: datetime, ccy: str, tz, late_note: str) -> bool:
        """Tarixda to'liq yopilish tasdiqlansa: holat, xabarlar (natija + POST-TRADE REPORT), tahlil. Aks holda False."""
        parts = self._closed_parts(pid)
        if parts is None:
            return False
        s, sl, tp, analysis = parts
        self.db.execute("UPDATE mt5_positions SET state='CLOSED', closed_at=?, close_reason=?, net=? WHERE position_id=?",
                        (now_iso(s["closed_at"]), s["reason"], s["net"], pid))
        self.db.execute("INSERT OR IGNORE INTO live_trades(position_id, strategy, symbol, direction, opened_at, closed_at, net, "
                        "r_multiple, reason, source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (pid, "SENTINAL-demo (chat/qo'lda)" if s["magic"] == SENTINAL_MAGIC else "OTHER", s["symbol"],
                         s["direction"], now_iso(s["opened_at"]), now_iso(s["closed_at"]), s["net"],
                         (analysis or {}).get("r_multiple"), s["reason"],
                         "SENTINAL" if s["magic"] == SENTINAL_MAGIC else "OTHER"))
        if analysis:
            self._save_analysis(analysis)
        self._enqueue_closed(parts, ccy, tz, late_note)
        self._ev("mt5_monitor", f"Pozitsiya #{pid} yopildi: {s['symbol']} {s['reason']} {s['net']:+.2f}", position=pid)
        return True

    # ------------------------------------------------------------------ bir martalik vazifalar (test, qayta yuborish)
    def startup_tasks(self, now: datetime) -> list[str]:
        """settings["monitor"]: test_pending — shaxsiy chatga TEST xabari; republish — [position_id, ...] ni shaxsiy chatga bir
        marta qayta yuborish (avval guruhga ketgan xabarlar). Bajarilgach bayroqlar tozalanadi."""
        cfg = self.svc.settings.data.setdefault("monitor", {})
        done = []
        if cfg.get("test_pending"):
            self.q.enqueue(f"pv:test:{now_iso(now)}", "test", "private",
                           "🧪 SENTINEL | TEST\nMonitoring va post-trade tahlil xabarlari FAQAT shu shaxsiy chatga keladi, "
                           "guruhga yuborilmaydi. Agar bu xabarni ko'rsangiz — yetkazish ishlayapti.")
            cfg["test_pending"] = False
            done.append("test")
        ids = [int(x) for x in cfg.get("republish") or []]
        for pid in ids:
            if self._republish(pid, now):
                done.append(f"republish:{pid}")
        if ids:
            cfg["republish"] = []
        if done:
            self.svc.settings.save()
        return done

    def _republish(self, pid: int, now: datetime) -> bool:
        tz, ccy = self.svc.settings.tz, self.currency_fn()
        note = "ℹ️ Shaxsiy chatga qayta yuborildi (avval guruhga ketgan edi)."
        parts = self._closed_parts(pid)
        if parts is not None:
            self._enqueue_closed(parts, ccy, tz, note)
            return True
        try:
            p = next((x for x in self.h.open_positions() if x["ticket"] == pid), None)
        except DataUnavailable:
            return False
        if p is None:
            return False
        self.q.enqueue(f"pv:opened:{pid}", "opened", self._target(), format_opened(p, ccy, True, tz) + "\n" + note)
        return True

    def _save_analysis(self, a: dict) -> None:
        """data/trading/post_trade_analysis.json — atomik yozuv, position_id bo'yicha takror yozilmaydi (yangilanadi)."""
        path = self.analysis_path
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {"version": 1, "trades": []}
        data["trades"] = [t for t in data.get("trades", []) if t.get("position_id") != a["position_id"]] + [a]
        data["trades"].sort(key=lambda t: t["closed_at"])
        data["updated_at"] = now_iso(self.svc.clock())
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, path)

    def downtime_alert(self, now: datetime) -> None:
        """Agent/monitor to'xtab qolgan bo'lsa (oxirgi muvaffaqiyatli tekshiruv eski) — qayta ishga tushganda texnik xabar."""
        last = self.db.one("SELECT value FROM meta WHERE key='monitor_last_ok'")
        if not last:
            return
        gap = now - datetime.fromisoformat(last["value"])
        if gap > timedelta(minutes=10):
            self.q.enqueue(f"pv:monitordown:{last['value']}", "alert", "private",
                           f"⚠️ SENTINEL | MONITORING ERROR (monitor was down)\nPozitsiya monitoringi {last['value'][:16].replace('T', ' ')} UTC dan "
                           f"{fmt_duration(int(gap.total_seconds()))} ishlamagan. Shu oraliqdagi yopilishlar MT5 tarixidan "
                           "tekshiriladi va topilganlari 'kechikkan xabar' sifatida yuboriladi.")


__all__ = ["private_chat_resolver", "format_report", "PositionMonitor", "NotificationQueue", "analyze_trade", "format_closed", "format_opened", "format_modified",
           "reason_title"]
