"""Trading tadqiqoti tool'lari (faqat tadqiqot bazasi: trading_memory/). Savdo, buyurtma, broker — YO'Q."""
from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from .. import gate
from .base import ToolContext, ToolResult

_services: dict[str, object] = {}
_lock = threading.Lock()


def _service(ctx: ToolContext):
    from ..trading.service import TradingService

    key = str(Path(ctx.paths.home).resolve())
    with _lock:
        if key not in _services:
            _services[key] = TradingService(ctx.paths.home)
        return _services[key]


def classify_internal(ctx: ToolContext, args: dict) -> gate.Decision:
    return gate.Decision(host="localhost").escalate(gate.INTERNAL)


def classify_read(ctx: ToolContext, args: dict) -> gate.Decision:
    return gate.Decision(host="localhost")


async def research_source(ctx: ToolContext, args: dict) -> ToolResult:
    svc = _service(ctx)
    try:
        added = svc.record_source(topic=args.get("topic", ""), url=args["url"], title=args["title"],
                                  summary=args["summary"], evidence_type=args["evidence_type"],
                                  publisher=args.get("publisher", ""), published_at=args.get("published_at", ""),
                                  task_id=ctx.task_id)
    except ValueError as exc:
        return ToolResult(False, f"Yozilmadi: {exc}")
    return ToolResult(True, "Manba yozildi." if added else "Bu manba shu mavzu bo'yicha allaqachon bor.")


async def report(ctx: ToolContext, args: dict) -> ToolResult:
    svc = _service(ctx)
    perf = svc.performance(args.get("date_from"), args.get("date_to"))
    recent = svc.db.query("SELECT a.analysis_id, a.created_at, a.symbol, a.timeframe, a.kind, a.strategy_id, "
                          "a.strategy_version, a.direction, a.entry, a.sl, a.tp, a.rr, o.status, o.r_multiple "
                          "FROM analyses a LEFT JOIN outcomes o ON o.analysis_id=a.analysis_id "
                          "ORDER BY a.created_at DESC LIMIT ?", (int(args.get("limit") or 15),))
    lib = svc.db.query("SELECT strategy_id, version, symbol, timeframe, period_start, period_end, sample_size, win_rate, "
                       "expectancy, max_dd FROM strategy_stats ORDER BY id DESC LIMIT 14")
    reviews = svc.db.query("SELECT analysis_id, strategy_id, classification FROM sl_reviews ORDER BY created_at DESC "
                           "LIMIT 10")
    exps = svc.db.query("SELECT experiment_id, strategy_id, base_version, candidate_version, verdict FROM experiments "
                        "ORDER BY created_at DESC LIMIT 10")
    out = {"performance": perf, "recent_analyses": recent, "strategy_backtests": lib, "sl_reviews": reviews,
           "experiments": exps, "note": "Bu paper trading (simulyatsiya) natijalari. Raqamlarni o'zgartirmasdan ayt."}
    return ToolResult(True, json.dumps(out, ensure_ascii=False, default=str)[:12000])


async def experiment(ctx: ToolContext, args: dict) -> ToolResult:
    svc = _service(ctx)
    params = args.get("params") or {}
    if not isinstance(params, dict) or not params:
        return ToolResult(False, "params — o'zgartiriladigan parametrlar obyekti (masalan {\"sl_atr\": 1.75})")
    try:
        rec = await asyncio.to_thread(svc.run_experiment, args["strategy_id"].upper(), params, args["problem"],
                                      args["hypothesis"], args.get("symbol") or "BTCUSDT", args.get("timeframe") or "1h",
                                      f"agent ({ctx.task_id})")
    except Exception as exc:  # noqa: BLE001 — ma'lumot yo'q yoki noto'g'ri parametr
        return ToolResult(False, f"Eksperiment o'tkazilmadi: {type(exc).__name__}: {exc}")
    res = rec["results"]
    b, c = res["base"]["out_of_sample"], res["candidate"]["out_of_sample"]
    return ToolResult(True, (f"{rec['experiment_id']}: {rec['strategy_id']} v{rec['base_version']} -> "
                             f"v{rec['candidate_version']} | verdikt: {rec['verdict']} — {res['explanation']}\n"
                             f"OOS asosiy: {json.dumps(b, ensure_ascii=False)}\nOOS nomzod: {json.dumps(c, ensure_ascii=False)}\n"
                             "Versiya avtomatik faollashtirilmaydi: faqat Jamshid /trading_faollashtir bilan."))


