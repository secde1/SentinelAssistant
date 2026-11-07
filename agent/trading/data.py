"""Bozor ma'lumoti: OHLCV provayderlar, sifat tekshiruvi, iqtisodiy kalendar.

Qoidalar:
  • faqat YOPILGAN shamlar (hali shakllanayotgan sham tahlilga kirmaydi);
  • ma'lumot eskirgan / yetarli emas / buzuq bo'lsa — DataUnavailable: tahlil QILINMAYDI (o'ylab topilmaydi);
  • har natijada manba va vaqt belgisi saqlanadi.

TradingView'ning ochiq ma'lumot API'si yo'q — u faqat ko'rish/alert vositasi. Shuning uchun asosiy manba: Binance ochiq
market-data API (data-api.binance.vision — kalitsiz, faqat bozor ma'lumoti) va ixtiyoriy Twelve Data (forex/metall,
TWELVEDATA_API_KEY). Bu yerda buyurtma (order) API'si umuman yo'q.
"""
from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import httpx

TF_SECONDS = {"1m": 60, "1min": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


class DataUnavailable(Exception):
    """Ishonchli ma'lumot yo'q — tahlil/natija hisoblanmaydi."""


@dataclass(frozen=True)
class Candle:
    ts: datetime  # ochilish vaqti, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    seconds: int = 3600

    @property
    def end(self) -> datetime:
        return self.ts + timedelta(seconds=self.seconds)


@dataclass
class Bundle:
    symbol: str
    timeframe: str
    candles: list[Candle]
    source: str
    fetched_at: datetime
    warnings: list[str] = field(default_factory=list)

    @property
    def last_close_time(self) -> datetime:
        return self.candles[-1].end


class Provider(Protocol):
    name: str

    def klines(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
               start: datetime | None = None) -> list[Candle]: ...


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


class BinanceProvider:
    """Binance ochiq market-data (data-api.binance.vision): kalitsiz, faqat bozor ma'lumoti."""

    name = "Binance public market data (data-api.binance.vision/api/v3/klines)"
    base = "https://data-api.binance.vision/api/v3/klines"

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=20)

    def _get(self, params: dict) -> list:
        last = None
        for attempt in range(3):
            try:
                r = self.client.get(self.base, params=params)
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}: {r.text[:150]}"
                if r.status_code in (400, 404):
                    break
            except httpx.HTTPError as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))
        raise DataUnavailable(f"Binance: {last}")

    def klines(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
               start: datetime | None = None) -> list[Candle]:
        sec = TF_SECONDS[timeframe]
        out: list[Candle] = []
        params: dict = {"symbol": symbol, "interval": timeframe}
        if start is not None:  # oldinga qarab (natija kuzatuvi)
            cursor = _ms(start)
            while len(out) < limit:
                params.update(startTime=cursor, limit=min(1000, limit - len(out)))
                if end is not None:
                    params["endTime"] = _ms(end) - 1
                rows = self._get(params)
                batch = [self._candle(r, sec) for r in rows]
                out += batch
                if len(rows) < params["limit"]:
                    break
                cursor = _ms(batch[-1].ts) + sec * 1000
            return out
        end_ms = _ms(end) - 1 if end else None
        while len(out) < limit:  # orqaga qarab (tarix)
            params["limit"] = min(1000, limit - len(out))
            if end_ms is not None:
                params["endTime"] = end_ms
            rows = self._get(params)
            if not rows:
                break
            batch = [self._candle(r, sec) for r in rows]
            out = batch + out
            if len(rows) < params["limit"]:
                break
            end_ms = _ms(batch[0].ts) - 1
        return out

    @staticmethod
    def _candle(row: list, sec: int) -> Candle:
        return Candle(datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc), float(row[1]), float(row[2]),
                      float(row[3]), float(row[4]), float(row[5]), sec)


