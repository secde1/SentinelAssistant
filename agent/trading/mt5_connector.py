"""MetaTrader 5 — FAQAT O'QISH bozor ma'lumoti (V19), rasmiy MetaTrader5 Python paketi orqali.

Xavfsizlik (kod darajasida):
  • paketga faqat ReadOnlyMT5 orqali murojaat qilinadi: ruxsat ro'yxatidan tashqari funksiya (buyurtma yuborish va
    tekshirish, pozitsiya va buyurtmalar ro'yxati, savdo tarixi ...) chaqirilsa — PermissionError. Bu modulda buyurtma
    kodi yo'q (test AST orqali tekshiradi);
  • initialize() ga login/parol/server BERILMAYDI — terminalda ochiq turgan hisob ishlatiladi. Hisob raqami, ism, balans
    saqlanmaydi va jurnalga yozilmaydi: faqat savdo rejimi (DEMO/CONTEST/REAL) va server nomi;
  • REAL hisobda ishlamaydi (MT5_ALLOW_REAL=1 bo'lmasa): tadqiqot uchun demo hisob talab qilinadi;
  • terminal ishga tushirilmaydi va yopilmaydi; sozlamalar, Algo Trading tugmasi, hisob o'zgartirilmaydi. Yagona
    "yozish" — symbol_select: kerakli simvolni Market Watch ro'yxatiga qo'shadi (ma'lumot olish uchun shart).

Vaqt: MT5 sham va tik vaqtlarini broker SERVER vaqtida beradi (epoch ko'rinishida, lekin siljish bilan). Siljish
faqat JONLI tik oqimidan o'lchanadi (1.5 s ichida tik o'zgarsa — bozor ochiq, oxirgi tik = hozir; 30 daqiqaga
yaxlitlanadi) va 7 kun saqlanadi. Eskirgan tik ishlatilmaydi (bozor yopilgandan keyingi tik noto'g'ri siljish beradi).
Aniqlanmasa — vaqt taxmin qilinmaydi: DataUnavailable.
"""
from __future__ import annotations

import getpass
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import TF_SECONDS, Candle, DataUnavailable

ALLOWED = frozenset({"initialize", "shutdown", "last_error", "version", "terminal_info", "account_info",
                     "symbols_total", "symbols_get", "symbol_info", "symbol_select", "symbol_info_tick",
                     "copy_rates_from", "copy_rates_from_pos", "copy_rates_range"})
TIMEFRAMES = {"1m": "TIMEFRAME_M1", "1min": "TIMEFRAME_M1", "5m": "TIMEFRAME_M5", "15m": "TIMEFRAME_M15",
              "30m": "TIMEFRAME_M30", "1h": "TIMEFRAME_H1", "4h": "TIMEFRAME_H4", "1d": "TIMEFRAME_D1"}
TRADE_MODES = {0: "DEMO", 1: "CONTEST", 2: "REAL"}
ALIASES = {"XAUUSD": ("GOLD",), "XAGUSD": ("SILVER",)}
OFFSET_TTL = timedelta(days=7)
_LOCK = threading.RLock()  # paket global (jarayonda bitta ulanish) — chaqiruvlar ketma-ket


class ReadOnlyMT5:
    """MetaTrader5 moduli ustidagi qobiq: faqat ALLOWED funksiyalar va TIMEFRAME_* konstantalari."""

    def __init__(self, module):
        self._m = module

    def __getattr__(self, name: str):
        if name.startswith("TIMEFRAME_"):
            return getattr(self._m, name)
        if name not in ALLOWED:
            raise PermissionError(f"MT5.{name} — faqat o'qish rejimi: bu funksiya ruxsat etilmagan")
        return getattr(self._m, name)


# ------------------------------------------------------------------------------------------------ terminalni aniqlash
def current_user() -> str:
    return f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}".strip("\\")


def same_user(a: str | None, b: str | None) -> bool:
    return (a or "").split("\\")[-1].lower() == (b or "").split("\\")[-1].lower()


