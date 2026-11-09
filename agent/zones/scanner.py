"""ZONE-1..5: butun bozorni (Binance USDT juftliklari + MT5 DEMO terminal simvollari) aktiv zonalar uchun skanerlaydi.

Faqat O'QISH: ochiq market-data va MT5 o'qish rejimi. Buyurtma bermaydi, signal yaratmaydi — zonalar `zones` jadvaliga yoziladi,
aktivlari veb-chatga tushadi (`staff_messages`, kind='zone'), ish jarayoni `staff_activity` jadvalida ko'rinadi.
LLM faqat muhokama uchun va soatiga cheklangan (kvota); zonani topish LLM'siz.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..staff import roster as R
from .categories import mt5_groups
from .detectors import DETECTORS, Bar, atr, classify

log = logging.getLogger(__name__)

DEFAULTS = {"enabled": True, "every_s": 300, "min_quote_volume": 1_000_000, "max_dist_atr": 6.0, "max_binance": 300, "max_mt5": 400,
            "announce_per_pass": 5, "announce_cooldown_h": 6, "consult_per_hour": 3, "near_atr": 0.5, "workers": 6}
STABLE = {"USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDP", "EUR", "GBP", "AEUR", "USDE", "XUSD", "PYUSD", "USD1"}
LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)$")
TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/24hr"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def zone_id(symbol: str, det: str, tf: str, kind: str, low: float, high: float) -> str:
    mid = (low + high) / 2
    bucket = f"{mid:.{max(0, 5 - len(str(int(abs(mid)))))}f}"  # ~5 ta ahamiyatli raqam: kichik siljish bir xil zona
    return hashlib.sha1(f"{symbol}|{det}|{tf}|{kind}|{bucket}".encode()).hexdigest()[:12]


def binance_universe(client, min_quote_volume: float, cap: int) -> list[str]:
    r = client.get(TICKER_URL)
    r.raise_for_status()
    rows = []
    for t in r.json():
        s = t["symbol"]
        if not s.endswith("USDT"):
            continue
        base = s[:-4]
        if base in STABLE or LEVERAGED.search(base) or float(t.get("quoteVolume") or 0) < min_quote_volume:
            continue
        rows.append((float(t["quoteVolume"]), s))
    return [s for _, s in sorted(rows, reverse=True)[:cap]]


def mt5_universe(connector, cap: int) -> list[str]:
    """Brokerda to'liq savdoga ochiq simvollar (forex, metall, indeks, kripto, aksiya — nima bo'lsa). Faqat nomlar o'qiladi."""
    infos = connector.mt5.symbols_get() or []
    names = [i.name for i in infos if getattr(i, "trade_mode", 4) == 4]  # SYMBOL_TRADE_MODE_FULL
    return names[:cap]