class TwelveDataProvider:
    name = "Twelve Data time_series API (api.twelvedata.com)"
    base = "https://api.twelvedata.com/time_series"
    intervals = {"1m": "1min", "1min": "1min", "5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h",
                 "1d": "1day"}

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise DataUnavailable("Twelve Data kaliti yo'q (.env: TWELVEDATA_API_KEY)")
        self.key = api_key
        self.client = client or httpx.Client(timeout=20)

    def klines(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
               start: datetime | None = None) -> list[Candle]:
        params = {"symbol": symbol, "interval": self.intervals[timeframe], "outputsize": min(5000, limit),
                  "timezone": "UTC", "apikey": self.key, "order": "ASC"}
        if end is not None:
            params["end_date"] = (end - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
        if start is not None:
            params["start_date"] = start.strftime("%Y-%m-%d %H:%M:%S")
        try:
            r = self.client.get(self.base, params=params)
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataUnavailable(f"Twelve Data: {type(exc).__name__}") from None
        if data.get("status") != "ok":
            raise DataUnavailable(f"Twelve Data: {str(data.get('message') or data)[:160]}")
        sec = TF_SECONDS[timeframe]
        out = []
        for v in data.get("values") or []:
            ts = datetime.strptime(v["datetime"][:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc) \
                if len(v["datetime"]) > 10 else datetime.strptime(v["datetime"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
            out.append(Candle(ts, float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"]),
                              float(v.get("volume") or 0), sec))
        out.sort(key=lambda c: c.ts)
        return out


class CSVProvider:
    """Tarixiy fayl: trading_memory/data/<SYMBOL>_<tf>.csv (ts,open,high,low,close,volume; ts — ISO yoki ms)."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.name = f"CSV ({self.folder})"

    def klines(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
               start: datetime | None = None) -> list[Candle]:
        path = self.folder / f"{symbol.replace('/', '')}_{timeframe}.csv"
        if not path.is_file():
            raise DataUnavailable(f"CSV yo'q: {path}")
        sec = TF_SECONDS[timeframe]
        out = []
        with path.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw = row["ts"]
                ts = datetime.fromtimestamp(int(raw) / 1000, tz=timezone.utc) if raw.isdigit() else \
                    datetime.fromisoformat(raw.replace("Z", "+00:00"))
                out.append(Candle(ts, float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"]),
                                  float(row.get("volume") or 0), sec))
        out = [c for c in out if (end is None or c.ts < end) and (start is None or c.ts >= start)]
        return out[:limit] if start is not None else out[-limit:]


# -------------------------------------------------------------------------------------------- sifat tekshiruvi
def validate(candles: list[Candle], timeframe: str, now: datetime, *, market: str = "crypto", need: int = 50,
             check_stale: bool = True) -> list[str]:
    """Xatolik bo'lsa DataUnavailable; kichik kamchiliklar — ogohlantirishlar ro'yxati."""
    sec = TF_SECONDS[timeframe]
    if len(candles) < need:
        raise DataUnavailable(f"sham yetarli emas: {len(candles)} < {need}")
    warnings = []
    gaps = 0
    for a, b in zip(candles, candles[1:]):
        if b.ts <= a.ts:
            raise DataUnavailable(f"vaqt tartibi buzilgan: {a.ts} -> {b.ts}")
        step = (b.ts - a.ts).total_seconds()
        if step != sec:
            gaps += int(step // sec) - 1
    for c in candles:
        vals = (c.open, c.high, c.low, c.close)
        if any(not math.isfinite(v) or v <= 0 for v in vals):
            raise DataUnavailable(f"noto'g'ri narx {c.ts}: {vals}")
        if c.high < max(c.open, c.close) - 1e-12 or c.low > min(c.open, c.close) + 1e-12:
            raise DataUnavailable(f"OHLC mantiqsiz {c.ts}: {vals}")
    if gaps:
        msg = f"{gaps} ta sham tushib qolgan"
        if market == "crypto" and gaps > max(2, len(candles) * 0.01):
            raise DataUnavailable(msg)
        warnings.append(msg + (" (bozor yopiq bo'lgan vaqt bo'lishi mumkin)" if market != "crypto" else ""))
    if check_stale:
        age = (now - candles[-1].end).total_seconds()
        if age > 2 * sec + 120:
            reason = "bozor yopiq yoki ma'lumot eskirgan" if market != "crypto" else "ma'lumot eskirgan"
            raise DataUnavailable(f"{reason}: oxirgi yopilgan sham {candles[-1].end.isoformat()}")
    return warnings


class MarketData:
    """Instrument -> provayder; faqat yopilgan va tekshirilgan shamlar."""

    def __init__(self, settings, providers: dict[str, Provider], clock=None):
        self.settings = settings
        self.providers = providers
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def provider_for(self, symbol: str) -> Provider:
        name = self.settings.instrument(symbol).get("provider", "binance")
        prov = self.providers.get(name)
        if prov is None:
            raise DataUnavailable(f"{symbol}: '{name}' provayderi sozlanmagan")
        return prov

    def history(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
                need: int = 50, check_stale: bool = True) -> Bundle:
        now = self.clock()
        prov = self.provider_for(symbol)
        raw = prov.klines(symbol, timeframe, limit + 1, end=end)
        candles = [c for c in raw if c.end <= (end or now)]  # faqat yopilgan shamlar
        market = self.settings.instrument(symbol).get("market", "crypto")
        warnings = validate(candles, timeframe, end or now, market=market, need=need,
                            check_stale=check_stale and end is None)
        return Bundle(symbol, timeframe, candles[-limit:], prov.name, now, warnings)

    def after(self, symbol: str, timeframe: str, start: datetime, limit: int = 1000) -> list[Candle]:
        """start dan keyingi YOPILGAN shamlar (natija kuzatuvi uchun)."""
        now = self.clock()
        raw = self.provider_for(symbol).klines(symbol, timeframe, limit, start=start)
        return [c for c in raw if c.ts >= start and c.end <= now]

    def fine(self, symbol: str, start: datetime, end: datetime) -> list[Candle]:
        """Sham ichidagi ketma-ketlikni aniqlash uchun mayda shamlar (1 daqiqa)."""
        tf = self.settings.instrument(symbol).get("fine_tf", "1m")
        minutes = int((end - start).total_seconds() // 60) + 1
        raw = self.provider_for(symbol).klines(symbol, tf, min(1000, max(1, minutes)), start=start, end=end)
        return [c for c in raw if start <= c.ts < end and c.end <= self.clock()]


# -------------------------------------------------------------------------------------------- iqtisodiy kalendar
class EconomicCalendar:
    """ForexFactory haftalik ochiq JSON (nfs.faireconomy.media). Mavjud bo'lmasa — "noma'lum" (taxmin qilinmaydi)."""

    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    name = "ForexFactory weekly calendar (nfs.faireconomy.media)"

    def __init__(self, cache_dir: Path, client: httpx.Client | None = None):
        self.cache_dir = Path(cache_dir)
        self.client = client or httpx.Client(timeout=15)

    def events(self) -> list[dict] | None:
        week = datetime.now(timezone.utc).strftime("%G-W%V")
        cache = self.cache_dir / f"calendar_{week}.json"
        if cache.is_file() and time.time() - cache.stat().st_mtime < 6 * 3600:
            try:
                return json.loads(cache.read_text(encoding="utf-8"))
            except ValueError:
                pass
        try:
            r = self.client.get(self.url)
            data = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            data = None
        if not isinstance(data, list):
            return json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return data

    def near(self, ts: datetime, hours: float = 2.0, currencies: tuple[str, ...] = ("USD",),
             impacts: tuple[str, ...] = ("High",)) -> list[dict] | None:
        evs = self.events()
        if evs is None:
            return None
        dates = []
        for e in evs:
            try:
                dates.append(datetime.fromisoformat(e["date"]))
            except (KeyError, ValueError):
                continue
        if not dates or not (min(dates) - timedelta(days=1) <= ts <= max(dates) + timedelta(days=1)):
            return None  # bu hafta fayli shu vaqtni qamramaydi — "hodisa yo'q" deb taxmin qilinmaydi
        out = []
        for e in evs:
            try:
                when = datetime.fromisoformat(e["date"])
            except (KeyError, ValueError):
                continue
            if e.get("country") in currencies and e.get("impact") in impacts and abs((when - ts).total_seconds()) <= \
                    hours * 3600:
                out.append({"title": e.get("title"), "country": e.get("country"), "impact": e.get("impact"),
                            "date": when.astimezone(timezone.utc).isoformat()})
        return out
