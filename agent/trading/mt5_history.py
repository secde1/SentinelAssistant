"""MT5 pozitsiya va bitim tarixini FAQAT O'QISH (V24): ochiq pozitsiyalar, yopilgan bitimlar, yopilish sababi.

Alohida tor qobiq (_HistoryAPI): faqat ro'yxatdagi O'QISH funksiyalari; buyurtma yuborish/o'zgartirish yo'q (test AST orqali
tekshiradi). Ulanish va hisob turi tekshiruvi MT5Connector'da (REAL hisobda ulanmaydi). Vaqtlar broker server vaqtida —
connector.server_offset bilan UTC ga o'giriladi; offset aniqlanmasa vaqt taxmin qilinmaydi (DataUnavailable).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .data import DataUnavailable
from .mt5_connector import _LOCK, MT5Connector

ALLOWED_HISTORY = frozenset({"history_deals_get", "history_orders_get", "positions_get", "last_error"})
# MT5 DEAL_REASON_* (rasmiy qiymatlar)
DEAL_REASONS = {0: "CLIENT", 1: "MOBILE", 2: "WEB", 3: "EXPERT", 4: "SL", 5: "TP", 6: "STOP_OUT", 7: "ROLLOVER",
                8: "VMARGIN", 9: "SPLIT"}
DEAL_ENTRY = {0: "IN", 1: "OUT", 2: "INOUT", 3: "OUT_BY"}
DEAL_TYPE = {0: "BUY", 1: "SELL"}


class _HistoryAPI:
    def __init__(self, module):
        self._m = module

    def __getattr__(self, name: str):
        if name in ALLOWED_HISTORY:
            return getattr(self._m, name)
        raise PermissionError(f"MT5.{name} — tarix qobig'ida ruxsat etilmagan (faqat o'qish)")


@dataclass
class Deal:
    ticket: int
    order: int
    position_id: int
    time: datetime
    type: str
    entry: str
    reason: str
    reason_code: int
    symbol: str
    volume: float
    price: float
    commission: float
    swap: float
    profit: float
    fee: float
    magic: int
    comment: str

    @property
    def net(self) -> float:
        return round(self.profit + self.commission + self.swap + self.fee, 2)


def _deal(d, off: int) -> Deal:
    return Deal(int(d.ticket), int(d.order), int(d.position_id),
                datetime.fromtimestamp(int(d.time_msc) / 1000 - off, tz=timezone.utc) if getattr(d, "time_msc", 0)
                else datetime.fromtimestamp(int(d.time) - off, tz=timezone.utc),
                DEAL_TYPE.get(int(d.type), str(d.type)), DEAL_ENTRY.get(int(d.entry), str(d.entry)),
                DEAL_REASONS.get(int(d.reason), f"UNKNOWN({d.reason})"), int(d.reason), str(d.symbol), float(d.volume),
                float(d.price), float(d.commission), float(d.swap), float(d.profit), float(getattr(d, "fee", 0.0)),
                int(d.magic), str(getattr(d, "comment", "")))


class MT5History:
    def __init__(self, connector: MT5Connector):
        self.c = connector

    def _api(self) -> tuple[_HistoryAPI, int]:
        self.c.connect()
        names = tuple(s for s in ("BTCUSDm", "ETHUSDm", "EURUSDm") if s in self.c._symbols.values())
        off = self.c.server_offset(names or ())
        return _HistoryAPI(self.c._module), off

    def deals_of_position(self, position_id: int) -> list[Deal]:
        """Bitta pozitsiyaning barcha bitimlari (IN va OUT), vaqt tartibida."""
        with _LOCK:
            api, off = self._api()
            rows = api.history_deals_get(position=int(position_id))
            if rows is None:
                raise DataUnavailable(f"MT5 tarixi o'qilmadi ({api.last_error()})")
            return sorted((_deal(d, off) for d in rows), key=lambda d: (d.time, d.ticket))

    def deals_between(self, start: datetime, end: datetime) -> list[Deal]:
        with _LOCK:
            api, off = self._api()

            def srv(dt: datetime) -> datetime:
                return datetime.fromtimestamp(dt.timestamp() + off, tz=timezone.utc)
            rows = api.history_deals_get(srv(start), srv(end))
            if rows is None:
                raise DataUnavailable(f"MT5 tarixi o'qilmadi ({api.last_error()})")
            return sorted((_deal(d, off) for d in rows if int(d.type) in DEAL_TYPE), key=lambda d: (d.time, d.ticket))

    def open_positions(self) -> list[dict]:
        with _LOCK:
            api, off = self._api()
            rows = api.positions_get()
            if rows is None:
                raise DataUnavailable(f"MT5 pozitsiyalari o'qilmadi ({api.last_error()})")
            return [{"ticket": int(p.ticket), "symbol": p.symbol, "side": "BUY" if int(p.type) == 0 else "SELL",
                     "volume": float(p.volume), "price_open": float(p.price_open), "sl": float(p.sl), "tp": float(p.tp),
                     "profit": float(p.profit), "swap": float(p.swap), "magic": int(p.magic),
                     "time": datetime.fromtimestamp(int(p.time) - off, tz=timezone.utc)} for p in rows]

    def contract_size(self, symbol: str) -> float | None:
        with _LOCK:
            self.c.connect()
            info = self.c.mt5.symbol_info(symbol)
            return float(info.trade_contract_size) if info is not None else None

    def currency(self) -> str:
        with _LOCK:
            self.c.connect()
            ai = self.c.mt5.account_info()
            return str(ai.currency) if ai is not None and getattr(ai, "currency", None) else "USD"

    def orders_of_position(self, position_id: int) -> list[dict]:
        with _LOCK:
            api, off = self._api()
            rows = api.history_orders_get(position=int(position_id))
            return [{"ticket": int(o.ticket), "type": int(o.type), "state": int(o.state), "reason": int(o.reason),
                     "price_open": float(o.price_open), "price_current": float(o.price_current), "sl": float(o.sl),
                     "tp": float(o.tp), "volume_initial": float(o.volume_initial),
                     "time_setup": datetime.fromtimestamp(int(o.time_setup) - off, tz=timezone.utc),
                     "time_done": datetime.fromtimestamp(int(o.time_done) - off, tz=timezone.utc),
                     "comment": str(o.comment)} for o in (rows or [])]


def summarize(deals: list[Deal]) -> dict | None:
    """Pozitsiya bitimlaridan yakuniy natija. Yopilmagan bo'lsa None (taxmin qilinmaydi)."""
    ins = [d for d in deals if d.entry == "IN"]
    outs = [d for d in deals if d.entry in ("OUT", "OUT_BY", "INOUT")]
    if not ins or not outs:
        return None
    vol_in, vol_out = sum(d.volume for d in ins), sum(d.volume for d in outs)
    if vol_out + 1e-9 < vol_in:
        return None  # qisman yopilgan — hali to'liq yopilmagan
    first, last = ins[0], outs[-1]
    return {"position_id": first.position_id, "symbol": first.symbol, "direction": "BUY" if first.type == "BUY" else "SELL",
            "volume": vol_in, "entry_price": sum(d.price * d.volume for d in ins) / vol_in,
            "exit_price": sum(d.price * d.volume for d in outs) / vol_out, "opened_at": first.time, "closed_at": last.time,
            "duration_s": int((last.time - first.time).total_seconds()), "reason": last.reason,
            "reason_code": last.reason_code, "profit": round(sum(d.profit for d in deals), 2),
            "commission": round(sum(d.commission for d in deals), 2), "swap": round(sum(d.swap for d in deals), 2),
            "fee": round(sum(d.fee for d in deals), 2), "net": round(sum(d.net for d in deals), 2),
            "magic": first.magic, "in_deal": first.ticket, "out_deal": last.ticket, "order_in": first.order,
            "order_out": last.order, "comment": last.comment}


def fmt_duration(sec: int) -> str:
    d = timedelta(seconds=sec)
    h, rem = divmod(int(d.total_seconds()), 3600)
    return f"{h} soat {rem // 60} daqiqa" if h else f"{rem // 60} daqiqa {rem % 60} soniya"
