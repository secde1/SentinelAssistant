"""trading_research.db — asosiy manba (authoritative). SQLite, WAL.

O'zgarmaslik kafolati BAZA darajasida (trigger): tahlil (analyses) va natija hodisalari (outcome_events) o'zgartirilmaydi
va o'chirilmaydi; strategiya versiyasining qoidalari (params) o'zgartirilmaydi — o'zgarish faqat yangi versiya bilan.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS strategies (
  strategy_id TEXT NOT NULL, version INTEGER NOT NULL, name TEXT NOT NULL, description TEXT, params TEXT NOT NULL,
  regimes TEXT NOT NULL, entry_rules TEXT, exit_rules TEXT, risk TEXT, status TEXT NOT NULL,
  created_at TEXT NOT NULL, created_by TEXT, parent_version INTEGER, notes TEXT,
  PRIMARY KEY (strategy_id, version));
CREATE TRIGGER IF NOT EXISTS strategies_rules_frozen BEFORE UPDATE OF params, regimes, entry_rules, exit_rules, risk
  ON strategies BEGIN SELECT RAISE(ABORT, 'strategy version rules are immutable: create a new version'); END;

CREATE TABLE IF NOT EXISTS strategy_stats (
  id INTEGER PRIMARY KEY, strategy_id TEXT, version INTEGER, symbol TEXT, timeframe TEXT, period_start TEXT,
  period_end TEXT, sample_size INTEGER, win_rate REAL, avg_rr REAL, expectancy REAL, max_dd REAL, ambiguous INTEGER,
  costs TEXT, source TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS analyses (
  analysis_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, local_date TEXT NOT NULL, timezone TEXT NOT NULL,
  symbol TEXT NOT NULL, timeframe TEXT NOT NULL, session TEXT, kind TEXT NOT NULL, regime TEXT, structure TEXT,
  strategy_id TEXT, strategy_version INTEGER, direction TEXT, entry_type TEXT, entry REAL, sl REAL, tp REAL, rr REAL,
  rr_net REAL, invalidation TEXT, valid_until TEXT, max_hold_bars INTEGER, evidence TEXT, assumptions TEXT,
  limitations TEXT, data_source TEXT, data_ts TEXT, data_fetched_at TEXT, costs TEXT, payload TEXT NOT NULL,
  content_hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS analyses_no_update BEFORE UPDATE ON analyses
  BEGIN SELECT RAISE(ABORT, 'analyses are immutable'); END;
CREATE TRIGGER IF NOT EXISTS analyses_no_delete BEFORE DELETE ON analyses
  BEGIN SELECT RAISE(ABORT, 'analyses are immutable'); END;

CREATE TABLE IF NOT EXISTS publications (
  ref TEXT NOT NULL, chat_id INTEGER NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, message_id INTEGER,
  text_hash TEXT, created_at TEXT, sent_at TEXT, error TEXT, PRIMARY KEY (ref, chat_id, kind));

CREATE TABLE IF NOT EXISTS outcomes (
  analysis_id TEXT PRIMARY KEY, status TEXT NOT NULL, entry_time TEXT, entry_price REAL, exit_time TEXT,
  exit_price REAL, r_multiple REAL, cost_r REAL, last_bar_ts TEXT, updated_at TEXT, note TEXT, data_source TEXT);
CREATE TABLE IF NOT EXISTS outcome_events (
  id INTEGER PRIMARY KEY, analysis_id TEXT NOT NULL, market_ts TEXT, recorded_at TEXT NOT NULL, from_status TEXT,
  to_status TEXT NOT NULL, price REAL, detail TEXT);
CREATE TRIGGER IF NOT EXISTS outcome_events_no_update BEFORE UPDATE ON outcome_events
  BEGIN SELECT RAISE(ABORT, 'outcome events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS outcome_events_no_delete BEFORE DELETE ON outcome_events
  BEGIN SELECT RAISE(ABORT, 'outcome events are append-only'); END;

CREATE TABLE IF NOT EXISTS sl_reviews (
  analysis_id TEXT PRIMARY KEY, created_at TEXT, strategy_id TEXT, strategy_version INTEGER, classification TEXT,
  factors TEXT, evidence TEXT);
CREATE TABLE IF NOT EXISTS experiments (
  experiment_id TEXT PRIMARY KEY, created_at TEXT, strategy_id TEXT, base_version INTEGER, candidate_version INTEGER,
  problem TEXT, hypothesis TEXT, data TEXT, costs TEXT, results TEXT, verdict TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS research_sources (
  id INTEGER PRIMARY KEY, topic TEXT, url TEXT, title TEXT, publisher TEXT, published_at TEXT, retrieved_at TEXT,
  summary TEXT, evidence_type TEXT, task_id TEXT, UNIQUE (url, topic));
CREATE TABLE IF NOT EXISTS jobs (
  job_key TEXT PRIMARY KEY, kind TEXT, scheduled_at TEXT, status TEXT, attempts INTEGER DEFAULT 0, last_error TEXT,
  started_at TEXT, finished_at TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS reports (
  report_id TEXT PRIMARY KEY, kind TEXT, period_start TEXT, period_end TEXT, created_at TEXT, text TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS data_warnings (
  id INTEGER PRIMARY KEY, ts TEXT, symbol TEXT, timeframe TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS chart_annotations (
  id INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL, fingerprint TEXT NOT NULL, file TEXT, created_at TEXT,
  validation TEXT, clipboard INTEGER, source TEXT, UNIQUE (fingerprint));
CREATE TABLE IF NOT EXISTS chart_verifications (
  id INTEGER PRIMARY KEY, scenario_id TEXT NOT NULL, ts TEXT, device TEXT, state TEXT, screenshot TEXT,
  evidence TEXT, status TEXT);
CREATE INDEX IF NOT EXISTS idx_analyses_date ON analyses(local_date);
CREATE INDEX IF NOT EXISTS idx_events_analysis ON outcome_events(analysis_id);

CREATE TABLE IF NOT EXISTS signals (
  signal_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, symbol TEXT NOT NULL, timeframe TEXT, direction TEXT NOT NULL,
  strategy_id TEXT, strategy_version INTEGER, entry_type TEXT, entry REAL, sl REAL, tp REAL, rr REAL, rr_net REAL,
  score INTEGER, tier TEXT, status TEXT NOT NULL, valid_until TEXT, data_ts TEXT, data_source TEXT, analysis TEXT,
  invalidation TEXT, text TEXT, chat_id INTEGER, message_id INTEGER, decided_at TEXT, decided_by INTEGER,
  decision_note TEXT);
CREATE INDEX IF NOT EXISTS idx_signals_sym ON signals(symbol, direction, status);
CREATE TABLE IF NOT EXISTS paper_positions (
  signal_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, direction TEXT NOT NULL, entry_type TEXT, entry_signal REAL,
  sl REAL, tp REAL, confirmed_at TEXT NOT NULL, data_end TEXT, valid_until TEXT, status TEXT NOT NULL, spread REAL,
  commission REAL, max_hold INTEGER, invalidation TEXT, entry_time TEXT, entry_price REAL, exit_time TEXT,
  exit_price REAL, r_multiple REAL, cost_r REAL, last_bar_ts TEXT, note TEXT, notified TEXT, trend_warned INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS mt5_positions (
  position_id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, volume REAL, entry REAL, sl REAL, tp REAL, opened_at TEXT,
  magic INTEGER, state TEXT NOT NULL, notified_open INTEGER DEFAULT 1, first_seen_at TEXT, last_sl REAL, last_tp REAL,
  closed_at TEXT, close_reason TEXT, net REAL);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, key TEXT UNIQUE NOT NULL, kind TEXT, target TEXT, text TEXT NOT NULL, status TEXT NOT NULL,
  attempts INTEGER DEFAULT 0, next_try TEXT, ambiguous INTEGER DEFAULT 0, message_id INTEGER, created_at TEXT, sent_at TEXT,
  error TEXT);
CREATE TABLE IF NOT EXISTS live_trades (
  position_id INTEGER PRIMARY KEY, strategy TEXT, symbol TEXT, direction TEXT, opened_at TEXT, closed_at TEXT, net REAL,
  r_multiple REAL, reason TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS position_snapshot (
  position_id INTEGER PRIMARY KEY, symbol TEXT, side TEXT, volume REAL, price_open REAL, sl REAL, tp REAL, profit REAL, swap REAL,
  magic INTEGER, opened_at TEXT, ts TEXT);
CREATE TABLE IF NOT EXISTS scan_log (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, symbol TEXT NOT NULL, stage TEXT NOT NULL, strategy TEXT, outcome TEXT NOT NULL, reason TEXT);
CREATE INDEX IF NOT EXISTS idx_scan_log_ts ON scan_log(ts);
CREATE TABLE IF NOT EXISTS zones (
  id TEXT PRIMARY KEY, symbol TEXT NOT NULL, source TEXT, detector TEXT, kind TEXT, tf TEXT, low REAL, high REAL, strength REAL,
  note TEXT, status TEXT, dist_atr REAL, price REAL, first_seen TEXT, last_seen TEXT, announced_at TEXT, watch INTEGER DEFAULT 0, atr REAL);
CREATE INDEX IF NOT EXISTS idx_zones_sym ON zones(symbol, status);
CREATE TABLE IF NOT EXISTS staff_activity (role TEXT PRIMARY KEY, task TEXT, ts TEXT, counters TEXT);
CREATE TABLE IF NOT EXISTS staff_messages (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, role TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, ref TEXT);
CREATE INDEX IF NOT EXISTS ix_staff_messages_ref ON staff_messages(ref);
CREATE TABLE IF NOT EXISTS staff_decisions (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL, ref TEXT, approve INTEGER, votes TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS control_commands (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, cmd TEXT NOT NULL, arg TEXT, source TEXT, status TEXT NOT NULL,
  result TEXT, done_at TEXT);
CREATE TABLE IF NOT EXISTS demo_groups (
  signal_id TEXT PRIMARY KEY, symbol TEXT, side TEXT, tickets TEXT, legs TEXT, sl REAL, risk_money REAL, risk_actual REAL,
  mode TEXT, opened_at TEXT, closed_at TEXT, status TEXT NOT NULL, note TEXT);
CREATE TABLE IF NOT EXISTS execution_audit (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, signal_id TEXT NOT NULL, symbol TEXT, origin TEXT, debate_result TEXT,
  risk_result TEXT, decision TEXT NOT NULL, stage TEXT NOT NULL, reason TEXT, mt5_request TEXT, mt5_retcode INTEGER, detail TEXT);
CREATE INDEX IF NOT EXISTS idx_exec_audit_sig ON execution_audit(signal_id);
CREATE INDEX IF NOT EXISTS idx_exec_audit_ts ON execution_audit(ts);
CREATE TABLE IF NOT EXISTS signal_events (
  id INTEGER PRIMARY KEY, signal_id TEXT NOT NULL, ts TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


class TradingDB:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            self._migrate()
            self.conn.commit()

    def _migrate(self) -> None:
        """V32: ustunlar qo'shiladi (mavjud ma'lumot o'chirilmaydi/o'zgartirilmaydi); paper_positions.dataset eski yozuvlar uchun
        FAQAT dalilga ko'ra to'ldiriladi (idempotent: faqat NULL qatorlar)."""
        def cols(t: str) -> set[str]:
            return {r[1] for r in self.conn.execute(f"PRAGMA table_info({t})")}
        for table, col in (("signals", "exec_status"), ("signals", "origin"), ("paper_positions", "dataset")):
            if col not in cols(table):
                self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT")
        self.conn.execute(
            "UPDATE paper_positions SET dataset = CASE "
            "WHEN signal_id LIKE 'TST-%' THEN 'TEST' "
            "WHEN EXISTS(SELECT 1 FROM signal_events e WHERE e.signal_id=paper_positions.signal_id AND e.kind='demo_refused') THEN 'COUNTERFACTUAL' "
            "WHEN signal_id LIKE 'ZON-%' AND EXISTS(SELECT 1 FROM signal_events e WHERE e.signal_id=paper_positions.signal_id AND e.kind='auto_confirm') "
            "AND NOT EXISTS(SELECT 1 FROM staff_decisions d WHERE d.kind='signal' AND d.ref=paper_positions.signal_id) THEN 'TEST' "
            "ELSE 'EXECUTABLE' END WHERE dataset IS NULL")

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    # ------------------------------------------------------------------ umumiy
    def execute(self, sql: str, params: Iterable = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Iterable = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def next_counter(self, name: str) -> int:
        with self._lock:
            row = self.conn.execute("SELECT value FROM counters WHERE name=?", (name,)).fetchone()
            value = (row[0] if row else 0) + 1
            self.conn.execute("INSERT INTO counters(name, value) VALUES(?, ?) ON CONFLICT(name) DO UPDATE SET value=?",
                              (name, value, value))
            self.conn.commit()
            return value

    def set_meta(self, key: str, value: Any) -> None:
        self.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, dumps(value)))

    def get_meta(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM meta WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    # ------------------------------------------------------------------ tahlillar
    def insert_analysis(self, record: dict) -> None:
        cols = ["analysis_id", "created_at", "local_date", "timezone", "symbol", "timeframe", "session", "kind",
                "regime", "structure", "strategy_id", "strategy_version", "direction", "entry_type", "entry", "sl",
                "tp", "rr", "rr_net", "invalidation", "valid_until", "max_hold_bars", "evidence", "assumptions",
                "limitations", "data_source", "data_ts", "data_fetched_at", "costs", "payload", "content_hash"]
        values = [record.get(c) if not isinstance(record.get(c), (dict, list)) else dumps(record.get(c)) for c in cols]
        self.execute(f"INSERT INTO analyses({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})", values)

    def analysis(self, analysis_id: str) -> dict | None:
        return self.one("SELECT * FROM analyses WHERE analysis_id=?", (analysis_id,))

    # ------------------------------------------------------------------ natijalar
    def outcome(self, analysis_id: str) -> dict | None:
        return self.one("SELECT * FROM outcomes WHERE analysis_id=?", (analysis_id,))

    def upsert_outcome(self, analysis_id: str, **fields: Any) -> None:
        fields["updated_at"] = utcnow()
        cur = self.outcome(analysis_id)
        if cur is None:
            cols = ["analysis_id"] + list(fields)
            self.execute(f"INSERT INTO outcomes({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                         [analysis_id] + list(fields.values()))
        else:
            sets = ", ".join(f"{k}=?" for k in fields)
            self.execute(f"UPDATE outcomes SET {sets} WHERE analysis_id=?", list(fields.values()) + [analysis_id])

    def add_event(self, analysis_id: str, from_status: str | None, to_status: str, market_ts: str | None,
                  price: float | None, detail: str = "") -> None:
        self.execute("INSERT INTO outcome_events(analysis_id, market_ts, recorded_at, from_status, to_status, price, "
                     "detail) VALUES(?,?,?,?,?,?,?)", (analysis_id, market_ts, utcnow(), from_status, to_status, price,
                                                       detail))

    # ------------------------------------------------------------------ nashrlar (dublikatsiz)
    def publication(self, ref: str, chat_id: int, kind: str) -> dict | None:
        return self.one("SELECT * FROM publications WHERE ref=? AND chat_id=? AND kind=?", (ref, chat_id, kind))

    def claim_publication(self, ref: str, chat_id: int, kind: str, text_hash: str) -> bool:
        """Yuborishdan OLDIN yozuv ('sending'). Allaqachon bor bo'lsa — False (qayta yuborilmaydi)."""
        try:
            self.execute("INSERT INTO publications(ref, chat_id, kind, status, text_hash, created_at) "
                         "VALUES(?,?,?,?,?,?)", (ref, chat_id, kind, "sending", text_hash, utcnow()))
            return True
        except sqlite3.IntegrityError:
            return False

    def finish_publication(self, ref: str, chat_id: int, kind: str, status: str, message_id: int | None = None,
                           error: str | None = None) -> None:
        self.execute("UPDATE publications SET status=?, message_id=?, error=?, sent_at=? WHERE ref=? AND chat_id=? "
                     "AND kind=?", (status, message_id, error, utcnow(), ref, chat_id, kind))

    # ------------------------------------------------------------------ jadval vazifalari
    def job(self, key: str) -> dict | None:
        return self.one("SELECT * FROM jobs WHERE job_key=?", (key,))

    def ensure_job(self, key: str, kind: str, scheduled_at: str) -> dict:
        self.execute("INSERT OR IGNORE INTO jobs(job_key, kind, scheduled_at, status, attempts) VALUES(?,?,?,?,0)",
                     (key, kind, scheduled_at, "pending"))
        return self.job(key)

    def update_job(self, key: str, **fields: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE jobs SET {sets} WHERE job_key=?", list(fields.values()) + [key])

    def warn(self, symbol: str, timeframe: str, kind: str, detail: str) -> None:
        self.execute("INSERT INTO data_warnings(ts, symbol, timeframe, kind, detail) VALUES(?,?,?,?,?)",
                     (utcnow(), symbol, timeframe, kind, detail[:500]))