class ZoneScanner:
    def __init__(self, svc, desk, http_client, cfg: dict | None = None, mt5=None, clock=None):
        self.svc, self.desk, self.http, self.mt5 = svc, desk, http_client, mt5
        self.db = svc.db
        self.cfg = {**DEFAULTS, **(cfg or {}), **((svc.settings.data.get("zones") or {}) if hasattr(svc.settings, "data") else {})}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._consults: list[float] = []
        self.universe: dict[str, list[str]] = {"binance": [], "mt5": []}
        self._uni_at = 0.0
        try:  # mavjud bazaga atr ustuni (yangi bazada CREATE TABLE'da bor)
            self.db.execute("ALTER TABLE zones ADD COLUMN atr REAL")
        except Exception:  # noqa: BLE001 — ustun allaqachon bor
            pass
        self.mt5_group: dict[str, str] = {}  # simvol -> kategoriya (brokerning haqiqiy yo'lidan)
        self.after_pass = None  # async callback: DIR-1 zona vazifasi (trade.ZoneTrader.on_pass)

    # ------------------------------------------------------------------ faollik (veb ko'radi)
    def work(self, role: str, task: str, **counters) -> None:
        self.db.execute("INSERT INTO staff_activity(role, task, ts, counters) VALUES(?,?,?,?) ON CONFLICT(role) DO UPDATE SET "
                        "task=excluded.task, ts=excluded.ts, counters=excluded.counters", (role, task, _now(), json.dumps(counters)))

    # ------------------------------------------------------------------ ma'lumot
    def _candles(self, source: str, symbol: str, tf: str, limit: int):
        now = self.clock()
        if source == "binance":
            raw = self.svc.market.providers["binance"].klines(symbol, tf, limit)
        else:
            raw = self.mt5.candles(symbol, tf, limit)
        return [c for c in raw if c.end <= now]

    def scan_symbol(self, source: str, symbol: str) -> dict:
        """Bitta instrument: zonalarni hisoblaydi. Qaytaradi {zones:[...], price, atr, fresh} yoki {error}."""
        out: list[dict] = []
        price = a = None
        fresh = True
        cache: dict[str, list] = {}
        for role, (fn, tf) in DETECTORS.items():
            if tf not in cache:
                try:
                    cache[tf] = self._candles(source, symbol, tf, 300 if tf != "4h" else 250)
                except Exception as exc:  # noqa: BLE001 — bitta instrument xatosi butun skanerni to'xtatmaydi
                    cache[tf] = []
                    if tf == "1h":
                        return {"error": f"{type(exc).__name__}: {str(exc)[:80]}"}
            cs = cache[tf]
            if len(cs) < 60:
                continue
            bars = [Bar(c.open, c.high, c.low, c.close) for c in cs]
            if tf == "1h":
                price, a = bars[-1].close, atr(bars)
                fresh = (self.clock() - cs[-1].end).total_seconds() < 6 * 3600  # bozor yopiq bo'lsa 'aktiv' bo'lmaydi
            out += fn(bars, tf, det=role)
        return {"zones": out, "price": price, "atr": a, "fresh": fresh}

    # ------------------------------------------------------------------ bazaga yozish
    def store(self, source: str, symbol: str, res: dict) -> list[dict]:
        """Instrument zonalarini yangilaydi. Qaytaradi: yangi AKTIV bo'lgan zonalar (chatga e'lon qilish uchun)."""
        now = _now()
        old = {r["id"]: r for r in self.db.query("SELECT id, first_seen, announced_at, status FROM zones WHERE symbol=?", (symbol,))}
        price, a = res.get("price"), res.get("atr")
        seen, news = set(), []
        for z in res.get("zones", []):
            if not price or not a:
                break
            status, dist = classify(z, price, a, float(self.cfg["near_atr"]))
            if status == "broken" or dist > float(self.cfg["max_dist_atr"]):  # uzoq zonalar — shovqin
                continue
            if status == "active" and not res.get("fresh", True):
                status = "fresh"
            zid = zone_id(symbol, z["detector"], z["tf"], z["kind"], z["low"], z["high"])
            if zid in seen:
                continue
            seen.add(zid)
            prev = old.get(zid)
            self.db.execute(
                "INSERT INTO zones(id, symbol, source, detector, kind, tf, low, high, strength, note, status, dist_atr, price, first_seen, last_seen, announced_at, atr) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET low=excluded.low, high=excluded.high, strength=excluded.strength, "
                "note=excluded.note, status=excluded.status, dist_atr=excluded.dist_atr, price=excluded.price, last_seen=excluded.last_seen, atr=excluded.atr",
                (zid, symbol, source, z["detector"], z["kind"], z["tf"], z["low"], z["high"], z["strength"], z["note"], status,
                 round(dist, 2), price, prev["first_seen"] if prev else now, now, prev["announced_at"] if prev else None, a))
            if status == "active" and self._announce_due(prev):
                news.append({**z, "id": zid, "symbol": symbol, "source": source, "status": status, "dist_atr": dist, "price": price, "atr": a})
        for zid in set(old) - seen:  # endi yo'q (teshilgan yoki yo'qolgan) zonalar
            self.db.execute("DELETE FROM zones WHERE id=?", (zid,))
        return news

    def _announce_due(self, prev) -> bool:
        if not prev or not prev["announced_at"]:
            return True
        try:
            return (self.clock() - datetime.fromisoformat(prev["announced_at"])).total_seconds() > float(self.cfg["announce_cooldown_h"]) * 3600
        except ValueError:
            return True

    # ------------------------------------------------------------------ chat
    @staticmethod
    def line(z: dict) -> str:
        where = "zona ICHIDA" if z["dist_atr"] <= 0.001 else "%.2f ATR uzoqda" % z["dist_atr"]
        return (f"{z['symbol']} [{z['source']}] {z['tf']} {z['kind'].upper()} zona {z['low']:.6g}–{z['high']:.6g} | narx {z['price']:.6g} "
                f"({where}) | kuch {z['strength']} | {z['note']}")

    def directive(self) -> dict:
        row = self.db.one("SELECT value FROM meta WHERE key='zone_directive'")
        try:
            return json.loads(row["value"]) if row else {}
        except ValueError:
            return {}

    def announce(self, news: list[dict]) -> list[dict]:
        d = self.directive()  # DIR-1 sharti (zdelka ochilgach): ochiq instrumentni chetlab, faqat kuchli zonalar
        if d:
            news = [z for z in news if z["symbol"] != d.get("symbol") and z["strength"] >= float(d.get("min_strength", 0))]
        top = sorted(news, key=lambda z: (z["dist_atr"], -z["strength"]))[: int(self.cfg["announce_per_pass"])]
        for z in top:
            self.desk.say(z["detector"], "zone", "AKTIV ZONA: " + self.line(z), z["id"])
            self.db.execute("UPDATE zones SET announced_at=? WHERE id=?", (_now(), z["id"]))
        return top

    def _consult_allowed(self) -> bool:
        cut = time.time() - 3600
        self._consults = [t for t in self._consults if t > cut]
        return self.desk.llm is not None and len(self._consults) < int(self.cfg["consult_per_hour"])

    async def consult(self, zones: list[dict]) -> None:
        """Muhokama (kvota cheklangan): DEBATE-C (daraja/tuzilma), DEBATE-B (xavf skeptigi), so'ng DIR-1 kuzatuv ro'yxati.
        Natija FAQAT matn va 'watch' belgisi — zdelka ochilmaydi."""
        if not zones or not self._consult_allowed():
            return
        self._consults.append(time.time())
        brief = "\n".join(f"{i}. {self.line(z)}" for i, z in enumerate(zones, 1))
        ctx = f"AKTIV ZONALAR (hisoblangan, taxmin emas):\n{brief}\n\nHar zona uchun 1-2 gapdan fikr ber."
        try:
            c, b = await asyncio.gather(self.desk._ask(R.BY_ID["DEBATE-C"], ctx), self.desk._ask(R.BY_ID["DEBATE-B"], ctx + " Xavf nuqtai nazaridan."))
            self.desk.say("DEBATE-C", "zone-talk", c.strip(), zones[0]["id"])
            self.desk.say("DEBATE-B", "zone-talk", b.strip(), zones[0]["id"])
            raw = await self.desk._ask(R.DIRECTOR, f"{ctx}\n\nDEBATE-C: {c.strip()[:500]}\nDEBATE-B: {b.strip()[:500]}\n"
                                       'Qaysi zonalarni KUZATUV ro\'yxatiga olamiz? FAQAT JSON: {"watch":[raqamlar], "note":"qisqa"}. '
                                       "Bu zdelka ochish emas, faqat kuzatuv.")
            from ..staff.desk import parse_json
            d = parse_json(raw) or {}
            picked = [zones[int(i) - 1] for i in d.get("watch", []) if str(i).isdigit() and 0 < int(i) <= len(zones)]
            for z in picked:
                self.db.execute("UPDATE zones SET watch=1 WHERE id=?", (z["id"],))
            self.desk.say(R.DIRECTOR.id, "zone-talk", f"Kuzatuvga olindi: {', '.join(z['symbol'] + ' ' + z['kind'] for z in picked) or 'hech biri'}. {str(d.get('note', ''))[:300]}", zones[0]["id"])
        except Exception as exc:  # noqa: BLE001 — kvota/tarmoq: faqat yozib qo'yamiz, skaner davom etadi
            log.exception("zona muhokamasi")
            self.desk.say(R.DIRECTOR.id, "system", f"Zona muhokamasi bajarilmadi ({type(exc).__name__}) — zonalar ma'lumot sifatida qoldi.", None)

    # ------------------------------------------------------------------ tsikl
    def refresh_universe(self) -> None:
        """Ro'yxat soatiga 1 marta. MUHIM: agent endigina ishga tushganda MT5 ulanishi hali ochilmagan bo'ladi — avval ulanamiz; ro'yxat
        olinmasa ESKISI saqlanadi va keyingi o'tishda qayta uriniladi (bo'sh ro'yxatni 1 soat eslab qolish MT5 zonalarini o'chirib qo'yardi)."""
        if time.time() - self._uni_at < 3600 and self.universe["binance"] and (self.universe["mt5"] or self.mt5 is None):
            return
        ok = True
        try:
            self.universe["binance"] = binance_universe(self.http, float(self.cfg["min_quote_volume"]), int(self.cfg["max_binance"]))
        except Exception as exc:  # noqa: BLE001
            ok = False
            log.warning("Binance ro'yxati olinmadi: %s", exc)
        if self.mt5 is not None:
            try:
                self.mt5.connect()  # idempotent: ulangan bo'lsa tezkor
                names = mt5_universe(self.mt5, int(self.cfg["max_mt5"]))
                if not names:
                    raise RuntimeError("MT5 simvollar ro'yxati bo'sh")
                self.universe["mt5"] = names
                self.mt5_group = mt5_groups(self.mt5)
            except Exception as exc:  # noqa: BLE001
                ok = False
                log.warning("MT5 simvollar ro'yxati olinmadi (eskisi saqlandi, qayta uriniladi): %s", exc)
        if ok:
            self._uni_at = time.time()
        self.db.execute("INSERT INTO meta(key, value) VALUES('zone_universe', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (json.dumps({"binance": len(self.universe["binance"]), "mt5": len(self.universe["mt5"]), "ts": _now()}),))

    def run_pass(self) -> dict:
        """Bitta to'liq o'tish (sinxron; thread ichida chaqiriladi). Qaytaradi statistika va e'lon qilinadigan zonalar."""
        t0 = time.time()
        self.refresh_universe()
        items = [("binance", s) for s in self.universe["binance"]] + [("mt5", s) for s in self.universe["mt5"]]
        total, done, errors, zones_n, news = len(items), 0, 0, 0, []
        roles = list(DETECTORS)
        for r in roles:
            self.work(r, f"Skaner boshlandi: {total} instrument", total=total, done=0)

        def one(it):
            return it, self.scan_symbol(*it)
        # Binance — parallel (tarmoq); MT5 — ketma-ket (paket global qulf)
        bn = [it for it in items if it[0] == "binance"]
        mt = [it for it in items if it[0] == "mt5"]
        def results(pool):
            yield from pool.map(one, bn)  # tartib bo'yicha, lekin har natija keldi-kelmas yoziladi
            for x in mt:
                yield one(x)

        with ThreadPoolExecutor(max_workers=int(self.cfg["workers"])) as pool:
            for it, res in results(pool):
                done += 1
                if "error" in res:
                    errors += 1
                else:
                    zones_n += len(res["zones"])
                    news += self.store(it[0], it[1], res)
                if done % 10 == 0 or done == total:
                    for r in roles:
                        self.work(r, f"{done}/{total} instrument skanerlandi", total=total, done=done, errors=errors)
        active = self.db.one("SELECT COUNT(*) n FROM zones WHERE status='active'")["n"]
        per = {r["detector"]: r["n"] for r in self.db.query("SELECT detector, COUNT(*) n FROM zones GROUP BY detector")}
        pa = {r["detector"]: r["n"] for r in self.db.query("SELECT detector, COUNT(*) n FROM zones WHERE status='active' GROUP BY detector")}
        for r in roles:
            self.work(r, f"O'tish tugadi: {per.get(r, 0)} zona, {pa.get(r, 0)} tasi aktiv ({total} instrument, {errors} xato)",
                      total=total, done=done, errors=errors, zones=per.get(r, 0), active=pa.get(r, 0), secs=round(time.time() - t0, 1))
        return {"total": total, "errors": errors, "zones": zones_n, "active": active, "news": news, "secs": round(time.time() - t0, 1)}

    async def run(self) -> None:
        if not self.cfg["enabled"]:
            return
        await asyncio.sleep(20)  # agent to'liq ishga tushsin
        while True:
            try:
                res = await asyncio.to_thread(self.run_pass)
                top = self.announce(res["news"])
                if res["errors"] > res["total"] * 0.5:
                    self.desk.say("ZONE-1", "system", f"Skaner: {res['errors']}/{res['total']} instrumentda ma'lumot xatosi (tarmoq/manba).", None)
                await self.consult(top[:3])
                if self.after_pass is not None:
                    await self.after_pass()
            except Exception:  # noqa: BLE001
                log.exception("zona skaneri")
            await asyncio.sleep(float(self.cfg["every_s"]))
