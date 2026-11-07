"""TradingService — bir joyda: xotira, sozlamalar, baza, strategiyalar, bozor ma'lumoti. Bot, jadval, tool va
dashboard shu orqali ishlaydi. Sinxron metodlar (HTTP/hisob) — chaqiruvchi asyncio.to_thread bilan ishlatadi."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import analysis as analysis_mod
from . import analytics, backtest, report, review
from .data import BinanceProvider, CSVProvider, DataUnavailable, EconomicCalendar, MarketData, TwelveDataProvider
from .db import TradingDB, dumps, utcnow
from .outcomes import update_one
from .settings import Settings, TradingMemory
from .strategies import Registry

log = logging.getLogger(__name__)


class TradingService:
    def __init__(self, home: Path, env: dict | None = None, providers: dict | None = None, clock=None,
                 calendar: EconomicCalendar | None = None):
        self.memory = TradingMemory(Path(home) / "trading_memory").ensure()
        self.env = env if env is not None else os.environ
        self.settings = Settings(self.memory, self.env)
        self.db = TradingDB(self.memory.db_path)
        self.registry = Registry(self.db, self.memory.strategies / "strategy_registry.json")
        self.registry.sync_defaults()
        if providers is None:
            providers = {"binance": BinanceProvider(), "csv": CSVProvider(self.memory.root / "data")}
            key = str(self.env.get("TWELVEDATA_API_KEY") or "").strip()
            if key:
                providers["twelvedata"] = TwelveDataProvider(key)
            if sys.platform == "win32":  # V22: MT5 (faqat o'qish). Terminal yopiq bo'lsa — DataUnavailable, boshqa narsa buzilmaydi
                from .mt5_connector import MT5Provider
                providers["mt5"] = MT5Provider(self.mt5)
                self._migrate_forex_provider(providers)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.market = MarketData(self.settings, providers, self.clock)
        self.calendar = calendar if calendar is not None else EconomicCalendar(self.memory.research)
        if not self.db.get_meta("installed_at"):  # o'rnatilishdan oldingi slotlar "o'tkazib yuborilgan" sanalmaydi
            self.db.set_meta("installed_at", self.clock().isoformat(timespec="seconds"))

    def _migrate_forex_provider(self, providers: dict) -> None:
        """Twelve Data kaliti yo'q bo'lsa, XAU/USD va EUR/USD ni MT5 ga o'tkazadi (saqlangan sozlama o'zgaradi)."""
        changed = False
        for sym in ("XAU/USD", "EUR/USD"):
            inst = self.settings.data.get("instruments", {}).get(sym)
            if inst and inst.get("provider") == "twelvedata" and "twelvedata" not in providers:
                inst["provider"] = "mt5"
                changed = True
        if changed:
            self.settings.save()

    @property
    def mt5(self):
        """MT5 ulanishi (faqat o'qish). Bitta nusxa: MetaTrader5 paketi jarayonda global."""
        if getattr(self, "_mt5", None) is None:
            from .mt5_connector import MT5Connector
            self._mt5 = MT5Connector.from_env(self.env, state_file=self.memory.root / "config" / "mt5_state.json")
        return self._mt5

    @property
    def mt5_trader(self):
        """MT5 DEMO savdo (V20): faqat DEMO hisob, har buyurtma tasdiq bilan."""
        if getattr(self, "_mt5_trader", None) is None:
            from .mt5_trade import DemoTrader
            self._mt5_trader = DemoTrader.from_env(self.mt5, self.env, log_file=self.memory.root / "mt5_demo_trades.jsonl")
        return self._mt5_trader

    @property
    def installed_at(self) -> datetime:
        return datetime.fromisoformat(self.db.get_meta("installed_at"))

    # ------------------------------------------------------------------ tahlil
    def create_analysis(self, symbol: str, timeframe: str) -> dict:
        res = analysis_mod.build(self.db, self.settings, self.market, self.registry, symbol, timeframe, self.clock(),
                                 memory=self.memory)
        return res.analysis

    def analysis_for_slot(self, local_day: str, slot: int) -> dict:
        """Slot uchun navbatdagi juftlik; ma'lumot yo'q bo'lsa — keyingisi. Hech biri bo'lmasa — DataUnavailable."""
        uni = self.settings["universe"]
        base = (date.fromisoformat(local_day).toordinal() * int(self.settings["daily_target"]) + slot) % len(uni)
        errors = []
        for k in range(len(uni)):
            item = uni[(base + k) % len(uni)]
            provider = self.settings.instrument(item["symbol"]).get("provider", "binance")
            if provider not in self.market.providers:
                errors.append(f"{item['symbol']}: '{provider}' sozlanmagan")
                continue  # sozlama holati (masalan Twelve Data kaliti yo'q) — ma'lumot sifati ogohlantirishi emas
            try:
                return self.create_analysis(item["symbol"], item["timeframe"])
            except DataUnavailable as exc:
                errors.append(f"{item['symbol']} {item['timeframe']}: {exc}")
                self.db.warn(item["symbol"], item["timeframe"], "data_unavailable", str(exc))
        raise DataUnavailable("hech bir instrument uchun ishonchli ma'lumot yo'q: " + " | ".join(errors[:4]))

    def track_manual(self, *, symbol: str, timeframe: str, direction: str, entry_type: str, entry: float, sl: float,
                     tp: float, valid_hours: float, note: str, source: str = "chat") -> dict:
        """Egasi yoki suhbatda qo'lda tuzilgan ssenariyni kuzatuvga olish. Strategiya statistikasi buzilmasin deb
        MANUAL v0 sifatida alohida yoziladi; bozor ma'lumoti (oxirgi yopilgan sham) tekshiriladi."""
        import hashlib
        from datetime import timedelta

        from .analysis import LIMITATIONS, new_analysis_id, session_of
        direction = direction.upper()
        if direction not in ("LONG", "SHORT"):
            raise ValueError("direction: LONG yoki SHORT")
        allowed = {"LONG": ("buy_stop", "buy_limit", "next_open"), "SHORT": ("sell_stop", "sell_limit", "next_open")}
        if entry_type not in allowed[direction]:
            raise ValueError(f"{direction} uchun entry_type: {', '.join(allowed[direction])}")
        if (direction == "LONG" and not sl < entry < tp) or (direction == "SHORT" and not tp < entry < sl):
            raise ValueError("darajalar mantiqsiz: LONG uchun SL < kirish < TP, SHORT uchun TP < kirish < SL")
        bundle = self.market.history(symbol, timeframe, 50, need=20)
        last = bundle.candles[-1].close
        if abs(entry - last) / last > 0.25:
            raise ValueError(f"kirish {entry} hozirgi narxdan ({last}) juda uzoq — xato kiritilgan bo'lishi mumkin")
        now = self.clock()
        local = self.settings.local(now)
        day = local.strftime("%Y-%m-%d")
        aid = new_analysis_id(self.db, day)
        spread = self.settings.spread_price(symbol, last)
        comm = self.settings.commission_rate(symbol)
        risk = abs(entry - sl)
        rr = abs(tp - entry) / risk
        record = {
            "analysis_id": aid, "created_at": now.isoformat(timespec="seconds"), "local_date": day,
            "timezone": self.settings.get("timezone"), "local_time": local.isoformat(timespec="seconds"),
            "symbol": symbol, "timeframe": timeframe, "session": session_of(now), "kind": "TRADE",
            "regime": {"trend": "MANUAL", "volatility": "—", "note": "qo'lda kiritilgan ssenariy — rejim hisoblanmagan"},
            "structure": f"Qo'lda kiritilgan ssenariy ({source}): {note[:300]}", "strategy_id": "MANUAL",
            "strategy_version": 0, "strategy_name": "Manual scenario (qo'lda)", "direction": direction,
            "entry_type": entry_type, "entry": entry, "sl": sl, "tp": tp, "rr": round(rr, 2),
            "rr_net": round(rr - (comm * 2 * entry + spread) / risk, 2),
            "invalidation": {"type": "close_below" if direction == "LONG" else "close_above", "level": sl,
                             "text": "kirishdan oldin narx SL darajasidan o'tib yopilsa"},
            "valid_until": (now + timedelta(hours=valid_hours)).isoformat(timespec="seconds"),
            "max_hold_bars": int(self.settings["max_hold_bars"]),
            "evidence": {"last_close": last, "note": note[:500]}, "assumptions": ["egasi/suhbat tomonidan berilgan darajalar"],
            "data_source": bundle.source, "data_ts": bundle.last_close_time.isoformat(),
            "data_fetched_at": bundle.fetched_at.isoformat(timespec="seconds"), "last_close": last,
            "costs": {"spread": spread, "commission_pct_per_side": comm * 100},
            "limitations": LIMITATIONS + ["Bu tizim strategiyasi emas — qo'lda kiritilgan; statistikada MANUAL alohida."],
        }
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        record["content_hash"] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        self.db.insert_analysis({**record, "payload": payload})
        day_dir = self.memory.analyses / day
        day_dir.mkdir(parents=True, exist_ok=True)
        with open(day_dir / f"{aid}.json", "x", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, indent=1, default=str))
        return record

    # ------------------------------------------------------------------ natijalar
    def open_trade_rows(self) -> list[dict]:
        return self.db.query("SELECT a.* FROM analyses a LEFT JOIN outcomes o ON o.analysis_id=a.analysis_id "
                             "WHERE a.kind='TRADE' AND (o.status IS NULL OR o.status IN ('PENDING','ACTIVE_SIMULATION')) "
                             "ORDER BY a.created_at")

    def update_outcomes(self) -> list[tuple[dict, str]]:
        changes = []
        for row in self.open_trade_rows():
            try:
                status, _note = update_one(self.db, self.market, self.settings, row)
            except Exception:  # noqa: BLE001 — bitta tahlil xatosi boshqalarini to'xtatmasin
                log.exception("trading natija yangilanmadi: %s", row["analysis_id"])
                continue
            if status:
                changes.append((row, status))
                if status == "SL_HIT":
                    try:
                        review.review_sl(self.db, self.market, self.settings, self.registry, row["analysis_id"],
                                         self.calendar)
                    except Exception:  # noqa: BLE001
                        log.exception("SL tahlili bajarilmadi: %s", row["analysis_id"])
        return changes

    # ------------------------------------------------------------------ hisobot va statistika
    def daily_report(self, day: str) -> tuple[str, dict]:
        return report.daily(self.db, self.settings, day, self.memory)

    def weekly_report(self, end_day: str) -> tuple[str, dict]:
        return report.weekly(self.db, self.settings, end_day, self.memory)

    def performance(self, date_from: str | None = None, date_to: str | None = None) -> dict:
        return analytics.performance(self.db, date_from, date_to)

    def local_today(self) -> str:
        return self.settings.local(self.clock()).strftime("%Y-%m-%d")

    def status_text(self) -> str:
        today = self.local_today()
        n = self.db.one("SELECT COUNT(*) AS n FROM analyses WHERE local_date=?", (today,))["n"]
        open_n = len(self.open_trade_rows())
        s = self.performance()["summary"]
        gid = self.settings.group_chat_id
        last = self.db.query("SELECT analysis_id, symbol, timeframe, kind, strategy_id, direction FROM analyses "
                             "ORDER BY created_at DESC LIMIT 3")
        lines = ["🧪 Trading tadqiqoti (paper trading)",
                 f"Guruh: {gid if gid else 'ulanmagan — /trading_guruh <chat_id>'}",
                 f"Bugun: {n}/{self.settings['daily_target']} tahlil; ochiq ssenariylar: {open_n}",
                 f"Umumiy: hal bo'lgan {s['resolved']}, TP {s['tp_hits']}, SL {s['sl_hits']}, yutuq foizi "
                 f"{s['win_rate'] if s['win_rate'] is not None else '—'}%, expectancy "
                 f"{s['expectancy_r'] if s['expectancy_r'] is not None else '—'}R"]
        lines += [f"  • {r['analysis_id']} {r['symbol']} {r['timeframe']} {r['kind']}"
                  + (f" {r['strategy_id']} {r['direction']}" if r["kind"] == "TRADE" else "") for r in last]
        return "\n".join(lines)

    # ------------------------------------------------------------------ tadqiqot manbalari
    def record_source(self, *, topic: str, url: str, title: str, summary: str, evidence_type: str,
                      publisher: str = "", published_at: str = "", task_id: str = "") -> bool:
        if evidence_type not in ("verified_finding", "opinion", "hypothesis"):
            raise ValueError("evidence_type: verified_finding | opinion | hypothesis")
        if not url.startswith(("http://", "https://")):
            raise ValueError("url http(s) bo'lishi kerak")
        rec = {"topic": topic, "url": url, "title": title, "publisher": publisher, "published_at": published_at or None,
               "retrieved_at": utcnow(), "summary": summary[:2000], "evidence_type": evidence_type, "task_id": task_id}
        cur = self.db.execute("INSERT OR IGNORE INTO research_sources(topic, url, title, publisher, published_at, "
                              "retrieved_at, summary, evidence_type, task_id) VALUES(?,?,?,?,?,?,?,?,?)",
                              tuple(rec.values()))
        if cur.rowcount:
            with (self.memory.research / "sources.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return bool(cur.rowcount)

    # ------------------------------------------------------------------ eksperimentlar
    def _candles(self, symbol: str, timeframe: str, bars: int):
        return self.market.history(symbol, timeframe, bars, need=600, check_stale=False).candles

    def run_experiment(self, strategy_id: str, params_patch: dict, problem: str, hypothesis: str, symbol: str,
                       timeframe: str, created_by: str = "agent") -> dict:
        base = self.registry.active().get(strategy_id)
        if base is None:
            raise ValueError(f"faol strategiya yo'q: {strategy_id}")
        cand = self.registry.create_version(strategy_id, params_patch, f"eksperiment: {hypothesis[:200]}", created_by)
        candles = self._candles(symbol, timeframe, int(self.settings["backtest_bars"]))
        spread_fn = lambda p: self.settings.spread_price(symbol, p)  # noqa: E731
        comm = self.settings.commission_rate(symbol)
        base_res = backtest.walk_forward(base, candles, spread_fn=spread_fn, commission=comm)
        cand_res = backtest.walk_forward(cand, candles, spread_fn=spread_fn, commission=comm)
        rec = backtest.record_experiment(self.db, self.memory, strategy_id=strategy_id, base=base, cand=cand,
                                         problem=problem, hypothesis=hypothesis,
                                         data_info={"symbol": symbol, "timeframe": timeframe,
                                                    "source": self.market.provider_for(symbol).name,
                                                    **base_res["periods"]},
                                         costs={"spread_model": self.settings.instrument(symbol),
                                                "commission_per_side": comm},
                                         base_res=base_res, cand_res=cand_res)
        if rec["verdict"] != "supported":
            self.db.execute("UPDATE strategies SET status='rejected' WHERE strategy_id=? AND version=?",
                            (strategy_id, cand.version))
            self.registry.export()
        return rec

    def refresh_library(self, symbol: str = "BTCUSDT", timeframe: str = "1h") -> list[dict]:
        candles = self._candles(symbol, timeframe, int(self.settings["backtest_bars"]))
        out = []
        for spec in self.registry.active().values():
            m = backtest.library_stats(self.db, spec, symbol, timeframe, candles,
                                       spread_fn=lambda p: self.settings.spread_price(symbol, p),
                                       commission=self.settings.commission_rate(symbol))
            out.append({"strategy_id": spec.strategy_id, "version": spec.version, **m})
        self.db.set_meta("library_refreshed", self.clock().isoformat(timespec="seconds"))
        return out

    def snapshot(self) -> str:
        return dumps({"settings": self.settings.data, "strategies": self.registry.all()})