async def track_manual(ctx: ToolContext, args: dict) -> ToolResult:
    svc = _service(ctx)
    try:
        rec = await asyncio.to_thread(
            svc.track_manual, symbol=args["symbol"].upper(), timeframe=args.get("timeframe") or "1h",
            direction=args["direction"], entry_type=args["entry_type"], entry=float(args["entry"]), sl=float(args["sl"]),
            tp=float(args["tp"]), valid_hours=float(args.get("valid_hours") or 24), note=args.get("note", ""),
            source=f"chat {ctx.task_id}")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(False, f"Kuzatuvga olinmadi: {type(exc).__name__}: {exc}")
    return ToolResult(True, (f"{rec['analysis_id']} kuzatuvga olindi (MANUAL v0, {rec['symbol']} {rec['timeframe']} "
                             f"{rec['direction']} {rec['entry_type']} {rec['entry']}, SL {rec['sl']}, TP {rec['tp']}, "
                             f"R/R 1:{rec['rr']}). Natija har 10 daqiqada yangilanadi; statistikada MANUAL alohida. "
                             "Guruhga avtomatik yuborilmaydi."))


SOURCE_DESCRIPTION = ("Trading tadqiqoti: o'rganilgan manbani bazaga yozadi (url, sarlavha, nashr sanasi, xulosa, dalil "
                      "turi: verified_finding | opinion | hypothesis). Sana noma'lum bo'lsa bo'sh qoldir — o'ylab topma.")
REPORT_DESCRIPTION = ("Trading tadqiqoti natijalari (paper trading): statistika, so'nggi tahlillar va natijalari, "
                      "strategiyalar backtesti, SL tahlillari, eksperimentlar. Faqat o'qish.")
EXPERIMENT_DESCRIPTION = ("Strategiya yaxshilash eksperimenti: yangi NOMZOD versiya (parametr o'zgarishi) yaratadi, tarixiy "
                          "ma'lumotda in-sample/out-of-sample sinaydi (xarajat bilan), eski versiya bilan solishtiradi va "
                          "natijani saqlaydi (muvaffaqiyatsizi ham). Faol strategiyani O'ZGARTIRMAYDI.")
SOURCE_SCHEMA = {"type": "object", "properties": {
    "topic": {"type": "string"}, "url": {"type": "string"}, "title": {"type": "string"},
    "publisher": {"type": "string"}, "published_at": {"type": "string", "description": "YYYY-MM-DD yoki bo'sh"},
    "summary": {"type": "string"},
    "evidence_type": {"type": "string", "enum": ["verified_finding", "opinion", "hypothesis"]}},
    "required": ["url", "title", "summary", "evidence_type"]}
REPORT_SCHEMA = {"type": "object", "properties": {
    "date_from": {"type": "string"}, "date_to": {"type": "string"}, "limit": {"type": "integer"}}}
MANUAL_DESCRIPTION = ("Suhbatda yoki Jamshid bergan qo'lda tuzilgan savdo ssenariysini (kirish/SL/TP) qog'oz savdo "
                      "kuzatuviga oladi — MANUAL v0 sifatida, tizim strategiyalari statistikasidan alohida. Faqat "
                      "Jamshid so'raganda. Real savdo emas.")
MANUAL_SCHEMA = {"type": "object", "properties": {
    "symbol": {"type": "string", "description": "Masalan BTCUSDT"}, "timeframe": {"type": "string", "enum": ["1h", "4h"]},
    "direction": {"type": "string", "enum": ["LONG", "SHORT"]},
    "entry_type": {"type": "string", "enum": ["buy_stop", "buy_limit", "sell_stop", "sell_limit", "next_open"]},
    "entry": {"type": "number"}, "sl": {"type": "number"}, "tp": {"type": "number"},
    "valid_hours": {"type": "number", "description": "Kirish sharti necha soat kutiladi (standart 24)"},
    "note": {"type": "string", "description": "Qayerdan/nimaga asoslangan"}},
    "required": ["symbol", "direction", "entry_type", "entry", "sl", "tp"]}
