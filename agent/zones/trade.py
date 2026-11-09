"""DIR-1 vazifasi: topilgan AKTIV zonadan zdelka ochish (faqat AUTO + DEMO) va zdelka ochilgach xodimlarga yangi shart berish.

Zona zdelkani O'ZI ochmaydi — u oddiy signalga aylanadi va signal tizimining O'ZINING yo'lidan o'tadi:
  zona -> Candidate (kirish/SL/TP kodda) -> store+publish -> xodimlar bahsi (>=3/4 + DIR-1) -> auto_confirm -> revalidate ->
  _open_group (1% risk, SL>=1 ATR, R/R>=1.5, korrelyatsiya, guruhlar soni, kunlik zarar chegarasi, DemoTrader: faqat DEMO).
Hech qaysi himoya aylanib o'tilmaydi. Hozircha faqat Binance'da ham, MT5 DEMO'da ham mavjud kripto juftliklar savdoga ruxsat
(ma'lumot va simvol xaritasi aniq bo'lgan yo'l); forex/metall zonalari faqat ko'rsatiladi.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..staff import roster as R
from ..trading.indicators import Features
from ..trading.signal_score import Item, Score, evaluate
from ..trading.signals import Candidate
from .detectors import Bar, atr

log = logging.getLogger(__name__)

LONG_KINDS = {"support", "demand", "liq-low"}
SHORT_KINDS = {"resistance", "supply", "liq-high"}
DEFAULTS = {"trade_enabled": True, "trade_min_strength": 20.0, "trade_cooldown_h": 6, "trade_max_per_pass": 1,
            "trade_categories": ["Forex", "Metals", "Indices", "Commodities"],  # MT5 (aksiya va kripto-MT5 yoqilmagan: kripto Binance orqali)
            "trade_min_rr": 1.5, "queue_min_rr": 2.0, "daily_target": 10, "behind_max_per_pass": 3, "behind_cooldown_h": 2, "max_spread_sl": 0.10, "trade_opp_min_strength": 15.0, "shortlist": 25}
NA = "zona signalida baholanmaydi"


@dataclass
class Setup:
    symbol: str
    zone: dict
    direction: str
    entry: float
    sl: float
    tp: float
    rr: float
    rr_net: float
    atr: float
    tp_note: str
    last_end: datetime
    source: str
    spread: float
    commission: float
    score: Score | None = None  # evaluate() natijasi: trend/EMA/RSI/MACD/hajm — bahschilar HAQIQIY ma'lumotni ko'radi


def build_setup(zone: dict, price: float, a: float, opposing: list[dict], *, min_rr: float = 1.5, spread_bps: float = 2.0,
                commission_pct: float = 0.1) -> tuple[Setup | None, str]:
    """Zonadan kirish/SL/TP (sof hisob). Qaytaradi (Setup, '') yoki (None, rad sababi). ATR bo'lmasa — rad."""
    if not a or a <= 0 or price <= 0:
        return None, "ATR/narx yo'q"
    kind = zone["kind"]
    if kind in LONG_KINDS:
        direction = "LONG"
    elif kind in SHORT_KINDS:
        direction = "SHORT"
    else:
        return None, f"'{kind}' zonasi yo'nalishsiz (diapazon) — zdelka berilmaydi"
    long = direction == "LONG"
    sl = min(zone["low"] - 0.25 * a, price - 1.0 * a) if long else max(zone["high"] + 0.25 * a, price + 1.0 * a)  # SL >= 1 ATR
    risk = abs(price - sl)
    if risk <= 0:
        return None, "SL masofasi 0"
    cost = price * (spread_bps / 1e4 + 2 * commission_pct / 100)
    fb = 2 * (risk + cost) + cost  # zaxira maqsad: xarajatdan KEYIN 2R
    if long:
        ahead = [z["low"] for z in opposing if z["kind"] in SHORT_KINDS and z["low"] > price]
        tp, note = (min(ahead), "maqsad: eng yaqin qarshi zona") if ahead else (price + fb, "qarshi zona topilmadi — xarajatdan keyin 2R")
    else:
        ahead = [z["high"] for z in opposing if z["kind"] in LONG_KINDS and z["high"] < price]
        tp, note = (max(ahead), "maqsad: eng yaqin qarshi zona") if ahead else (price - fb, "qarshi zona topilmadi — xarajatdan keyin 2R")
    reward = abs(tp - price)
    rr = reward / risk
    rr_net = (reward - cost) / (risk + cost)
    if rr_net < min_rr:
        return None, f"R/R {rr_net:.2f} < {min_rr:g}: yo'lda qarshi zona juda yaqin"
    return Setup(zone.get("symbol", ""), zone, direction, price, sl, tp, rr, rr_net, a, note, datetime.now(timezone.utc), "", price * spread_bps / 1e4,
                 commission_pct / 100), ""


