"""Dashboard: xodimlar bo'limi, signallar, pozitsiyalar, boshqaruv. Ma'lumot FAQAT O'QISH (mode=ro).

Yagona yozuv: `control_commands` jadvaliga buyruq qo'yish (agent uni bajaradi va hamma himoyani o'zi tekshiradi).
Buyruq ro'yxati qat'iy; REAL hisobda buyurtma baribir DemoTrader tomonidan rad etiladi.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from ..staff import roster
from ..zones.categories import mt5_category  # noqa: F401 — yagona manba (agent va dashboard bir xil kategoriya)
from ..trading import lifecycle as lc
from ..trading.settings import DEFAULTS
from .agentstate import agent_status
from .trading_api import TradingView

COMMANDS = {"mode": {"analysis", "confirm", "auto"}, "stop": {""}, "flat": {""}, "review": None, "confirm": None, "reject": None, "say": None, "zone": {"", "test", "force"}}  # review/confirm/reject: signal_id


# Market Overview: Binance ochiq narxi. XAU/EUR/GBP uchun to'g'ridan-to'g'ri narx yo'q — taxminiy proksi (belgilanadi).
MARKET = (("BTCUSD", "BTCUSDT", "spot"), ("ETHUSD", "ETHUSDT", "spot"), ("XAUUSD", "PAXGUSDT", "proksi: PAXG (oltin)"),
          ("EURUSD", "EURUSDT", "proksi: EUR/USDT"), ("GBPUSD", "GBPUSDT", "proksi: GBP/USDT"))
_market_cache: dict = {"ts": 0.0, "data": None}


def _fetch_market() -> list[dict]:
    syms = json.dumps([m[1] for m in MARKET], separators=(",", ":"))
    url = "https://data-api.binance.vision/api/v3/ticker/24hr?symbols=" + urllib.request.quote(syms)
    with urllib.request.urlopen(url, timeout=6) as r:  # noqa: S310 — faqat https, ochiq narx
        raw = {x["symbol"]: x for x in json.loads(r.read().decode("utf-8"))}
    out = []
    for name, sym, note in MARKET:
        x = raw.get(sym)
        out.append({"symbol": name, "source": sym, "note": note,
                    "price": float(x["lastPrice"]) if x else None, "change_pct": float(x["priceChangePercent"]) if x else None})
    return out


_candle_cache: dict = {}
_probe_cache: dict = {}
_PROC_START = time.time()
_MT5_LOCK = threading.RLock()
TFS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d"}


def _fetch_candles(symbol: str, tf: str, limit: int = 400) -> list[dict]:
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={TFS[tf]}&limit={limit}"
    with urllib.request.urlopen(url, timeout=8) as r:  # noqa: S310 — faqat https, ochiq market-data
        raw = json.loads(r.read().decode("utf-8"))
    return [{"time": int(k[0] // 1000), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in raw]


SPOT_INFO = "https://data-api.binance.vision/api/v3/exchangeInfo"
FUT_INFO = {"futures-usdm": "https://fapi.binance.com/fapi/v1/exchangeInfo", "futures-coinm": "https://dapi.binance.com/dapi/v1/exchangeInfo"}
FUT_KLINES = {"futures-usdm": "https://fapi.binance.com/fapi/v1/klines", "futures-coinm": "https://dapi.binance.com/dapi/v1/klines"}
MARKETS = ("spot", "futures-usdm", "futures-coinm", "mt5")
_inst_cache: dict = {"ts": 0.0, "data": None}


def _get_json(url: str, timeout: float = 15):
    with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310 — faqat https, ochiq ma'lumot
        return json.loads(r.read().decode("utf-8"))


def _fetch_candles_market(symbol: str, tf: str, market: str, limit: int = 400) -> list[dict]:
    if market == "spot":
        return _fetch_candles(symbol, tf, limit)
    url = f"{FUT_KLINES[market]}?symbol={symbol}&interval={TFS[tf]}&limit={limit}"
    raw = _get_json(url, 8)
    return [{"time": int(k[0] // 1000), "open": float(k[1]), "high": float(k[2]), "low": float(k[3]), "close": float(k[4])} for k in raw]


def _norm_symbol(sym: str) -> str:
    """MT5 'BTCUSDm' -> 'BTCUSDT' (taqqoslash uchun)."""
    s = (sym or "").upper()
    s = s[:-1] if sym and sym[-1] == "m" else s
    return s + "T" if s.endswith("USD") else s


class _Safe:
    """Diagnostika uchun: jadval hali yo'q bo'lsa (agent yangi nusxada hali ishga tushmagan) xato emas, bo'sh natija."""

    def __init__(self, db):
        self._db = db

    def query(self, sql, params=()):
        try:
            return self._db.query(sql, params)
        except sqlite3.OperationalError:
            return []

    def one(self, sql, params=()):
        try:
            return self._db.one(sql, params)
        except sqlite3.OperationalError:
            return None

    def close(self):
        self._db.close()


def _has_col(db, table: str, col: str) -> bool:
    try:
        return any(r["name"] == col for r in db.query(f"PRAGMA table_info({table})"))
    except Exception:  # noqa: BLE001
        return False


def _exec_only(db) -> str:
    """paper_positions uchun filtr: faqat ijro qilinadigan to'plam (dataset ustuni hali yo'q bo'lsa — filtrsiz, eski sxema)."""
    return " AND COALESCE(dataset,'EXECUTABLE')='EXECUTABLE'" if _has_col(db, "paper_positions", "dataset") else ""