EXPERIMENT_SCHEMA = {"type": "object", "properties": {
    "strategy_id": {"type": "string", "description": "TF-PULLBACK, BRK-RETEST, SR-BOUNCE, MA-CROSS, RSI-MR, VOL-BRK, MS-BOS"},
    "params": {"type": "object", "description": "O'zgaradigan parametrlar, masalan {\"sl_atr\": 1.75}"},
    "problem": {"type": "string", "description": "Kuzatilgan muammo (masalan SL tahlillaridan)"},
    "hypothesis": {"type": "string", "description": "Sinaladigan gipoteza"},
    "symbol": {"type": "string"}, "timeframe": {"type": "string", "enum": ["1h", "4h"]}},
    "required": ["strategy_id", "params", "problem", "hypothesis"]}


# ------------------------------------------------------------------------------------------------ MetaTrader 5 (V19)
async def mt5_status(ctx: ToolContext, args: dict) -> ToolResult:
    """Ulanish testi + bitta tarixiy ma'lumot testi. Terminalni ishga tushirmaydi, buyurtma yubormaydi."""
    import asyncio

    from ..trading import mt5_connector as mt5c
    from ..trading.data import DataUnavailable

    conn = _service(ctx).mt5
    symbol = str(args.get("symbol") or "EUR/USD")
    timeframe = str(args.get("timeframe") or "1h")
    bars = max(50, min(2000, int(args.get("bars") or 200)))

    def run() -> tuple[bool, list[str]]:
        st = mt5c.status(conn)
        terms = "; ".join(f"{t['name']} ({'ochiq' if t.get('running') else 'yopiq'}"
                          f"{', ' + str(t['user']) if t.get('user') else ''})" for t in st["terminals"]) or "topilmadi"
        lines = [f"Terminallar: {terms}. Agent foydalanuvchisi: {st['agent_user']}"]
        if not st["connected"]:
            lines.append(f"Ulanish: YO'Q — {st['reason']}")
            return False, lines
        lines.append(f"Ulanish: OK — {st['terminal']} (build {st['build']}), server {st['server']}, hisob turi "
                     f"{st['trade_mode']}, simvollar {st['symbols']}. Faqat o'qish; Algo Trading tugmasi "
                     f"{'yoqilgan' if st['algo_trading_button'] else 'o`chiq'} (o'zgartirilmaydi)")
        try:
            candles = conn.candles(symbol, timeframe, bars + 1)
        except DataUnavailable as exc:
            lines.append(f"Tarix: YO'Q — {exc}")
            return False, lines
        now = conn.clock()
        closed = [c for c in candles if c.end <= now]
        if not closed:
            lines.append(f"Tarix: {symbol} {timeframe} — yopilgan sham yo'q")
            return False, lines
        last = closed[-1]
        off = conn._offset[0] if conn._offset else None
        age_min = int((now - last.end).total_seconds() // 60)
        lines.append(f"Tarix: {symbol} -> {conn.resolve(symbol)} {timeframe}: {len(closed)} ta yopilgan sham, "
                     f"{closed[0].ts:%Y-%m-%d %H:%M} — {last.ts:%Y-%m-%d %H:%M} UTC; oxirgi close {last.close} "
                     f"(yopilganiga {age_min} daqiqa)" + (f"; server vaqti UTC{off / 3600:+.1f}" if off is not None else ""))
        return True, lines

    ok, lines = await asyncio.to_thread(run)
    return ToolResult(ok, "\n".join(lines))


MT5_SCHEMA = {"type": "object", "properties": {
    "symbol": {"type": "string", "description": "Instrument (masalan EUR/USD, XAU/USD, BTCUSD). Default EUR/USD."},
    "timeframe": {"type": "string", "enum": ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]},
    "bars": {"type": "integer", "description": "Nechta sham (50-2000), default 200"}}}
