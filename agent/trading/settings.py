"""Tadqiqot sozlamalari: trading_memory/config/research_settings.json (birinchi ishga tushishda standart bilan yaratiladi).

Maxfiy narsa bu faylga YOZILMAYDI (Twelve Data kaliti faqat .env da: TWELVEDATA_API_KEY). Guruh chat_id maxfiy emas —
uni egasi /trading_guruh <id> buyrug'i bilan tasdiqlaydi (yoki .env: TRADING_GROUP_CHAT_ID).
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]

SUBDIRS = ("config", "database", "strategies", "analyses", "outcomes", "research", "experiments", "reports", "logs")

DEFAULTS: dict[str, Any] = {
    "timezone": "Asia/Tashkent",
    "daily_target": 10,
    "analysis_slots": ["09:00", "10:00", "11:30", "13:00", "14:30", "16:00", "17:30", "19:00", "20:30", "22:00"],
    "research_at": "08:30",
    "report_at": "23:30",
    "outcome_poll_sec": 600,
    # Har slot navbatdagi juftlikni oladi; ma'lumot bo'lmasa — keyingisiga o'tadi (tahlil o'ylab topilmaydi).
    "universe": [
        {"symbol": "BTCUSDT", "timeframe": "1h"}, {"symbol": "ETHUSDT", "timeframe": "1h"},
        {"symbol": "XAU/USD", "timeframe": "1h"}, {"symbol": "SOLUSDT", "timeframe": "1h"},
        {"symbol": "BTCUSDT", "timeframe": "4h"}, {"symbol": "EUR/USD", "timeframe": "1h"},
        {"symbol": "XRPUSDT", "timeframe": "1h"}, {"symbol": "ETHUSDT", "timeframe": "4h"},
        {"symbol": "BNBUSDT", "timeframe": "1h"}, {"symbol": "SOLUSDT", "timeframe": "4h"},
    ],
    # Xarajat modeli: spread (bps yoki narx birligida) + komissiya (% har tomonga).
    "instruments": {
        "BTCUSDT": {"provider": "binance", "market": "crypto", "spread_bps": 1.0, "commission_pct": 0.1, "fine_tf": "1m"},
        "ETHUSDT": {"provider": "binance", "market": "crypto", "spread_bps": 1.5, "commission_pct": 0.1, "fine_tf": "1m"},
        "SOLUSDT": {"provider": "binance", "market": "crypto", "spread_bps": 2.0, "commission_pct": 0.1, "fine_tf": "1m"},
        "XRPUSDT": {"provider": "binance", "market": "crypto", "spread_bps": 2.0, "commission_pct": 0.1, "fine_tf": "1m"},
        "BNBUSDT": {"provider": "binance", "market": "crypto", "spread_bps": 2.0, "commission_pct": 0.1, "fine_tf": "1m"},
        "XAU/USD": {"provider": "twelvedata", "market": "metal", "spread": 0.30, "commission_pct": 0.0, "fine_tf": "1min"},
        "EUR/USD": {"provider": "twelvedata", "market": "forex", "spread": 0.00012, "commission_pct": 0.0,
                    "fine_tf": "1min"},
    },
    "min_rr": 1.5,
    "validity_bars": 6,  # kirish sharti shuncha sham ichida bajarilmasa — NOT_TRIGGERED
    "max_hold_bars": 48,  # faol simulyatsiya shuncha shamdan keyin — EXPIRED
    "history_bars": 500,
    "library_universe": [{"symbol": "BTCUSDT", "timeframe": "1h"}, {"symbol": "ETHUSDT", "timeframe": "1h"},
                         {"symbol": "BTCUSDT", "timeframe": "4h"}],
    "library_refresh_days": 7,
    "backtest_bars": 2000,
    "missed_policy": {"analysis": "skip", "report": "run_on_startup", "research": "run_if_same_day"},
    "retry": {"attempts": 3, "delay_sec": 120, "slot_window_min": 45},
    # V22 signal tizimi. mode: off | dry (skanerlaydi, Telegramga yubormaydi) | live. Faqat PAPER trading.
    "monitor": {"enabled": True, "poll_sec": 60, "backfill_h": 48, "test_pending": False, "republish": []},  # V24: MT5 pozitsiya monitoringi (faqat o'qish)
    "signals": {"mode": "dry", "scan_sec": 900, "cooldown_h": 4, "tolerance_atr": 1.0,
                "universe": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "XAU/USD", "EUR/USD"]},
    "publish": {"enabled": True, "outcome_updates": True, "daily_report": True, "analyses": True},
    "group_chat_id": None,
    "group_title": None,
    "group_authorized_at": None,
    "research_topics": [
        "market structure", "technical analysis methods", "risk management", "statistical validation of trading "
        "strategies", "strategy performance evidence", "economic events and their market impact", "market volatility "
        "regimes", "common backtesting mistakes (look-ahead bias, overfitting, survivorship bias)",
    ],
}


def tz_from_name(name: str) -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 — tzdata yo'q bo'lsa
            pass
    return timezone(timedelta(hours=5), "UTC+05:00") if name == "Asia/Tashkent" else timezone.utc


@dataclass
class TradingMemory:
    root: Path

    def ensure(self) -> "TradingMemory":
        for d in SUBDIRS:
            (self.root / d).mkdir(parents=True, exist_ok=True)
        return self

    def __getattr__(self, name: str) -> Path:
        if name in SUBDIRS:
            return self.root / name
        raise AttributeError(name)

    @property
    def db_path(self) -> Path:
        return self.root / "database" / "trading_research.db"

    @property
    def settings_path(self) -> Path:
        return self.root / "config" / "research_settings.json"


class Settings:
    def __init__(self, memory: TradingMemory, env: dict | None = None):
        self.memory = memory
        self.env = env if env is not None else os.environ
        self.data = self._load()

    def _load(self) -> dict:
        data = copy.deepcopy(DEFAULTS)
        path = self.memory.settings_path
        if path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    data.update(saved)
            except (OSError, ValueError):
                pass
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def save(self) -> None:
        path = self.memory.settings_path
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def tz(self) -> tzinfo:
        return tz_from_name(self.data.get("timezone") or "Asia/Tashkent")

    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def local(self, dt: datetime) -> datetime:
        return dt.astimezone(self.tz)

    def instrument(self, symbol: str) -> dict:
        return dict(self.data["instruments"].get(symbol) or {"provider": "binance", "market": "crypto",
                                                               "spread_bps": 2.0, "commission_pct": 0.1})

    @property
    def private_chat_id(self) -> int | None:
        """Egasining SHAXSIY chati (monitoring va savdo tahlili faqat shu yerga). group_chat_id dan alohida saqlanadi."""
        pid = self.data.get("private_chat_id")
        return int(pid) if isinstance(pid, int) and pid > 0 else None

    @property
    def group_chat_id(self) -> int | None:
        raw = str(self.env.get("TRADING_GROUP_CHAT_ID") or "").strip()
        if raw.lstrip("-").isdigit():
            return int(raw)
        gid = self.data.get("group_chat_id")
        return int(gid) if isinstance(gid, int) or (isinstance(gid, str) and gid.lstrip("-").isdigit()) else None

    def authorize_group(self, chat_id: int, title: str | None = None) -> None:
        self.data["group_chat_id"] = int(chat_id)
        self.data["group_title"] = title
        self.data["group_authorized_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()

    def spread_price(self, symbol: str, price: float) -> float:
        inst = self.instrument(symbol)
        if inst.get("spread") is not None:
            return float(inst["spread"])
        return price * float(inst.get("spread_bps", 0.0)) / 10000.0

    def commission_rate(self, symbol: str) -> float:
        return float(self.instrument(symbol).get("commission_pct", 0.0)) / 100.0