def _kinds_by_signal(db, ids: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        for r in db.query(f"SELECT signal_id, kind FROM signal_events WHERE signal_id IN ({','.join('?' * len(chunk))})", chunk):
            out.setdefault(r["signal_id"], set()).add(r["kind"])
    return out


_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def exec_counters(db, since: str) -> dict:
    """Bitta oyna uchun: alohida hisoblagichlar + voronka + to'xtash taqsimoti + sabablar (TEST signallar sanalmaydi)."""
    rows = db.query("SELECT * FROM signals WHERE created_at>=? AND signal_id NOT LIKE 'TST-%' ORDER BY created_at", (since,))
    ids = [r["signal_id"] for r in rows]
    kinds = _kinds_by_signal(db, ids)
    debated = {r["ref"] for r in db.query("SELECT DISTINCT ref FROM staff_decisions WHERE kind='signal'")} if ids else set()
    audit: dict[str, dict] = {}
    for r in db.query("SELECT * FROM execution_audit WHERE decision IN ('EXECUTED','EXECUTION_REFUSED','PRECHECK_REFUSED') ORDER BY id"):
        audit[r["signal_id"]] = r  # eng oxirgi ijro urinishi
    c = dict.fromkeys(("generated", "watch", "sent", "debate_approved", "debate_rejected", "risk_approved", "risk_refused", "execution_ready",
                       "mt5_executed", "manual_test_orders", "expired_invalidated", "owner_override_after_reject", "paper_only"), 0)
    stopped: dict[str, int] = {}
    reasons: dict[tuple, int] = {}
    for r in rows:
        sid, k = r["signal_id"], kinds.get(r["signal_id"], set())
        st = lc.derive_exec_status(r, k)
        org = lc.derive_origin(r, k, sid in debated)
        c["generated"] += 1
        c["watch"] += st == lc.WATCH
        c["sent"] += "sent" in k
        c["debate_approved"] += "staff_approve" in k
        c["debate_rejected"] += "staff_reject" in k
        a = audit.get(sid)
        if a is not None:
            passed, refused = a["risk_result"] == "passed", a["risk_result"] == "refused"
        else:  # eski yozuv: faqat signal_events dalili
            passed, refused = "demo_opened" in k, ("demo_refused" in k or "precheck_refused" in k) and "demo_opened" not in k
        c["risk_approved"] += passed
        c["risk_refused"] += refused
        c["execution_ready"] += st in (lc.EXECUTION_READY, lc.EXECUTED)
        c["paper_only"] += st == lc.EXECUTION_READY
        if st == lc.EXECUTED:
            if org == lc.ORIGIN_FORCED:
                c["manual_test_orders"] += 1
            else:
                c["mt5_executed"] += 1
        c["expired_invalidated"] += st in (lc.EXPIRED, lc.INVALIDATED)
        c["owner_override_after_reject"] += ("staff_reject" in k) and bool(k & {"demo_opened", "demo_refused"})
        if st != lc.EXECUTED:
            stopped[st] = stopped.get(st, 0) + 1
        for kind in ("demo_refused", "precheck_refused", "confirm_refused", "staff_reject", "invalidated", "expired"):
            if kind in k:
                ev = db.one("SELECT detail FROM signal_events WHERE signal_id=? AND kind=? ORDER BY id DESC LIMIT 1", (sid, kind))
                key = (kind, _NUM.sub("#", (ev or {}).get("detail") or "")[:110])
                reasons[key] = reasons.get(key, 0) + 1
    funnel = [{"stage": "GENERATED", "label": "Generated signals (barchasi)", "n": c["generated"]},
              {"stage": "SENT", "label": "Egasiga yuborildi", "n": c["sent"]},
              {"stage": "DEBATE_APPROVED", "label": "Debate approved", "n": c["debate_approved"]},
              {"stage": "RISK_APPROVED", "label": "Risk approved", "n": c["risk_approved"]},
              {"stage": "EXECUTION_READY", "label": "Execution ready", "n": c["execution_ready"]},
              {"stage": "EXECUTED", "label": "MT5 executed (avto/qo'lda, sinovsiz)", "n": c["mt5_executed"]}]
    top = sorted(reasons.items(), key=lambda kv: -kv[1])[:12]
    return {"counters": c, "funnel": funnel, "stopped_at": [{"status": s, "n": n} for s, n in sorted(stopped.items(), key=lambda kv: -kv[1])],
            "reasons": [{"kind": k[0], "reason": k[1], "n": n} for k, n in top]}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


class DeskView(TradingView):
    _mt5c = None  # MT5 o'qish ulanishi (kechiktirib ochiladi)

    def _jsons(self, row: dict, keys: tuple[str, ...]) -> dict:
        for k in keys:
            if isinstance(row.get(k), str):
                try:
                    row[k] = json.loads(row[k])
                except ValueError:
                    pass
        return row

    def market(self) -> dict:
        now = time.time()
        if _market_cache["data"] is not None and now - _market_cache["ts"] < 10:
            return _market_cache["data"]
        try:
            res = {"items": _fetch_market(), "error": None}
        except Exception as exc:  # noqa: BLE001 — tarmoq yo'q bo'lsa N/A ko'rsatiladi, soxta narx YO'Q
            res = {"items": [{"symbol": m[0], "source": m[1], "note": m[2], "price": None, "change_pct": None} for m in MARKET],
                   "error": f"Narx olinmadi: {exc}"}
        _market_cache.update(ts=now, data=res)
        return res

    def status(self) -> dict:
        """Header holatlari. Ma'lumot bo'lmasa None (frontend N/A ko'rsatadi) — soxta ONLINE YO'Q."""
        ag = agent_status((self.root.parent / "ish"))
        db = self._db()
        mt5_ts = research_ts = tg_last = None
        research = None
        if db is not None:
            try:
                b = db.one("SELECT value FROM meta WHERE key='account_balance'")
                mt5_ts = json.loads(b["value"]).get("ts") if b else None
                j = db.one("SELECT finished_at AS scheduled_at, status FROM jobs WHERE status IN ('done','failed') AND finished_at IS NOT NULL "
                           "ORDER BY finished_at DESC LIMIT 1")  # oxirgi BAJARILGAN ish (kelajakdagi pending emas)
                research = j
                research_ts = j["scheduled_at"] if j else None
                ns = db.one("SELECT MAX(sent_at) t FROM notifications WHERE status='SENT'")
                tg_last = (ns or {}).get("t")
            finally:
                db.close()

        def age(ts):
            try:
                d = datetime.fromisoformat(str(ts))
                d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
                return (datetime.now(timezone.utc) - d).total_seconds()
            except (TypeError, ValueError):
                return None
        a = age(mt5_ts)
        return {"agent": {"running": bool(ag.get("running")), "busy": bool((ag.get("control") or {}).get("busy")), "version": ag.get("version")},
                "mt5": {"connected": None if a is None else a < 300, "last": mt5_ts},
                "telegram": {"active": bool(ag.get("running")), "last_send": tg_last},  # polling holatini tashqaridan tekshirib bo'lmaydi: faqat agent + oxirgi muvaffaqiyatli yuborish
                "research": {"last_job": research_ts, "status": (research or {}).get("status"),
                     "fresh": (research or {}).get("status") == "done" and (age(research_ts) or 1e12) < 30 * 3600},
                "last_sync": mt5_ts, "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds")}

    def dashboard(self) -> dict:
        db = self._db()
        if db is None:
            return {"kpi": None}
        try:
            n_sig = db.one("SELECT COUNT(*) n FROM signals")["n"]
            n_open = db.one("SELECT COUNT(*) n FROM position_snapshot")["n"]
            nets = [r["net"] for r in db.query("SELECT net FROM live_trades WHERE net IS NOT NULL")]
            wins = [n for n in nets if n > 0]
            losses = [n for n in nets if n < 0]
            pf = round(sum(wins) / abs(sum(losses)), 2) if losses else None
            n_str = db.one("SELECT COUNT(DISTINCT strategy_id) n FROM strategies")["n"]
            paper = [r["r_multiple"] for r in db.query("SELECT r_multiple FROM paper_positions WHERE r_multiple IS NOT NULL" + _exec_only(db))]
            return {"kpi": {"signals": n_sig, "open_positions": n_open, "closed_n": len(nets),
                            "win_rate": round(100 * len(wins) / len(nets), 1) if nets else None, "profit_factor": pf,
                            "demo_net": round(sum(nets), 2) if nets else None, "paper_r": round(sum(paper), 2) if paper else None,
                            "strategies": n_str}}
        finally:
            db.close()

    # ------------------------------------------------------------------ System Diagnostics (haqiqiy monitoring ma'lumoti)
    def _probe(self, key: str, fn, ttl: float = 20.0) -> dict:
        """Zondlar (Binance/MT5) 20 soniya keshlanadi: har sahifa yangilanishida tashqi so'rov yuborilmasin."""
        now = time.time()
        hit = _probe_cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
        t0 = time.perf_counter()
        try:
            detail = fn()
            res = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "detail": detail, "error": None}
        except Exception as exc:  # noqa: BLE001
            res = {"ok": False, "ms": round((time.perf_counter() - t0) * 1000), "detail": None, "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
        _probe_cache[key] = (now, res)
        return res

    def diagnostics(self) -> dict:
        t_start = time.perf_counter()
        now = datetime.now(timezone.utc)

        def age_s(ts):
            try:
                d = datetime.fromisoformat(str(ts))
                d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
                return (now - d).total_seconds()
            except (TypeError, ValueError):
                return None

        def st(ts, ok_s, warn_s):
            a = age_s(ts)
            return "unknown" if a is None else "ok" if a <= ok_s else "warn" if a <= warn_s else "down"
        comps: list[dict] = []

        def add(cid, name, status, last=None, err=None, ms=None, ex=None, fail=None, detail=""):
            comps.append({"id": cid, "name": name, "status": status, "last_activity": last, "last_error": err, "processing_ms": ms,
                          "executions": ex, "failures": fail, "detail": detail})
        db = self._db()
        db = _Safe(db) if db is not None else None
        funnel: dict[str, int] = {}
        reasons: list[dict] = []
        tasks: list[dict] = []
        ag = agent_status(self.root.parent / "ish")
        add("backend", "Backend (dashboard)", "ok", last=now.isoformat(timespec="seconds"), ms=None,
            detail=f"jarayon {int(time.time() - _PROC_START)} soniyadan beri ishlayapti")
        if db is None:
            add("database", "Database", "down", err="baza fayli yo'q")
            return {"ts": now.isoformat(timespec="seconds"), "components": comps, "funnel": funnel, "reasons": reasons, "tasks": tasks}
        try:
            t0 = time.perf_counter()
            qc = db.one("PRAGMA quick_check") or {}
            qms = round((time.perf_counter() - t0) * 1000)
            size = self.db_path.stat().st_size / 1e6
            last_w = max([x for x in (db.one("SELECT MAX(ts) t FROM staff_messages") or {}).values() if x] +
                         [x for x in (db.one("SELECT MAX(ts) t FROM scan_log") or {}).values() if x] or [""])
            ok = list(qc.values())[:1] == ["ok"]
            add("database", "Database (SQLite)", "ok" if ok else "down", last=last_w or None, err=None if ok else str(qc), ms=qms,
                detail=f"{size:.1f} MB; quick_check={'ok' if ok else qc}")
            # Binance / MT5 zondlari
            b = self._probe("binance", lambda: _get_json("https://data-api.binance.vision/api/v3/time", 6))
            add("binance", "Binance connection", "ok" if b["ok"] else "down", last=now.isoformat(timespec="seconds") if b["ok"] else None,
                err=b["error"], ms=b["ms"], detail="data-api.binance.vision /time javob vaqti")

            def mt5_probe():
                with _MT5_LOCK:
                    if self._mt5c is None:
                        from ..trading.mt5_connector import MT5Connector
                        self._mt5c = MT5Connector.from_env(os.environ, state_file=self.root / "config" / "mt5_state.json")
                    self._mt5c.connect()
                    api = self._mt5c.mt5
                    ti = api.terminal_info()
                    bars = api.copy_rates_from_pos(self._mt5c.resolve("EURUSD"), api.TIMEFRAME_H1, 0, 5)
                    return {"connected": bool(ti.connected), "trade_allowed": bool(ti.trade_allowed), "bars": 0 if bars is None else len(bars)}
            m = self._probe("mt5", mt5_probe)
            ok_m = m["ok"] and (m["detail"] or {}).get("connected") and (m["detail"] or {}).get("bars", 0) > 0
            bal = db.one("SELECT value FROM meta WHERE key='account_balance'")
            bts = json.loads(bal["value"]).get("ts") if bal else None
            add("mt5", "MT5 connection", "ok" if ok_m else "down", last=bts, err=m["error"] or (None if ok_m else "terminal ulangan emas yoki shamlar yo'q"),
                ms=m["ms"], detail=f"terminal={m['detail']}; monitor balans yozuvi yoshi={int(age_s(bts) or -1)} s")
            # Research engine (rejalashtirilgan tahlil ishlari)
            jd = db.one("SELECT MAX(finished_at) t, COUNT(*) n FROM jobs WHERE status='done'") or {}
            jf = db.one("SELECT COUNT(*) n, MAX(last_error) e FROM jobs WHERE status='failed'") or {}
            jr = db.one("SELECT COUNT(*) n FROM jobs WHERE status='running'") or {}
            jp = db.one("SELECT MIN(scheduled_at) t, COUNT(*) n FROM jobs WHERE status='pending'") or {}
            add("research", "Research Engine (rejalashtirilgan tahlil)", st(jd.get("t"), 8 * 3600, 30 * 3600), last=jd.get("t"), err=(jf.get("e") or None),
                ex=jd.get("n"), fail=jf.get("n"), detail=f"keyingi: {jp.get('t')}, kutilayotgan {jp.get('n')}, hozir bajarilayotgan {jr.get('n')}")
            # Strategy engine + Signal generator (scan_log)
            since = (now - timedelta(hours=24)).isoformat(timespec="seconds")
            runs = db.query("SELECT ts, reason FROM scan_log WHERE stage='summary' AND ts>=? ORDER BY ts", (since,))
            last_run = runs[-1] if runs else None
            ms_list, fails = [], 0
            for r in runs:
                try:
                    j = json.loads(r["reason"])
                except ValueError:
                    continue
                for k, v in j.items():
                    if isinstance(v, int) and k not in ("ms", "n_errors"):
                        funnel[k] = funnel.get(k, 0) + v
                fails += int(j.get("n_errors", 0) > 0)
                funnel["n_errors"] = funnel.get("n_errors", 0) + int(j.get("n_errors", 0))
                if "ms" in j:
                    ms_list.append(j["ms"])
            funnel["scans"] = len(runs)
            add("strategy", "Strategy Engine (skaner)", "unknown" if not runs else st(last_run["ts"], 40 * 60, 3 * 3600), last=last_run["ts"] if last_run else None,
                ms=round(sum(ms_list) / len(ms_list)) if ms_list else None, ex=len(runs), fail=fails,
                detail="scan_log yozuvlari yo'q (agent yangi nusxada hali skan qilmagan)" if not runs else f"so'nggi 24 soatda {len(runs)} skan, {fails} tasi xatoli")
            sg = db.one("SELECT signal_id, created_at, symbol, tier, status FROM signals WHERE strategy_id!='ZONE-DIR' ORDER BY created_at DESC LIMIT 1")
            n24 = (db.one("SELECT COUNT(*) n FROM signals WHERE created_at>=?", (since,)) or {}).get("n", 0)
            add("signals", "Signal Generator", "ok" if sg else "unknown", last=sg["created_at"] if sg else None, ex=n24,
                detail=f"oxirgi: {sg['signal_id']} {sg['symbol']} {sg['tier']} {sg['status']}" if sg else "signal yo'q")
            la = db.one("SELECT MAX(created_at) t, COUNT(*) n FROM analyses") or {}
            add("analysis", "Last Successful Analysis (tadqiqot)", st(la.get("t"), 12 * 3600, 48 * 3600), last=la.get("t"), ex=la.get("n"))
            # AI agentlar
            act = db.query("SELECT role, task, ts FROM staff_activity")
            recent = [a for a in act if (age_s(a["ts"]) or 1e9) < 600]
            m24 = (db.one("SELECT COUNT(*) n FROM staff_messages WHERE ts>=?", (since,)) or {}).get("n", 0)
            sysm = db.query("SELECT ts, text FROM staff_messages WHERE kind='system' AND ts>=? ORDER BY id DESC LIMIT 20", (since,))
            errs = [x for x in sysm if any(w in x["text"] for w in ("bajarilmadi", "xato", "Xato", "yakunlanmadi"))]
            add("agents", "AI Agents (Claude xodimlari)", "ok" if recent else "warn", last=max([a["ts"] for a in act] or [None]) if act else None,
                err=errs[0]["text"][:140] if errs else None, ex=m24, fail=len(errs),
                detail=f"so'nggi 10 daqiqada faol: {len(recent)} ta xodim; 24 soatda {m24} ta xabar")
            zs = db.one("SELECT ts, task, counters FROM staff_activity WHERE role='ZONE-1'") or {}
            zc = {}
            try:
                zc = json.loads(zs.get("counters") or "{}")
            except ValueError:
                pass
            add("zones", "Zona skanerlari (ZONE-1..5)", st(zs.get("ts"), 15 * 60, 3600), last=zs.get("ts"), ms=round((zc.get("secs") or 0) * 1000) or None,
                fail=zc.get("errors"), detail=zs.get("task"))
            ns = db.one("SELECT MAX(sent_at) t, SUM(status='SENT') ok, SUM(status!='SENT') bad FROM notifications") or {}
            add("telegram", "Telegram Bot", "ok" if ag.get("running") else "down", last=ns.get("t"), ex=ns.get("ok"), fail=ns.get("bad"),
                detail="agent ishlayapti; polling holatini tashqaridan tekshirib bo'lmaydi — oxirgi muvaffaqiyatli yuborish ko'rsatilgan")
            add("scheduler", "Scheduler / agent jarayoni", "ok" if ag.get("running") else "down", last=ag.get("last_alive"), ex=None,
                detail=f"pid {ag.get('pid')}, versiya {ag.get('version')}, ishga tushgan {ag.get('started')}")
            # rad etishlar
            reasons = db.query("SELECT stage, COALESCE(strategy,'-') strategy, substr(reason,1,90) reason, COUNT(*) n FROM scan_log WHERE outcome='reject' AND ts>=? "
                               "GROUP BY 1,2,3 ORDER BY n DESC LIMIT 15", (since,))
            dr = db.query("SELECT 'risk/ijro' stage, '-' strategy, substr(detail,1,90) reason, COUNT(*) n FROM signal_events WHERE kind IN ('demo_refused','confirm_refused') "
                          "AND ts>=? GROUP BY 3 ORDER BY n DESC LIMIT 8", (since,))
            reasons += dr
            for r in db.query("SELECT role, task, ts FROM staff_activity WHERE ts>=?", ((now - timedelta(seconds=90)).isoformat(timespec="seconds"),)):
                tasks.append({"kind": "agent", "name": r["role"], "detail": r["task"], "ts": r["ts"]})
            for r in db.query("SELECT id, cmd, arg, status, ts FROM control_commands WHERE status IN ('pending','running')"):
                tasks.append({"kind": "buyruq", "name": f"#{r['id']} {r['cmd']}", "detail": r["arg"], "ts": r["ts"]})
            for t in ((ag.get("control") or {}).get("tasks") or []):
                tasks.append({"kind": "agent-vazifa", "name": str(t.get("id")), "detail": str(t.get("last") or t.get("text") or "")[:100], "ts": None})
            # voronka: DEMO ijro bosqichi (24 soat)
            funnel["demo_opened"] = (db.one("SELECT COUNT(*) n FROM demo_groups WHERE opened_at>=?", (since,)) or {}).get("n", 0)
            funnel["demo_refused"] = sum(r["n"] for r in dr)
            funnel["zone_signals"] = (db.one("SELECT COUNT(*) n FROM signals WHERE strategy_id='ZONE-DIR' AND created_at>=?", (since,)) or {}).get("n", 0)
        finally:
            db.close()
        return {"ts": now.isoformat(timespec="seconds"), "components": comps, "funnel": funnel, "reasons": reasons, "tasks": tasks,
                "build_ms": round((time.perf_counter() - t_start) * 1000)}

    def control_state(self) -> dict:
        cfg = {**DEFAULTS["signals"], **(self._settings().get("signals") or {})}  # faylda faqat o'zgartirilganlari turadi
        keep = ("mode", "trade_mode", "demo_orders", "sizing", "risk_pct", "split", "max_groups", "time_stop_h", "min_lot_fallback",
                "min_lot_max_risk_pct", "staff_gate", "breaker_losses", "breaker_dd_pct", "auto_min_tier", "daily_loss_pct", "target")
        db = self._db()
        cmds, bal = [], None
        if db is not None:
            try:
                cmds = db.query("SELECT id, ts, cmd, arg, status, result FROM control_commands ORDER BY id DESC LIMIT 15")
                b = db.one("SELECT value FROM meta WHERE key='account_balance'")
                bal = json.loads(b["value"]) if b else None
            finally:
                db.close()
        return {"settings": {k: cfg.get(k) for k in keep}, "commands": cmds, "balance": bal}

    def staff(self) -> dict:
        db = self._db()
        last: dict[str, dict] = {}
        act: dict[str, dict] = {}
        if db is not None:
            try:
                for r in db.query("SELECT role, MAX(id) id, MAX(ts) ts FROM staff_messages GROUP BY role"):
                    last[r["role"]] = r
                for r in db.query("SELECT role, task, ts, counters FROM staff_activity"):
                    act[r["role"]] = r
            finally:
                db.close()
        now = datetime.now(timezone.utc)
        out = []
        for m in roster.roster():
            a = act.get(m["id"]) or {}
            ts = max(filter(None, [(last.get(m["id"]) or {}).get("ts"), a.get("ts")]), default=None)
            age = None
            if ts:
                try:
                    age = (now - datetime.fromisoformat(ts)).total_seconds()
                except ValueError:
                    age = None
            try:
                counters = json.loads(a.get("counters") or "{}")
            except ValueError:
                counters = {}
            out.append({**m, "last_ts": ts, "active": age is not None and age < 90, "task": a.get("task"), "counters": counters})
        return {"members": out}

    def messages(self, after_id: int = 0, limit: int = 80) -> dict:
        db = self._db()
        if db is None:
            return {"items": []}
        try:
            if after_id > 0:
                rows = db.query("SELECT * FROM staff_messages WHERE id>? ORDER BY id LIMIT ?", (after_id, limit))
            else:
                rows = list(reversed(db.query("SELECT * FROM staff_messages ORDER BY id DESC LIMIT ?", (limit,))))
            return {"items": rows}
        finally:
            db.close()

    def signals(self) -> dict:
        db = self._db()
        if db is None:
            return {"items": []}
        try:
            rows = db.query("SELECT signal_id, created_at, symbol, timeframe, direction, strategy_id, entry, sl, tp, rr, score, tier, "
                            "status, decided_by, decision_note FROM signals ORDER BY created_at DESC LIMIT 80")
            verdicts = {r["ref"]: r for r in db.query("SELECT ref, approve, votes, reason, ts FROM staff_decisions WHERE kind='signal' ORDER BY id")}
            full = {r["signal_id"]: r for r in db.query("SELECT * FROM signals ORDER BY created_at DESC LIMIT 80")}
            kinds = _kinds_by_signal(db, list(full))
            for r in rows:
                v = verdicts.get(r["signal_id"])
                r["staff"] = None if v is None else {"approve": bool(v["approve"]), "reason": v["reason"], "votes": json.loads(v["votes"] or "{}")}
                f = full.get(r["signal_id"], r)
                r["exec_status"] = lc.derive_exec_status(f, kinds.get(r["signal_id"], ()))  # eski yozuvlar uchun hisoblanadi (bazaga yozilmaydi)
                r["origin"] = lc.derive_origin(f, kinds.get(r["signal_id"], ()), v is not None)
            return {"items": rows}
        finally:
            db.close()

    def _mt5_candles(self, symbol: str, tf: str, limit: int) -> list[dict]:
        """MT5 (forex, metall, indeks, aksiya, kripto): faqat O'QISH (ReadOnlyMT5). Ulanish dashboard jarayonida kechiktirib ochiladi."""
        with _MT5_LOCK:
            if self._mt5c is None:
                from ..trading.mt5_connector import MT5Connector
                self._mt5c = MT5Connector.from_env(os.environ, state_file=self.root / "config" / "mt5_state.json")
            cs = self._mt5c.candles(symbol, tf, limit)
        return [{"time": int(c.ts.timestamp()), "open": c.open, "high": c.high, "low": c.low, "close": c.close} for c in cs]

    def instruments(self, force: bool = False) -> dict:
        """Hamma instrumentlar HAQIQIY manbalardan: Binance spot (exchangeInfo), Binance Futures (agar ulanish bo'lsa), MT5 (symbols_get).
        Manba ulanmasa — o'sha bo'lim bo'sh va sababi `sources` da yoziladi (soxta ro'yxat YO'Q). 10 daqiqa kesh."""
        now = time.time()
        if not force and _inst_cache["data"] is not None and now - _inst_cache["ts"] < 600:
            return _inst_cache["data"]
        items: list[dict] = []
        sources: dict[str, dict] = {}
        zones: dict[tuple[str, str], int] = {}
        mt5_trade: set[str] = set()
        db = self._db()
        if db is not None:
            try:
                for r in db.query("SELECT symbol, source, SUM(status='active') a FROM zones GROUP BY symbol, source"):
                    zones[("mt5" if r["source"] == "mt5" else "spot", r["symbol"])] = int(r["a"] or 0)
            finally:
                db.close()
        # Binance spot
        try:
            info = _get_json(SPOT_INFO)
            n = 0
            for x in info.get("symbols", []):
                if x.get("status") != "TRADING":
                    continue
                n += 1
                items.append({"symbol": x["symbol"], "market": "spot", "category": "Crypto", "base": x.get("baseAsset"), "quote": x.get("quoteAsset"),
                              "zones": zones.get(("spot", x["symbol"]), 0)})
            sources["spot"] = {"ok": True, "count": n, "error": None}
        except Exception as exc:  # noqa: BLE001
            sources["spot"] = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        # Binance Futures (ulanish bo'lmasa — ochiq aytiladi)
        for mk, url in FUT_INFO.items():
            try:
                info = _get_json(url, 8)
                n = 0
                for x in info.get("symbols", []):
                    if x.get("status") not in ("TRADING", None) and x.get("contractStatus") not in ("TRADING", None):
                        continue
                    n += 1
                    items.append({"symbol": x["symbol"], "market": mk, "category": "Crypto", "base": x.get("baseAsset"), "quote": x.get("quoteAsset"), "zones": 0})
                sources[mk] = {"ok": True, "count": n, "error": None}
            except Exception as exc:  # noqa: BLE001
                sources[mk] = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        # MT5 (faqat o'qish)
        try:
            with _MT5_LOCK:
                if self._mt5c is None:
                    from ..trading.mt5_connector import MT5Connector
                    self._mt5c = MT5Connector.from_env(os.environ, state_file=self.root / "config" / "mt5_state.json")
                self._mt5c.connect()
                infos = list(self._mt5c.mt5.symbols_get() or [])
            for i in infos:
                items.append({"symbol": i.name, "market": "mt5", "category": mt5_category(i.name, getattr(i, "path", "") or ""),
                              "base": None, "quote": None, "tradable": getattr(i, "trade_mode", 0) == 4, "zones": zones.get(("mt5", i.name), 0)})
                if getattr(i, "trade_mode", 0) == 4:
                    mt5_trade.add(i.name.upper())
            sources["mt5"] = {"ok": True, "count": len(infos), "error": None}
        except Exception as exc:  # noqa: BLE001
            sources["mt5"] = {"ok": False, "count": 0, "error": f"{type(exc).__name__}: {str(exc)[:80]}"}
        for it in items:  # spot kripto: MT5 DEMO'da shu juftlik (BASEUSDm) bormi — "DEMO savdo" belgisi
            if it["market"] == "spot":
                it["tradable"] = it["symbol"].endswith("USDT") and (it["symbol"][:-1] + "m").upper() in mt5_trade
            elif it["market"] != "mt5":
                it["tradable"] = False
        res = {"items": items, "sources": sources, "ts": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _inst_cache.update(ts=now, data=res)
        return res

    def chart_symbols(self) -> dict:
        """Grafik uchun instrumentlar: skaner topgan zonalar va signallardan (barcha bozor: kripto + MT5)."""
        db = self._db()
        crypto: set[str] = set()
        mt5: set[str] = set()
        if db is not None:
            try:
                for r in db.query("SELECT DISTINCT symbol, source FROM zones"):
                    (crypto if r["source"] == "binance" else mt5).add(r["symbol"])
                for r in db.query("SELECT DISTINCT symbol FROM signals"):
                    crypto.add(r["symbol"]) if r["symbol"].endswith("USDT") else None
            finally:
                db.close()
        return {"crypto": sorted(crypto), "mt5": sorted(mt5)}

    def chart(self, symbol: str, tf: str = "1h", market: str = "") -> dict:
        """Grafik: shamlar (spot/futures — Binance ochiq, MT5 — o'qish) + agent o'zi yozgan ma'lumotdan chizmalar
        (signal Entry/SL/TP, zona, pozitsiya). Chizmalar bazadan olinadi — qo'lda chizish yo'q; ma'lumot bo'lmasa chizilmaydi."""
        symbol = (symbol or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9._#-]{1,24}", symbol):
            raise ApiError(400, "Noto'g'ri symbol")
        if tf not in TFS:
            raise ApiError(400, "Noto'g'ri taymfreym")
        if market and market not in MARKETS:
            raise ApiError(400, "Noto'g'ri bozor turi")
        syms = self.chart_symbols()
        if not market:  # eski chaqiruvlar (market berilmagan): zonalar jadvalidan aniqlash
            market = "mt5" if symbol in syms["mt5"] else "spot"
        if market != "mt5":
            symbol = symbol.upper()
        source = "mt5" if market == "mt5" else "binance"
        key, now = (market, symbol, tf), time.time()
        hit = _candle_cache.get(key)
        candles, error = [], None
        if hit and now - hit[0] < 10:
            candles = hit[1]
        else:
            try:
                candles = _fetch_candles_market(symbol, tf, market) if market != "mt5" else self._mt5_candles(symbol, tf, 400)
                _candle_cache[key] = (now, candles)
            except Exception as exc:  # noqa: BLE001 — tarmoq/manba yo'q: shamsiz, xato ochiq aytiladi
                error = f"Shamlar olinmadi ({market}): {exc}"
        levels, zones = [], []
        db = self._db() if market in ("spot", "mt5") else None  # futures uchun agent ma'lumoti yo'q
        if db is not None:
            try:
                rows = db.query("SELECT signal_id, created_at, direction, entry, sl, tp, status, tier, analysis FROM signals "
                                "WHERE symbol=? ORDER BY created_at DESC LIMIT 6", (symbol,))
                live = [r for r in rows if r["status"] in ("SENT", "CONFIRMING", "CONFIRMED")] or rows[:1]
                for r in live:
                    for kind, val in (("entry", r["entry"]), ("sl", r["sl"]), ("tp", r["tp"])):
                        if val:
                            levels.append({"kind": kind, "price": val, "label": f"{r['signal_id'][-4:]} {kind.upper()}", "side": r["direction"],
                                           "signal_id": r["signal_id"], "status": r["status"]})
                    try:
                        ev = (json.loads(r["analysis"] or "{}").get("evidence") or {})
                    except ValueError:
                        ev = {}
                    if ev.get("range_high") and ev.get("range_low"):
                        zones.append({"high": ev["range_high"], "low": ev["range_low"], "label": f"Zona {r['signal_id'][-4:]}", "kind": "range", "tf": "1h",
                                      "detector": "SIGNAL", "strength": None, "signal_id": r["signal_id"], "status": r["status"]})
                for z in db.query("SELECT id, detector, kind, tf, low, high, status, strength FROM zones WHERE symbol=? "
                                  "ORDER BY (status='active') DESC, strength DESC LIMIT 40", (symbol,)):
                    zones.append({"high": z["high"], "low": z["low"], "label": f"{z['detector']} {z['kind']} {z['tf']}", "kind": z["kind"], "tf": z["tf"],
                                  "detector": z["detector"], "strength": z["strength"], "signal_id": None, "status": z["status"].upper()})
                for p in db.query("SELECT position_id, symbol, side, price_open, sl, tp, profit FROM position_snapshot"):
                    same = p["symbol"] == symbol if source == "mt5" else _norm_symbol(p["symbol"]) == symbol
                    if not same:
                        continue
                    levels.append({"kind": "position", "price": p["price_open"], "label": f"POS {p['position_id']} {p['side']} P/L {p['profit']}",
                                   "side": p["side"], "signal_id": None, "status": "OPEN"})
                    for kind, val in (("sl", p["sl"]), ("tp", p["tp"])):
                        if val:
                            levels.append({"kind": kind, "price": val, "label": f"POS {p['position_id']} {kind.upper()}", "side": p["side"], "signal_id": None, "status": "OPEN"})
            finally:
                db.close()
        return {"symbol": symbol, "tf": tf, "market": market, "source": source, "candles": candles, "levels": levels, "zones": zones,
                "symbols": syms["crypto"] + syms["mt5"], "groups": syms, "error": error}

    def zones(self, status: str = "", symbol: str = "") -> dict:
        db = self._db()
        if db is None:
            return {"items": [], "summary": {}, "universe": None}
        try:
            where, params = [], []
            if status in ("active", "fresh"):
                where.append("status=?")
                params.append(status)
            if symbol:
                where.append("symbol=?")
                params.append(symbol)
            sql = ("SELECT id, symbol, source, detector, kind, tf, low, high, strength, note, status, dist_atr, price, first_seen, last_seen, watch "
                   "FROM zones" + (" WHERE " + " AND ".join(where) if where else "") +
                   " ORDER BY (status='active') DESC, watch DESC, dist_atr, strength DESC LIMIT 400")
            items = db.query(sql, tuple(params))
            summary = {"total": (db.one("SELECT COUNT(*) n FROM zones") or {}).get("n", 0),
                       "active": (db.one("SELECT COUNT(*) n FROM zones WHERE status='active'") or {}).get("n", 0),
                       "symbols": (db.one("SELECT COUNT(DISTINCT symbol) n FROM zones") or {}).get("n", 0),
                       "by_detector": db.query("SELECT detector, COUNT(*) n, SUM(status='active') active FROM zones GROUP BY detector ORDER BY detector")}
            u = db.one("SELECT value FROM meta WHERE key='zone_universe'")
            st = db.one("SELECT value FROM meta WHERE key='zone_trade_status'")
            tk0 = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5))).replace(hour=0, minute=0, second=0, microsecond=0)
            today = (db.one("SELECT COUNT(*) n FROM demo_groups WHERE signal_id LIKE 'ZON-%' AND opened_at >= ?",
                            (tk0.astimezone(timezone.utc).isoformat(timespec="seconds"),)) or {}).get("n", 0)
            try:
                trade = json.loads(st["value"]) if st else {}
            except ValueError:
                trade = {}
            trade["today_opened"] = today  # Toshkent kuni bo'yicha, bazadan (DIR-1 yozuviga bog'liq emas)
            recent = db.query("SELECT s.signal_id, s.symbol, s.direction, s.status, s.created_at, s.decision_note, "
                              "(SELECT approve FROM staff_decisions d WHERE d.ref=s.signal_id AND d.kind='signal' ORDER BY d.id DESC LIMIT 1) AS approve, "
                              "(SELECT reason FROM staff_decisions d WHERE d.ref=s.signal_id AND d.kind='signal' ORDER BY d.id DESC LIMIT 1) AS reason "
                              "FROM signals s WHERE s.strategy_id='ZONE-DIR' ORDER BY s.created_at DESC LIMIT 8")
            return {"items": items, "summary": summary, "universe": json.loads(u["value"]) if u else None, "trade": trade, "recent": recent}
        finally:
            db.close()

    def execution(self) -> dict:
        """Ijro voronkasi va alohida hisoblagichlar (bugun — Toshkent kuni, 7 kun, hammasi). Hamma qiymat bazadan: signals + signal_events
        + execution_audit. Eski yozuvlar uchun ijro holati hisoblanadi (derive_exec_status); bazadagi tarix o'zgarmaydi."""
        db = self._db()
        if db is None:
            return {"windows": {}, "error": "Trading bazasi yo'q"}
        try:
            sdb = _Safe(db)
            tk = timezone(timedelta(hours=5))
            now = datetime.now(timezone.utc)
            day0 = now.astimezone(tk).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            wins = {"today": day0, "7d": now - timedelta(days=7), "all": datetime(2000, 1, 1, tzinfo=timezone.utc)}
            return {"windows": {k: exec_counters(sdb, v.isoformat(timespec="seconds")) for k, v in wins.items()},
                    "since_today_utc": day0.isoformat(timespec="seconds"), "ts": now.isoformat(timespec="seconds"),
                    "note": "GENERATED = barcha signallar (WATCH ham); CONFIRMED (eski holat) ijro degani EMAS — faqat EXECUTED MT5 DEMO order_send."}
        finally:
            db.close()

    def signal_detail(self, signal_id: str) -> dict:
        db = self._db()
        if db is None:
            raise ApiError(404, "Trading bazasi yo'q")
        try:
            row = db.one("SELECT * FROM signals WHERE signal_id=?", (signal_id,))
            if row is None:
                raise ApiError(404, "Signal topilmadi")
            row = self._jsons(row, ("analysis", "invalidation"))
            row.pop("text", None)
            kinds = _kinds_by_signal(db, [signal_id]).get(signal_id, set())
            dec = db.one("SELECT 1 x FROM staff_decisions WHERE kind='signal' AND ref=?", (signal_id,))
            row["exec_status"] = lc.derive_exec_status(row, kinds)
            row["origin"] = lc.derive_origin(row, kinds, dec is not None)
            return {"signal": row, "execution_audit": _Safe(db).query("SELECT ts, origin, debate_result, risk_result, decision, stage, reason, "
                                                                      "mt5_request, mt5_retcode FROM execution_audit WHERE signal_id=? ORDER BY id", (signal_id,)),
                    "events": db.query("SELECT ts, kind, detail FROM signal_events WHERE signal_id=? ORDER BY id", (signal_id,)),
                    "messages": db.query("SELECT id, ts, role, kind, text FROM staff_messages WHERE ref=? ORDER BY id", (signal_id,)),
                    "decision": db.one("SELECT ts, approve, votes, reason FROM staff_decisions WHERE kind='signal' AND ref=? ORDER BY id DESC LIMIT 1", (signal_id,))}
        finally:
            db.close()

    def positions(self) -> dict:
        db = self._db()
        if db is None:
            return {"open": [], "groups": [], "closed": [], "paper": [], "totals": {}}
        try:
            open_rows = db.query("SELECT * FROM position_snapshot ORDER BY opened_at")
            groups = [self._jsons(g, ("tickets", "legs")) for g in
                      db.query("SELECT * FROM demo_groups ORDER BY opened_at DESC LIMIT 30")]
            closed = db.query("SELECT position_id, symbol, direction, strategy, opened_at, closed_at, net, r_multiple, reason, source "
                              "FROM live_trades ORDER BY closed_at DESC LIMIT 60")
            nets = [c["net"] for c in closed if c["net"] is not None]
            totals = {"open_profit": round(sum(p["profit"] or 0 for p in open_rows), 2), "closed_n": len(nets),
                      "closed_net": round(sum(nets), 2), "wins": sum(1 for n in nets if n > 0), "losses": sum(1 for n in nets if n < 0)}
            pcols = ("signal_id, symbol, direction, entry_type, entry_signal, sl, tp, confirmed_at, status, entry_price, "
                     "exit_time, exit_price, r_multiple, note")
            if _has_col(db, "paper_positions", "dataset"):  # to'rt turdagi ma'lumot ARALASHTIRILMAYDI
                def ds(name: str) -> list[dict]:
                    return db.query(f"SELECT {pcols}, COALESCE(dataset,'EXECUTABLE') AS dataset FROM paper_positions "
                                    "WHERE COALESCE(dataset,'EXECUTABLE')=? ORDER BY confirmed_at DESC LIMIT 60", (name,))
                paper, counterfactual, tests = ds(lc.DS_EXECUTABLE), ds(lc.DS_COUNTERFACTUAL), ds(lc.DS_TEST)
            else:
                paper = db.query(f"SELECT {pcols} FROM paper_positions ORDER BY confirmed_at DESC LIMIT 60")
                counterfactual, tests = [], []
            return {"open": open_rows, "groups": groups, "closed": closed, "paper": paper, "counterfactual": counterfactual,
                    "tests": tests, "totals": totals}
        finally:
            db.close()

    def command(self, cmd: str, arg: str = "") -> dict:
        if cmd not in COMMANDS:
            raise ApiError(400, "Noma'lum buyruq")
        arg = "".join(ch for ch in (arg or "") if ch.isprintable()).strip()[:500 if cmd == "say" else 60]
        if cmd == "say" and len(arg) < 2:
            raise ApiError(400, "Xabar bo'sh")
        allowed = COMMANDS[cmd]
        if allowed is not None and arg not in allowed:
            raise ApiError(400, "Noto'g'ri argument")
        if cmd in ("review", "confirm", "reject") and not arg.replace("-", "").replace("_", "").isalnum():
            raise ApiError(400, "Signal ID noto'g'ri")
        if not self.db_path.is_file():
            raise ApiError(503, "Trading bazasi yo'q")
        conn = sqlite3.connect(self.db_path.as_posix(), timeout=10)
        try:
            cur = conn.execute("INSERT INTO control_commands(ts, cmd, arg, source, status) VALUES(?,?,?,'web','pending')",
                               (datetime.now(timezone.utc).isoformat(timespec="seconds"), cmd, arg))
            conn.commit()
            return {"id": cur.lastrowid, "status": "pending"}
        except sqlite3.OperationalError as exc:
            raise ApiError(503, f"Baza hali tayyor emas: {exc}") from exc
        finally:
            conn.close()

    def command_status(self, cid: int) -> dict:
        db = self._db()
        if db is None:
            raise ApiError(404, "Yo'q")
        try:
            row = db.one("SELECT id, cmd, arg, status, result, done_at FROM control_commands WHERE id=?", (cid,))
        finally:
            db.close()
        if row is None:
            raise ApiError(404, "Buyruq topilmadi")
        return row