def to_candidate(s: Setup, now: datetime, data_ts: datetime, source: str) -> Candidate:
    z = s.zone
    long = s.direction == "LONG"
    if s.score is not None:  # haqiqiy hisoblangan kursatkichlar; daraja "ZONE" (strategiya darajasi emas)
        score = Score(s.score.score, s.score.items, "ZONE", s.score.blocked, s.score.missing)
    else:
        items = [Item(k, k, None, NA) for k in ("h4_trend", "h1_trend", "m15_ema", "rsi", "macd", "volume", "breakout", "structure", "sr")]
        score = Score(0, items, "ZONE", None, ["kursatkichlar hisoblanmadi"])
    inv = {"type": "close_below" if long else "close_above", "level": s.sl,
           "text": f"narx {'SL dan pastda' if long else 'SL dan yuqorida'} yopilsa zona bekor"}
    return Candidate(symbol=s.symbol, timeframe="1h", direction=s.direction, strategy_id="ZONE-DIR", strategy_version=1,
                     entry_type="next_open", entry=s.entry, sl=s.sl, tp=s.tp, rr=s.rr, rr_net=s.rr_net, invalidation=inv,
                     valid_until=now + timedelta(hours=4), data_ts=data_ts, source=source, spread=s.spread, commission=s.commission,
                     score=score, evidence={"zone_low": z["low"], "zone_high": z["high"], "zone_kind": z["kind"], "zone_tf": z["tf"],
                                            "zone_detector": z["detector"], "zone_strength": z["strength"], "atr14": s.atr,
                                            "target": s.tp_note},
                     structure=f"{z['tf']} {z['kind']} zonasi {z['low']:.6g}-{z['high']:.6g}; {s.tp_note}")