def find_terminals() -> list[dict]:
    """O'rnatilgan terminallar (Program Files\\*\\terminal64.exe) va ochiq jarayonlar (kim nomidan ochilgani bilan)."""
    out: list[dict] = []
    for root in filter(None, {os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432")}):
        try:
            dirs = sorted(Path(root).iterdir())
        except OSError:
            continue
        for d in dirs:
            exe = d / "terminal64.exe"
            if exe.is_file():
                out.append({"path": str(exe), "name": d.name, "running": False, "user": None, "pid": None})
    try:
        import psutil
    except ImportError:
        return out
    for p in psutil.process_iter(["pid", "name"]):
        if (p.info["name"] or "").lower() != "terminal64.exe":
            continue
        try:
            exe = p.exe()
        except (psutil.Error, OSError):
            exe = ""
        try:
            user = p.username()
        except (psutil.Error, OSError):
            user = "?"  # boshqa foydalanuvchi jarayoni bo'lishi mumkin
        hit = next((t for t in out if exe and t["path"].lower() == exe.lower()), None)
        if hit is None:
            hit = {"path": exe or "?", "name": Path(exe).parent.name if exe else "?"}
            out.append(hit)
        hit.update(running=True, user=user, pid=p.info["pid"])
    return out


def choose_terminal(terminals: list[dict], configured: str | None = None) -> tuple[dict | None, str]:
    """Qaysi terminal: MT5_PATH > yagona ochiq > yagona o'rnatilgan. Noaniq bo'lsa — tanlanmaydi (egasidan so'raladi)."""
    names = ", ".join(t["name"] for t in terminals)
    if configured:
        hit = next((t for t in terminals if t["path"].lower() == configured.lower()), None)
        return (hit, "MT5_PATH") if hit else (None, f"MT5_PATH dagi terminal topilmadi: {configured}")
    running = [t for t in terminals if t.get("running")]
    if len(running) == 1:
        return running[0], "ochiq terminal"
    if len(running) > 1:
        return None, f"bir nechta MT5 ochiq ({', '.join(t['name'] for t in running)}) — .env: MT5_PATH bilan tanlang"
    if not terminals:
        return None, "MetaTrader 5 terminali topilmadi"
    if len(terminals) == 1:
        return terminals[0], "yagona o'rnatilgan terminal"
    return None, f"bir nechta MT5 o'rnatilgan ({names}), hech biri ochiq emas — keraklisini oching yoki MT5_PATH bering"


# ------------------------------------------------------------------------------------------------ ulanish
class MT5Connector:
    def __init__(self, path: str | None = None, *, module=None, allow_real: bool = False, timeout_ms: int = 15000,
                 state_file: Path | None = None, clock=None, terminals=None, sleep=time.sleep):
        self.path_cfg = (path or "").strip() or None
        self._module = module
        self.allow_real = allow_real
        self.timeout_ms = timeout_ms
        self.state_file = Path(state_file) if state_file else None
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._terminals = terminals  # testlar uchun: find_terminals() o'rniga
        self._sleep = sleep
        self.mt5: ReadOnlyMT5 | None = None
        self.info: dict = {}
        self._symbols: dict[str, str] = {}
        self._offset: tuple[int, datetime] | None = None

    @classmethod
    def from_env(cls, env, state_file: Path | None = None) -> "MT5Connector":
        return cls(str(env.get("MT5_PATH") or ""), state_file=state_file,
                   allow_real=str(env.get("MT5_ALLOW_REAL") or "").strip() == "1")

    def _load(self) -> ReadOnlyMT5:
        if self._module is None:
            try:
                import MetaTrader5 as module
            except ImportError:
                raise DataUnavailable("MetaTrader5 Python paketi o'rnatilmagan (pip install MetaTrader5)") from None
            self._module = module
        return ReadOnlyMT5(self._module)

    def _alive(self) -> bool:
        try:
            ti = self.mt5.terminal_info()
            return bool(ti and ti.connected)
        except Exception:  # noqa: BLE001 — terminal yopilgan bo'lishi mumkin
            return False

    def connect(self) -> dict:
        with _LOCK:
            if self.mt5 is not None and self._alive():
                return self.info
            self.mt5 = None
            mt5 = self._load()
            terms = self._terminals if self._terminals is not None else find_terminals()
            term, why = choose_terminal(terms, self.path_cfg)
            if term is None:
                raise DataUnavailable(f"MT5: {why}")
            if not term.get("running"):
                raise DataUnavailable(f"MT5 terminali ochiq emas ({term['name']}) — agent uni o'zi ishga tushirmaydi")
            me = current_user()
            if term.get("user") not in (None, "?") and not same_user(term["user"], me):
                raise DataUnavailable(
                    f"MT5 terminali boshqa foydalanuvchi ({term['user']}) nomidan ochilgan, agent esa {me} nomidan "
                    "ishlaydi — Python API turli foydalanuvchilar orasida ulanmaydi (IPC timeout). Terminalni yopib, "
                    "Start menyudan oddiy (o'z nomingizdan) oching.")
            if not mt5.initialize(path=term["path"], timeout=self.timeout_ms):  # login/parol berilmaydi
                err = mt5.last_error()
                hint = (" (terminal javob bermadi: terminalda hisobga kirilmagan, dialog oynasi ochiq yoki terminal "
                        "boshqa foydalanuvchida bo'lishi mumkin)") \
                    if err and err[0] == -10005 else ""
                raise DataUnavailable(f"MT5 initialize muvaffaqiyatsiz: {err}{hint}")
            ok = False
            try:
                ti, ai = mt5.terminal_info(), mt5.account_info()
                if ai is None:
                    raise DataUnavailable("MT5: terminalda hisobga kirilmagan — demo hisobga kiring")
                mode = TRADE_MODES.get(ai.trade_mode, str(ai.trade_mode))
                if mode == "REAL" and not self.allow_real:
                    raise DataUnavailable("MT5: REAL hisob ochiq — tadqiqot faqat demo hisobda ishlaydi (demo hisobga "
                                          "o'ting; faqat o'qish uchun ruxsat: MT5_ALLOW_REAL=1)")
                if not (ti and ti.connected):
                    raise DataUnavailable("MT5 terminali savdo serveriga ulanmagan (internet yoki hisob)")
                self.info = {"terminal": term["name"], "path": term["path"], "build": (mt5.version() or [None, None])[1],
                             "server": ai.server, "trade_mode": mode, "algo_trading_button": bool(ti.trade_allowed),
                             "symbols": mt5.symbols_total(), "selected_by": why}
                ok = True
            finally:
                if not ok:
                    mt5.shutdown()
            self.mt5 = mt5
            self._symbols.clear()
            return self.info

    def close(self) -> None:
        with _LOCK:
            if self.mt5 is not None:
                self.mt5.shutdown()
            self.mt5 = None

    # -------------------------------------------------------------------------------------- simvol va vaqt
    def resolve(self, symbol: str) -> str:
        """'XAU/USD' -> broker nomi (XAUUSD, XAUUSDm, XAUUSD.a, GOLD ...). Topilmasa — DataUnavailable."""
        key = symbol.replace("/", "").replace("-", "").upper()
        if key in self._symbols:
            return self._symbols[key]
        names = [s.name for s in (self.mt5.symbols_get() or [])]

        def norm(n: str) -> str:
            return "".join(ch for ch in n.upper() if ch.isalnum())
        found = [n for n in names if n.upper() == key] or [n for n in names if norm(n) == key] or \
            sorted((n for n in names if n.upper().startswith(key) and len(n) - len(key) <= 4), key=len) or \
            [n for n in names if n.upper() in ALIASES.get(key, ())]
        if not found:
            raise DataUnavailable(f"MT5: '{symbol}' simvoli brokerda topilmadi")
        self._symbols[key] = found[0]
        return found[0]

    def _ensure_selected(self, name: str):
        info = self.mt5.symbol_info(name)
        if info is None:
            raise DataUnavailable(f"MT5: {name} ma'lumoti yo'q ({self.mt5.last_error()})")
        if not info.visible and not self.mt5.symbol_select(name, True):
            raise DataUnavailable(f"MT5: {name} Market Watch ga qo'shilmadi ({self.mt5.last_error()})")
        return info

    def _read_state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8")) if self.state_file else {}
        except (OSError, ValueError):
            return {}

    def server_offset(self, names: tuple[str, ...] = ()) -> int:
        """Server vaqti - UTC (soniya). Jonli tikdan o'lchanadi; bo'lmasa 7 kunlik saqlangan qiymat; aks holda xato."""
        now = self.clock()
        if self._offset and now - self._offset[1] < timedelta(minutes=10):
            return self._offset[0]
        probes = list(names)
        for extra in ("BTCUSD", "EURUSD"):
            try:
                probes.append(self.resolve(extra))
            except DataUnavailable:
                pass
        for name in list(dict.fromkeys(probes))[:3]:
            first = self.mt5.symbol_info_tick(name)
            if not first or not getattr(first, "time_msc", 0):
                continue
            self._sleep(1.5)
            tick = self.mt5.symbol_info_tick(name)
            if not tick or tick.time_msc == first.time_msc:
                continue  # tik o'zgarmadi — bozor yopiq yoki sokin, oxirgi tik "hozir" emas
            delta = tick.time_msc / 1000.0 - self.clock().timestamp()
            off = int(round(delta / 1800.0) * 1800)
            if abs(delta - off) <= 90 and abs(off) <= 14 * 3600:
                self._offset = (off, now)
                if self.state_file:
                    state = self._read_state()
                    state.update(offset_sec=off, measured_at=now.isoformat(timespec="seconds"), server=self.info.get("server"))
                    self.state_file.parent.mkdir(parents=True, exist_ok=True)
                    self.state_file.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
                return off
        state = self._read_state()
        if "offset_sec" in state and state.get("server") == self.info.get("server"):
            measured = datetime.fromisoformat(state["measured_at"])
            if now - measured < OFFSET_TTL:
                return int(state["offset_sec"])
        raise DataUnavailable("MT5 server vaqt siljishi aniqlanmadi (bozor yopiq, yangi tik yo'q) — vaqt taxmin qilinmaydi")

    # -------------------------------------------------------------------------------------- shamlar
    def candles(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
                start: datetime | None = None) -> list[Candle]:
        if timeframe not in TIMEFRAMES:
            raise DataUnavailable(f"MT5: '{timeframe}' taymfreymi qo'llab-quvvatlanmaydi")
        with _LOCK:
            self.connect()
            try:
                name = self.resolve(symbol)
                self._ensure_selected(name)
                tf = getattr(self.mt5, TIMEFRAMES[timeframe])
                off = self.server_offset((name,))

                def srv(dt: datetime) -> datetime:
                    return datetime.fromtimestamp(dt.timestamp() + off, tz=timezone.utc)
                if start is not None:
                    rows = self.mt5.copy_rates_range(name, tf, srv(start), srv(end or self.clock()))
                elif end is not None:
                    rows = self.mt5.copy_rates_from(name, tf, srv(end - timedelta(seconds=1)), int(limit))
                else:
                    rows = self.mt5.copy_rates_from_pos(name, tf, 0, int(limit))
                if rows is None:
                    raise DataUnavailable(f"MT5 {name} {timeframe}: ma'lumot qaytmadi ({self.mt5.last_error()})")
            except DataUnavailable:
                if not self._alive():
                    self.mt5 = None  # terminal yopilgan/uzilgan — keyingi chaqiruvda qayta ulanadi
                raise
        sec = TF_SECONDS[timeframe]
        out = [Candle(datetime.fromtimestamp(int(r["time"]) - off, tz=timezone.utc), float(r["open"]), float(r["high"]),
                      float(r["low"]), float(r["close"]), float(r["tick_volume"]), sec) for r in rows]
        if start is not None:
            out = [c for c in out if c.ts >= start][:limit]
        if end is not None:
            out = [c for c in out if c.ts < end]
        return out


class MT5Provider:
    """data.Provider: MarketData shu orqali MT5'dan sham oladi (faqat yopilgan shamlar MarketData'da filtrlanadi)."""

    def __init__(self, connector: MT5Connector):
        self.connector = connector

    @property
    def name(self) -> str:
        i = self.connector.info
        return f"MetaTrader 5 ({i.get('server', '?')}, {i.get('trade_mode', '?')}, faqat o'qish)"

    def klines(self, symbol: str, timeframe: str, limit: int, end: datetime | None = None,
               start: datetime | None = None) -> list[Candle]:
        return self.connector.candles(symbol, timeframe, limit, end=end, start=start)


def status(connector: MT5Connector) -> dict:
    """Ulanish holati (tool va --check uchun). Hech narsa o'zgartirmaydi."""
    terms = connector._terminals if connector._terminals is not None else find_terminals()
    out = {"terminals": [{k: t.get(k) for k in ("name", "running", "user")} for t in terms], "agent_user": current_user()}
    try:
        out.update(connected=True, **connector.connect())
    except DataUnavailable as exc:
        out.update(connected=False, reason=str(exc))
    return out
