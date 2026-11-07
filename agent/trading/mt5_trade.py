"""MT5 DEMO savdo (V20) — sinov uchun, FAQAT DEMO hisobda, har bir buyurtma egasining tasdig'i bilan (gate DANGER).

Kod darajasidagi cheklovlar (env bilan yumshatilmaydi):
  • har buyurtmadan oldin hisob turi qayta o'qiladi: DEMO bo'lmasa (REAL, CONTEST, noma'lum) — rad etiladi;
  • stop-loss majburiy va narxning to'g'ri tomonida; lot MT5_MAX_LOT (default 0.10) dan oshmaydi; bir vaqtda
    MT5_MAX_POSITIONS (default 3) tadan ko'p ochiq pozitsiya yo'q;
  • faqat o'zimizning magic raqamli pozitsiyalar ko'rinadi va yopiladi (qo'lda ochilgan yoki EA pozitsiyalariga tegilmaydi);
  • oldin order_check, keyin order_send; natija (retcode) aynan qaytariladi, muvaffaqiyat o'ylab topilmaydi;
  • hisob raqami, ism, balans jurnalga yozilmaydi; Algo Trading tugmasi va hisob sozlamasi o'zgartirilmaydi.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .data import DataUnavailable
from .mt5_connector import _LOCK, MT5Connector

MAGIC = 20260711
COMMENT = "SENTINAL-demo"
ALLOWED_TRADE = frozenset({"order_check", "order_send", "positions_get", "symbol_info", "symbol_info_tick",
                           "account_info", "last_error"})
RETCODE_DONE = (10009, 10008)  # TRADE_RETCODE_DONE, TRADE_RETCODE_PLACED


class TradeRefused(Exception):
    """Buyurtma yuborilmadi (xavfsizlik cheklovi yoki parametr xatosi)."""


class _TradeAPI:
    """MetaTrader5 moduli ustida tor qobiq: faqat ALLOWED_TRADE funksiyalari va KATTA_HARFLI konstantalar."""

    def __init__(self, module):
        self._m = module

    def __getattr__(self, name: str):
        if name.isupper() or name in ALLOWED_TRADE:
            return getattr(self._m, name)
        raise PermissionError(f"MT5.{name} — savdo qobig'ida ruxsat etilmagan")


class DemoTrader:
    def __init__(self, connector: MT5Connector, *, max_lot: float = 0.10, max_positions: int = 3,
                 log_file: Path | None = None):
        self.c = connector
        self.max_lot = max_lot
        self.max_positions = max_positions
        self.log_file = Path(log_file) if log_file else None

    @classmethod
    def from_env(cls, connector: MT5Connector, env, log_file: Path | None = None) -> "DemoTrader":
        def num(key, default, cast):
            try:
                return cast(str(env.get(key) or default))
            except ValueError:
                return default
        return cls(connector, max_lot=num("MT5_MAX_LOT", 0.10, float), max_positions=num("MT5_MAX_POSITIONS", 3, int),
                   log_file=log_file)

    # ------------------------------------------------------------------------------------------ yordamchilar
    def _api(self) -> tuple[_TradeAPI, str]:
        """Ulanadi va HAR SAFAR hisob DEMO ekanini tekshiradi."""
        try:
            self.c.connect()
        except DataUnavailable as exc:
            if "REAL hisob" in str(exc):
                raise TradeRefused("REAL hisob ochiq — savdo faqat DEMO hisobda (REAL bilan keyingi qaror)") from exc
            raise TradeRefused(str(exc)) from exc
        api = _TradeAPI(self.c._module)
        ai = api.account_info()
        if ai is None:
            raise TradeRefused("MT5: hisob ma'lumoti o'qilmadi")
        if ai.trade_mode != 0:
            raise TradeRefused(f"Hisob DEMO emas (trade_mode={ai.trade_mode}) — buyurtma yuborilmaydi")
        return api, ai.server

    def _log(self, event: dict) -> None:
        if not self.log_file:
            return
        event = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), **event}
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        with self.log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    @staticmethod
    def _filling(api: _TradeAPI, info) -> int:
        mode = getattr(info, "filling_mode", 0)
        if mode & 2:
            return api.ORDER_FILLING_IOC
        if mode & 1:
            return api.ORDER_FILLING_FOK
        return api.ORDER_FILLING_RETURN

    @staticmethod
    def _own(api: _TradeAPI) -> list:
        return [p for p in (api.positions_get() or []) if p.magic == MAGIC]

    @staticmethod
    def _result(res, api: _TradeAPI) -> dict:
        if res is None:
            return {"ok": False, "retcode": None, "comment": f"javob yo'q {api.last_error()}"}
        return {"ok": res.retcode in RETCODE_DONE, "retcode": res.retcode, "comment": getattr(res, "comment", ""),
                "order": getattr(res, "order", 0), "deal": getattr(res, "deal", 0),
                "price": getattr(res, "price", 0.0), "volume": getattr(res, "volume", 0.0)}

    # ------------------------------------------------------------------------------------------ amallar
    def positions(self) -> list[dict]:
        with _LOCK:
            api, _ = self._api()
            return [{"ticket": p.ticket, "symbol": p.symbol, "side": "buy" if p.type == 0 else "sell",
                     "lot": p.volume, "open": p.price_open, "sl": p.sl, "tp": p.tp, "profit": p.profit}
                    for p in self._own(api)]

    def open(self, symbol: str, side: str, lot: float, sl: float, tp: float | None = None, *,
             dry_run: bool = False) -> dict:
        side = side.lower()
        if side not in ("buy", "sell"):
            raise TradeRefused("side: buy yoki sell")
        if not sl:
            raise TradeRefused("stop-loss (sl) majburiy")
        if not 0 < lot <= self.max_lot:
            raise TradeRefused(f"lot {lot} ruxsat etilgan chegaradan tashqarida (max {self.max_lot})")
        with _LOCK:
            api, server = self._api()
            try:
                name = self.c.resolve(symbol)
                info = self.c._ensure_selected(name)
            except DataUnavailable as exc:
                raise TradeRefused(str(exc)) from exc
            step = info.volume_step
            if lot < info.volume_min or (step and abs(lot / step - round(lot / step)) > 1e-6):
                raise TradeRefused(f"lot {lot}: broker minimumi {info.volume_min}, qadam {step}")
            tick = api.symbol_info_tick(name)
            if tick is None or not tick.ask or not tick.bid:
                raise TradeRefused(f"{name}: joriy narx yo'q (bozor yopiq bo'lishi mumkin)")
            price = tick.ask if side == "buy" else tick.bid
            if not (sl < price if side == "buy" else sl > price):
                raise TradeRefused(f"SL {sl} narxning noto'g'ri tomonida (narx {price}, {side})")
            if tp is not None and not (tp > price if side == "buy" else tp < price):
                raise TradeRefused(f"TP {tp} narxning noto'g'ri tomonida (narx {price}, {side})")
            if not dry_run and len(self._own(api)) >= self.max_positions:
                raise TradeRefused(f"ochiq pozitsiyalar chegarasi: {self.max_positions}")
            req = {"action": api.TRADE_ACTION_DEAL, "symbol": name, "volume": lot,
                   "type": api.ORDER_TYPE_BUY if side == "buy" else api.ORDER_TYPE_SELL, "price": price,
                   "sl": sl, "deviation": 20, "magic": MAGIC, "comment": COMMENT,
                   "type_time": api.ORDER_TIME_GTC, "type_filling": self._filling(api, info)}
            if tp is not None:
                req["tp"] = tp
            chk = api.order_check(req)
            if chk is None or chk.retcode != 0:
                out = {"ok": False, "stage": "order_check", "retcode": getattr(chk, "retcode", None),
                       "comment": getattr(chk, "comment", f"javob yo'q {api.last_error()}")}
                self._log({"event": "open_rejected", "server": server, "symbol": name, "side": side, "lot": lot, **out})
                return out
            if dry_run:
                return {"ok": True, "stage": "order_check", "retcode": 0, "symbol": name, "price": price,
                        "comment": "tekshiruv o'tdi, buyurtma YUBORILMADI"}
            res = self._result(api.order_send(req), api)
            res.update(stage="order_send", symbol=name, side=side)
            self._log({"event": "open", "server": server, "symbol": name, "side": side, "lot": lot, "sl": sl,
                       "tp": tp, **res})
            return res

    def close(self, ticket: int) -> dict:
        with _LOCK:
            api, server = self._api()
            pos = next((p for p in self._own(api) if p.ticket == ticket), None)
            if pos is None:
                raise TradeRefused(f"#{ticket}: bizning (SENTINAL) pozitsiyamiz emas yoki topilmadi — tegilmaydi")
            info = self.c._ensure_selected(pos.symbol)
            tick = api.symbol_info_tick(pos.symbol)
            if tick is None:
                raise TradeRefused(f"{pos.symbol}: joriy narx yo'q")
            buy = pos.type == 0
            req = {"action": api.TRADE_ACTION_DEAL, "symbol": pos.symbol, "volume": pos.volume,
                   "type": api.ORDER_TYPE_SELL if buy else api.ORDER_TYPE_BUY, "position": pos.ticket,
                   "price": tick.bid if buy else tick.ask, "deviation": 20, "magic": MAGIC, "comment": COMMENT,
                   "type_time": api.ORDER_TIME_GTC, "type_filling": self._filling(api, info)}
            res = self._result(api.order_send(req), api)
            res.update(stage="order_send", symbol=pos.symbol, ticket=ticket)
            self._log({"event": "close", "server": server, **res})
            return res