class ZoneTrader:
    """DIR-1 ning zona vazifasi. Har skaner o'tishidan keyin `on_pass` chaqiriladi."""

    def __init__(self, sv, scanner, cfg: dict | None = None):
        self.sv, self.scanner, self.db = sv, scanner, sv.db
        self.cfg = {**DEFAULTS, **(cfg or {}), **((sv.svc.settings.data.get("zones") or {}) if hasattr(sv.svc.settings, "data") else {})}

    # ------------------------------------------------------------------ tanlash
    def _tradable(self, symbol: str, source: str = "binance") -> bool:
        """Savdoga yaroqli: Binance USDT juftligi (MT5 DEMO'da <BASE>USDm bor) YOKI MT5 DEMO'da to'liq savdoga ochiq simvol,
        kategoriyasi ruxsat etilganlardan (forex, metall, indeks, xom ashyo)."""
        mt = {n.upper() for n in self.scanner.universe.get("mt5", [])}
        if source == "mt5":
            return symbol.upper() in mt and self.scanner.mt5_group.get(symbol) in set(self.cfg["trade_categories"])
        return symbol.endswith("USDT") and (symbol[:-1] + "m").upper() in mt

    def _opposing(self, z: dict) -> list[dict]:
        """Qarshi to'siq: faqat KUCHLI support/resistance/demand/supply (kichik likvidlik/diapazon zonalari to'siq emas — ular ko'p va shovqin)."""
        return self.db.query("SELECT kind, low, high FROM zones WHERE symbol=? AND id != ? AND strength >= ? AND kind IN ('resistance','supply','support','demand')",
                             (z["symbol"], z["id"], float(self.cfg["trade_opp_min_strength"])))

    def _shortlist(self, cands: list[dict], test: bool, force: bool = False) -> tuple[list[dict], list[str]]:
        """BARCHA nomzodlar tarmoqsiz saralanadi (baza: narx, ATR, qarshi zonalar). Faqat R/R va kuldaundan o'tganlari keyingi (tarmoq) bosqichga.
        Oldin faqat eng kuchli 12 ta har gal bir xil rad etilib, qolganiga navbat yetmasdi."""
        out, skipped = [], []
        for z in cands:
            if not force and self._cooldown(z["symbol"]):
                skipped.append(f"{z['symbol']}: kuldaun")
                continue
            if not test and z.get("atr") and z.get("price"):
                s, why = build_setup(z, z["price"], z["atr"], self._opposing(z), min_rr=float(self.cfg["trade_min_rr"]), spread_bps=0.0, commission_pct=0.0)
                if s is None:
                    skipped.append(f"{z['symbol']} {z['tf']} {z['kind']}: {why}")
                    continue
            out.append(z)
        return out, skipped

    def _candidates(self, n: int = 400) -> list[dict]:
        rows = self.db.query("SELECT id, symbol, source, detector, kind, tf, low, high, strength, note, dist_atr, watch, atr, price FROM zones "
                             "WHERE status='active' AND strength >= ? ORDER BY watch DESC, strength DESC, dist_atr LIMIT 400",
                             (float(self.cfg["trade_min_strength"]),))
        return [r for r in rows if r["kind"] in LONG_KINDS | SHORT_KINDS and self._tradable(r["symbol"], r["source"])][:n]

    def _tk_day_start(self) -> str:
        """Toshkent kuni boshi (UTC ISO). Kunlik hisob Toshkent kuni bo'yicha."""
        tk = timezone(timedelta(hours=5))
        now = datetime.now(timezone.utc).astimezone(tk)
        return now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).isoformat(timespec="seconds")

    def opened_today(self) -> int:
        """Bugun (Toshkent) ochilgan zona zdelkalari: MT5 DEMO guruhi haqiqatan ochilgan ZON-* signallar."""
        row = self.db.one("SELECT COUNT(*) n FROM demo_groups WHERE signal_id LIKE 'ZON-%' AND opened_at >= ?", (self._tk_day_start(),))
        return int((row or {}).get("n", 0))

    def behind(self) -> bool:
        return self.opened_today() < int(self.cfg["daily_target"])

    def _limits(self) -> tuple[int, float]:
        """(bir o'tishda max urinish, instrument kuldauni soat). Maqsaddan orqada bo'lsa — faolroq (himoyalar o'zgarmaydi)."""
        if self.behind():
            return int(self.cfg["behind_max_per_pass"]), float(self.cfg["behind_cooldown_h"])
        return int(self.cfg["trade_max_per_pass"]), float(self.cfg["trade_cooldown_h"])

    @staticmethod
    def _near_obstacle(s: Setup, f1) -> str | None:
        """Foyda tomonida 1H swing darajasi kirishdan 1R dan yaqin bo'lsa — sabab matni (baholovchilar aynan shuni rad etardi)."""
        risk = abs(s.entry - s.sl)
        if risk <= 0:
            return None
        highs, lows = f1.swings(len(f1) - 1, lookback=200)
        if s.direction == "LONG":
            above = sorted(p for _, p in highs if p > s.entry)
            if above and (above[0] - s.entry) < risk:
                return f"yaqin qarshilik {above[0]:.6g} ({(above[0] - s.entry) / risk:.2f}R) — foyda yo'li to'silgan"
        else:
            below = sorted((p for _, p in lows if p < s.entry), reverse=True)
            if below and (s.entry - below[0]) < risk:
                return f"yaqin support {below[0]:.6g} ({(s.entry - below[0]) / risk:.2f}R) — foyda yo'li to'silgan"
        return None

    def _plan_ok(self, s: Setup) -> tuple[bool, str]:
        """Zdelka rejasini signal yuborishdan OLDIN sinash — _open_group bilan AYNAN bir xil plan_group (minimal lot riski, spred, R/R, SL>=ATR).
        Bajarib bo'lmaydigan signal egasiga yuborilmaydi va bahsga (kvotaga) tushmaydi."""
        from ..trading import autotrade as at
        from ..trading.signals import mt5_name
        sv, cfg = self.sv, self.sv.cfg
        if sv.history is None or sv.trader is None:
            return False, "balans/MT5 ulanmagan"
        side = "buy" if s.direction == "LONG" else "sell"
        try:
            spec = sv.trader.symbol_spec(mt5_name(s.symbol))
            price = spec["ask"] if side == "buy" else spec["bid"]
            at.plan_group(side=side, price=price, sl=s.sl, tp=s.tp, atr=s.atr, balance=sv.history.balance(), spec=spec,
                          risk_pct=float(cfg.get("risk_pct", 1.0)), min_sl_atr=float(cfg.get("min_sl_atr", 1.0)),
                          min_rr=float(sv.svc.settings.get("min_rr", 1.5)), tp1_r=float(cfg.get("tp1_r", 1.0)), split=bool(cfg.get("split", True)),
                          max_lot=float(sv.trader.max_lot), spread=spec["spread"], max_spread_sl=float(cfg.get("max_spread_sl", 0.10)),
                          min_lot_fallback=bool(cfg.get("min_lot_fallback", False)), min_lot_max_risk_pct=float(cfg.get("min_lot_max_risk_pct", 8.0)))
        except at.PlanRefused as exc:
            return False, f"zdelka rejasi: {exc}"
        except Exception as exc:  # noqa: BLE001 — narx/balans olinmadi: ochilmaydigan signal yubormaymiz
            return False, f"reja tekshirilmadi: {str(exc)[:80]}"
        return True, ""

    def _cooldown(self, symbol: str) -> bool:
        cut = (self.sv.svc.clock() - timedelta(hours=self._limits()[1])).isoformat(timespec="seconds")  # servis soati (testda qotirilgan; jonli — hozirgi vaqt)
        return bool(self.db.one("SELECT 1 FROM signals WHERE strategy_id='ZONE-DIR' AND symbol=? AND created_at>?", (symbol, cut)))

    def _ensure_instrument(self, z: dict) -> None:
        """MT5 simvoli uchun ma'lumot manbasi va xarajat modeli (haqiqiy spred, komissiya yo'q). Xotirada; faqat urinilgan simvollar."""
        if z["source"] != "mt5":
            return
        from ..trading.signals import mt5_name
        spec = self.sv.trader.symbol_spec(mt5_name(z["symbol"]))
        mid = (spec["ask"] + spec["bid"]) / 2
        cat = (self.scanner.mt5_group.get(z["symbol"]) or "forex").lower()
        self.sv.svc.settings.data.setdefault("instruments", {})[z["symbol"]] = {
            "provider": "mt5", "market": cat, "spread_bps": round(spec["spread"] / mid * 1e4, 3), "commission_pct": 0.0, "fine_tf": "1m"}

    def _bundles(self, symbol: str):
        m = self.sv.svc.market
        return m.history(symbol, "1h", 320, need=250), m.history(symbol, "4h", 320, need=250), m.history(symbol, "15m", 320, need=120)

    def _setup(self, z: dict, test: bool = False, force: bool = False) -> tuple[Setup | None, str, object]:
        self._ensure_instrument(z)
        b, b4, b15 = self._bundles(z["symbol"])
        # MT5 (forex/indeks/metall): hafta oxiri/sessiya bo'shliqlari NORMAL; kripto uchun bo'shliq — ma'lumot sifati xatosi.
        warns = [w for bb in (b, b4, b15) for w in bb.warnings if not (z["source"] == "mt5" and "tushib qolgan" in w)]
        if warns:
            return None, "ma'lumot sifati: " + "; ".join(warns)[:120], b
        bars = [Bar(c.open, c.high, c.low, c.close) for c in b.candles]
        price, a = bars[-1].close, atr(bars)
        opposing = [] if test else self._opposing(z)  # test: TP=2R
        st = self.sv.svc.settings.instrument(z["symbol"])
        s, why = build_setup(z, price, a, opposing, min_rr=float(self.cfg["trade_min_rr"]), spread_bps=float(st.get("spread_bps", 2.0)),
                             commission_pct=float(st.get("commission_pct", 0.1)))
        if s is not None:
            s.symbol, s.last_end, s.source = z["symbol"], b.last_close_time, b.source
            ok_plan, why_plan = self._plan_ok(s)  # bajarib bo'lmaydigan zonalar (masalan 0.01 lot riski 8% dan katta) signalga aylanmaydi
            if not ok_plan:
                return None, why_plan, b
            f1, f4, f15 = Features.build(b.candles), Features.build(b4.candles), Features.build(b15.candles)
            near = None if force else self._near_obstacle(s, f1)
            if near:  # signal tizimining O'ZINING S/R qoidasi (evaluate): foyda tomonidagi eng yaqin swing kamida 1R uzoqda
                return None, near, b
            mkt = self.sv.svc.settings.instrument(z["symbol"]).get("market", "crypto")
            s.score = evaluate(s.direction == "LONG", f15, f1, f4, entry=s.entry, sl=s.sl, tp=s.tp, rr_net=s.rr_net,
                               min_rr=float(self.cfg["trade_min_rr"]), volume_kind="volume" if mkt == "crypto" else "tick")
        return s, why, b

    # ------------------------------------------------------------------ asosiy sikl
    def _enabled(self) -> tuple[bool, str]:
        sv = self.sv
        if not self.cfg["trade_enabled"]:
            return False, "zona zdelkasi o'chirilgan (zones.trade_enabled=false)"
        if sv.trade_mode != "auto":
            return False, "AUTO rejim yoqilmagan"
        if not sv.demo_enabled or sv.cfg.get("sizing") != "risk" or sv.trader is None:
            return False, "DEMO savdo/sizing=risk/MT5 trader yoqilmagan"
        return True, ""

    def _record(self, **kw) -> None:
        """Vazifa holati (DIR-1 savol berilganda HAQIQIY holatni aytishi va dashboard ko'rsatishi uchun)."""
        kw["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.db.execute("INSERT INTO meta(key, value) VALUES('zone_trade_status', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(kw, ensure_ascii=False),))

    def open_groups(self) -> int:
        return (self.db.one("SELECT COUNT(*) n FROM demo_groups WHERE status='OPEN'") or {}).get("n", 0)

    async def on_pass(self, manual: bool = False, test: bool = False, force: bool = False) -> None:
        desk = self.sv.desk
        ok, why = self._enabled()
        if not ok:
            self._record(enabled=False, why=why)
            if manual:
                desk.say(R.DIRECTOR.id, "system", f"Zona vazifasi bajarilmadi: {why}.", None)
            self.set_directive(None)
            desk.db.execute("INSERT INTO staff_activity(role, task, ts, counters) VALUES('DIR-1', ?, ?, '{}') ON CONFLICT(role) DO UPDATE SET task=excluded.task, ts=excluded.ts",
                            (f"Zona vazifasi to'xtab turibdi: {why}", datetime.now(timezone.utc).isoformat(timespec="seconds")))
            return
        if self.open_groups() >= int(self.sv.cfg.get("max_groups", 1)):
            self._record(enabled=True, state="ochiq pozitsiya bor (max guruh chegarasi) — yangi zdelka ochilmaydi, navbat tuziladi")
            if manual:
                desk.say(R.DIRECTOR.id, "system", "Zona vazifasi: ochiq zdelka guruhi chegarasi to'lgan — yangi zdelka ochilmaydi (navbat tuziladi).", None)
            await self.queue_mode()
            return
        self.set_directive(None)  # pozitsiya yo'q — odatiy qidiruv
        tried = 0
        cands = self._candidates()
        short, skipped = self._shortlist(cands, test, force)
        max_try = 1 if force else self._limits()[0]
        for z in short[: int(self.cfg["shortlist"])]:
            if tried >= max_try or self.open_groups() >= int(self.sv.cfg.get("max_groups", 1)):
                break
            if not force and self._cooldown(z["symbol"]):
                skipped.append(f"{z['symbol']}: {self.cfg['trade_cooldown_h']} soat kuldaun")
                continue
            try:
                s, why, b = await asyncio.to_thread(self._setup, z, test, force)
            except Exception as exc:  # noqa: BLE001 — bitta zona xatosi boshqalarni to'xtatmaydi
                log.warning("zona sozlamasi %s: %s", z["symbol"], exc)
                skipped.append(f"{z['symbol']}: {str(exc)[:90] or type(exc).__name__}")
                continue
            if s is None:
                skipped.append(f"{z['symbol']} {z['tf']} {z['kind']}: {why}")
                continue
            tried += 1
            if test:
                s.tp_note = "SINOV rejimi: qarshi zona hisobga olinmadi, TP = xarajatdan keyin 2R"
            await self.execute(s, b, force)
        counts: dict[str, int] = {}
        for x in skipped:
            k = "R/R yetmadi (kuchli qarshi zona yaqin)" if "R/R" in x else "kuldaun" if "kuldaun" in x else "zdelka rejasi (lot/spred)" if "zdelka rejasi" in x \
                else "ma'lumot sifati" if "ma'lumot" in x else "boshqa"
            counts[k] = counts.get(k, 0) + 1
        self._record(enabled=True, state="har skanerdan keyin tekshiriladi", candidates=len(cands), shortlisted=len(short), tried=tried, skip_counts=counts,
                     skipped=[x for x in skipped if "R/R" not in x][:6] or skipped[:6],
                     categories=list(self.cfg["trade_categories"]), today_opened=self.opened_today(), target=int(self.cfg["daily_target"]))
        await self._progress_report(skipped)
        if manual and not tried:
            total = (self.db.one("SELECT COUNT(*) n FROM zones WHERE status='active' AND source='binance'") or {}).get("n", 0)
            tw = [r for r in self.db.query("SELECT symbol, kind, strength FROM zones WHERE status='active' AND source='binance'") if self._tradable(r["symbol"])]
            weak = "; ".join(f"{r['symbol']} {r['kind']} kuch {r['strength']}" for r in tw[:4])
            desk.say(R.DIRECTOR.id, "report", f"Zona vazifasi: {total} aktiv Binance zonasi bor, lekin MT5 DEMO'da faqat BTC/ETH kabi bir nechta kripto savdo qilinadi: "
                     f"ulardan aktiv zona {len(tw)} ta{(' (' + weak + ')') if weak else ''}; kuch chegarasi {self.cfg['trade_min_strength']:g}, o'tgan nomzod {len(cands)} ta. "
                     "Sabablari: " + ("; ".join(skipped[:8]) or "chegaradan kuchli savdoga yaroqli zona yo'q") +
                     ". Yaxshi sharoit chiqquncha zdelka ochilmaydi (zonani zo'rlab ochmayman).", None)

    async def _progress_report(self, skipped: list[str]) -> None:
        """DIR-1: kunlik maqsad bo'yicha hisobot (soatiga ko'pi bilan 1 marta, chatda). Maqsad — niyat, kafolat emas."""
        now = datetime.now(timezone.utc)
        last = getattr(self, "_last_report", None)
        if last and (now - last).total_seconds() < 3600:
            return
        self._last_report = now
        n, tgt = self.opened_today(), int(self.cfg["daily_target"])
        why = "; ".join(skipped[:3]) or "nomzodlar bahs/himoyalardan o'tmadi"
        self.sv.desk.say(R.DIRECTOR.id, "report", f"Kunlik maqsad (Toshkent kuni): {n}/{tgt} zona zdelkasi ochildi. "
                         f"{'Maqsadga yetildi.' if n >= tgt else 'Orqadaman: faol rejim (bir o\'tishda ' + str(self._limits()[0]) + ' tagacha urinish, kuldaun ' + str(self._limits()[1]) + ' soat). Himoyalar (1% risk, SL, 5% kunlik zarar, DEMO) o\'zgarmaydi.'} "
                         f"So'nggi to'siqlar: {why}.", None)

    async def execute(self, s: Setup, bundle, force: bool = False) -> None:
        sv, desk = self.sv, self.sv.desk
        now = sv.svc.clock()
        z = s.zone
        desk.say(R.DIRECTOR.id, "assign", f"Zona vazifasi: {s.symbol} {s.direction} — {z['tf']} {z['kind']} zonasi {z['low']:.6g}-{z['high']:.6g} "
                 f"({z['detector']}, kuch {z['strength']}). Kirish {s.entry:.6g}, SL {s.sl:.6g}, TP {s.tp:.6g} (R/R {s.rr_net:.2f}; {s.tp_note}). "
                 "Bahsga topshiriladi; ruxsat bo'lsa zdelka himoyalar bilan DEMO'da ochiladi.", z["id"])
        cand = to_candidate(s, now, s.last_end, s.source)
        sig = sv.store(cand, now, "NEW", prefix="ZON")
        if not await sv.publish(sig["signal_id"], cand, header="🎯 DIR-1 zona vazifasi (zona asosidagi signal — strategiya testidan o'tmagan)", buttons=False):
            desk.say(R.DIRECTOR.id, "system", f"Zona signali yuborilmadi ({sig['signal_id']}) — zdelka ochilmadi.", z["id"])
            return
        if force:  # egasi buyrug'i (veb "Majburiy sinov"): bahs o'tkazib yuboriladi; ijro himoyalari (lot, SL, R/R, spred, kunlik zarar, DEMO) QOLADI
            desk.say(R.DIRECTOR.id, "assign", f"MAJBURIY SINOV (egasi buyrug'i): bahs o'tkazib yuborildi — {sig['signal_id']} to'g'ridan-to'g'ri ijro himoyalariga topshiriladi.", z["id"])
        elif not await sv.staff_gate(sig):
            dec = self.db.one("SELECT reason FROM staff_decisions WHERE ref=? ORDER BY id DESC LIMIT 1", (sig["signal_id"],)) or {}
            note = f"bahs rad etdi: {(dec.get('reason') or '')[:260]}"
            desk.say(R.DIRECTOR.id, "system", f"Bahs rad etdi ({sig['signal_id']}) — zdelka ochilmaydi.", z["id"])
            if sv._claim(sig["signal_id"], "REJECTED", note, by=0):  # tugmasiz signal osilib qolmasin: holat va xabar yopiladi
                await sv._finalize_message(self.db.one("SELECT * FROM signals WHERE signal_id=?", (sig["signal_id"],)), "REJECTED", note,
                                           "⛔ AUTO: bahs rad etdi — zdelka ochilmadi")
            return
        res = await sv.auto_confirm(sig["signal_id"], origin="forced_test" if force else None)  # majburiy sinov avtomatik zdelka sifatida sanalmaydi
        row = self.db.one("SELECT status, decision_note FROM signals WHERE signal_id=?", (sig["signal_id"],))
        desk.say(R.DIRECTOR.id, "verdict", f"Zona zdelkasi natijasi {sig['signal_id']}: {(res or row['decision_note'] or row['status'])[:260]}", z["id"])
        if row and row["status"] == "CONFIRMED" and self.open_groups():
            self.set_directive({"symbol": s.symbol, "signal": sig["signal_id"]}, announce=True)

    # ------------------------------------------------------------------ zdelka ochilgach: qolgan xodimlarga yangi shart
    def directive(self) -> dict | None:
        row = self.db.one("SELECT value FROM meta WHERE key='zone_directive'")
        try:
            return json.loads(row["value"]) if row else None
        except ValueError:
            return None

    def set_directive(self, d: dict | None, announce: bool = False) -> None:
        old = self.directive()
        if d is None:
            if old is not None:
                self.db.execute("DELETE FROM meta WHERE key='zone_directive'")
                self.sv.desk.say(R.DIRECTOR.id, "assign", "Pozitsiya yopildi/yo'q — zona qidiruvi odatiy tartibga qaytdi (shartlar bekor).", None)
            return
        d = {**d, "min_strength": float(self.cfg["trade_min_strength"]) + 10, "min_rr": float(self.cfg["queue_min_rr"]), "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if old and old.get("symbol") == d["symbol"]:
            return
        self.db.execute("INSERT INTO meta(key, value) VALUES('zone_directive', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(d),))
        if announce:
            text = (f"Zdelka ochildi ({d['symbol']}). Yangi shart ZONE-1..5 ga: 1) {d['symbol']} va unga bog'liq juftliklarni chetlab o'ting; "
                    f"2) faqat zona kuchi ≥ {d['min_strength']:g} bo'lgan aktiv zonalarni xabar qiling; 3) navbat uchun R/R ≥ {d['min_rr']:g} bo'lgan "
                    "tayyor rejalarni tuzing. Pozitsiya yopilguncha yangi zdelka ochilmaydi (guruhlar chegarasi).")
            self.sv.desk.say(R.DIRECTOR.id, "assign", text, d["signal"])
            for m in R.ZONES:
                self.sv.desk.say(m.id, "directive-ack", f"Shart qabul qilindi: {d['symbol']} chetlanadi, kuch ≥ {d['min_strength']:g}, navbat R/R ≥ {d['min_rr']:g}.", d["signal"])

    async def queue_mode(self) -> None:
        """Pozitsiya ochiq: yangi zdelka yo'q, lekin xodimlar navbat uchun tayyor reja tuzadi (shartga mos)."""
        d = self.directive() or {}
        open_sym = d.get("symbol")
        picks = []
        for z in self._candidates(8):
            if z["symbol"] == open_sym or z["strength"] < float(d.get("min_strength", 0)):
                continue
            try:
                s, why, _ = await asyncio.to_thread(self._setup, z)
            except Exception:  # noqa: BLE001
                continue
            if s is not None and s.rr_net >= float(d.get("min_rr", self.cfg["queue_min_rr"])):
                picks.append(s)
            if len(picks) >= 3:
                break
        self.db.execute("INSERT INTO meta(key, value) VALUES('zone_queue', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (json.dumps([{"symbol": p.symbol, "dir": p.direction, "entry": p.entry, "sl": p.sl, "tp": p.tp, "rr": round(p.rr_net, 2)} for p in picks]),))
        if picks:
            self.sv.desk.say(R.DIRECTOR.id, "report", "Navbat (pozitsiya yopilgach birinchi tekshiriladi): " +
                             "; ".join(f"{p.symbol} {p.direction} kirish {p.entry:.6g} SL {p.sl:.6g} TP {p.tp:.6g} R/R {p.rr_net:.2f}" for p in picks), None)