MT5_DESCRIPTION = ("MetaTrader 5 ulanish testi (FAQAT O'QISH): o'rnatilgan va ochiq terminallar, hisob turi (DEMO/REAL), "
                   "tarixiy OHLC shamlar (broker simvol nomi avtomatik topiladi, vaqt UTC ga o'giriladi). Terminalni "
                   "ishga tushirmaydi, buyurtma yubormaydi, sozlamani o'zgartirmaydi. REAL hisobda ulanmaydi (demo "
                   "kerak). MT5 bilan ishlash uchun o'z skriptingni yozma — shu tool'ni ishlat.")


# ------------------------------------------------------------------------------------------------ MT5 DEMO savdo (V20)
def classify_mt5_order(ctx: ToolContext, args: dict) -> gate.Decision:
    """check/positions — o'qish. open/close — har safar Jamshid tasdig'i (DANGER)."""
    if str(args.get("action")) in ("open", "close"):
        return gate.Decision(host="localhost").escalate(
            gate.DANGER, "MT5 DEMO hisobda savdo buyrug'i (open/close) — har bir buyurtma egasining tasdig'i bilan",
            "real_trade")
    return gate.Decision(host="localhost")


async def mt5_order(ctx: ToolContext, args: dict) -> ToolResult:
    from ..trading.mt5_trade import TradeRefused

    trader = _service(ctx).mt5_trader
    action = str(args.get("action") or "")

    def run() -> ToolResult:
        try:
            if action == "positions":
                rows = trader.positions()
                if not rows:
                    return ToolResult(True, "SENTINAL ochgan pozitsiya yo'q (DEMO)")
                return ToolResult(True, "\n".join(
                    f"#{r['ticket']} {r['symbol']} {r['side']} {r['lot']} lot, ochilgan {r['open']}, SL {r['sl']}, "
                    f"TP {r['tp']}, hozirgi natija {r['profit']}" for r in rows))
            if action in ("check", "open"):
                res = trader.open(str(args.get("symbol") or ""), str(args.get("side") or ""),
                                  float(args.get("lot") or 0), float(args.get("sl") or 0),
                                  float(args["tp"]) if args.get("tp") else None, dry_run=(action == "check"))
            elif action == "close":
                res = trader.close(int(args.get("ticket") or 0))
            else:
                return ToolResult(False, "action: check, open, close yoki positions")
        except TradeRefused as exc:
            return ToolResult(False, f"Buyurtma YUBORILMADI: {exc}")
        except (TypeError, ValueError) as exc:
            return ToolResult(False, f"Parametr xatosi: {exc}")
        head = "BAJARILDI" if res["ok"] else "RAD ETILDI"
        if res.get("stage") == "order_check" and res["ok"]:
            head = "TEKSHIRUV O'TDI"
        return ToolResult(res["ok"], f"{head} ({res.get('stage')}): retcode {res.get('retcode')}, {res.get('comment')}"
                          + (f", narx {res.get('price')}, order {res.get('order')}, deal {res.get('deal')}"
                             if res.get("stage") == "order_send" and res["ok"] else ""))

    return await asyncio.to_thread(run)


MT5_ORDER_SCHEMA = {"type": "object", "required": ["action"], "properties": {
    "action": {"type": "string", "enum": ["check", "open", "close", "positions"],
               "description": "check = buyurtmani brokerda tekshirish (YUBORMAYDI); open = bozor buyurtmasi; "
                              "close = o'zimiz ochgan pozitsiyani yopish; positions = o'zimizning ochiq pozitsiyalar"},
    "symbol": {"type": "string"}, "side": {"type": "string", "enum": ["buy", "sell"]},
    "lot": {"type": "number", "description": "Hajm (default chegara 0.10)"},
    "sl": {"type": "number", "description": "Stop-loss narxi — MAJBURIY"}, "tp": {"type": "number"},
    "ticket": {"type": "integer", "description": "close uchun pozitsiya raqami"}}}
MT5_ORDER_DESCRIPTION = (
    "MT5 DEMO hisobda sinov savdosi. FAQAT DEMO: REAL/CONTEST hisobda kod rad etadi. open va close har safar Jamshidning "
    "tasdig'ini talab qiladi. SL majburiy, lot va ochiq pozitsiya soni cheklangan; faqat o'zimiz ochgan pozitsiyalar "
    "yopiladi. Avval action=check, keyin open. Natija (retcode) aynan aytiladi — muvaffaqiyatni o'ylab topma.")
