"""Dashboard uchun Trading Research ma'lumoti — bazani FAQAT O'QISH rejimida ochadi (sqlite mode=ro).

Hech qanday boshqaruv yo'q: tahlil yaratish, nashr, strategiya faollashtirish, broker — dashboarddan mumkin emas.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from ..trading import analytics


class _RO:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        self.conn.row_factory = sqlite3.Row

    def query(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params=()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        self.conn.close()


def _j(value):
    if isinstance(value, str) and value[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class TradingView:
    def __init__(self, home: Path):
        self.root = Path(home) / "trading_memory"
        self.db_path = self.root / "database" / "trading_research.db"

    def _db(self) -> _RO | None:
        return _RO(self.db_path) if self.db_path.is_file() else None

    def _settings(self) -> dict:
        try:
            return json.loads((self.root / "config" / "research_settings.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def overview(self) -> dict:
        st = self._settings()
        base = {"enabled": os.environ.get("TRADING_ENABLED", "0").strip() in ("1", "true", "yes", "on"),
                "group_configured": bool(st.get("group_chat_id") or os.environ.get("TRADING_GROUP_CHAT_ID")),
                "group_title": st.get("group_title"), "timezone": st.get("timezone"),
                "daily_target": st.get("daily_target"), "slots": st.get("analysis_slots"),
                "twelvedata": bool(os.environ.get("TWELVEDATA_API_KEY")), "exists": self.db_path.is_file()}
        db = self._db()
        if db is None:
            return {**base, "summary": None, "equity": [], "by_strategy": [], "recent": [], "jobs": [], "warnings": [],
                    "per_day": []}
        try:
            perf = analytics.performance(db)
            recent = db.query("SELECT a.analysis_id, a.created_at, a.local_date, a.symbol, a.timeframe, a.session, a.kind, "
                              "a.strategy_id, a.strategy_version, a.direction, a.entry, a.sl, a.tp, a.rr, o.status, "
                              "o.r_multiple FROM analyses a LEFT JOIN outcomes o ON o.analysis_id=a.analysis_id "
                              "ORDER BY a.created_at DESC LIMIT 40")
            since = (date.today() - timedelta(days=13)).isoformat()
            per_day = db.query("SELECT local_date AS day, SUM(kind='TRADE') AS trade, SUM(kind='NO_TRADE') AS no_trade "
                               "FROM analyses WHERE local_date >= ? GROUP BY local_date ORDER BY local_date", (since,))
            jobs = db.query("SELECT job_key, kind, scheduled_at, status, attempts, last_error FROM jobs "
                            "ORDER BY scheduled_at DESC LIMIT 30")
            warnings = db.query("SELECT ts, symbol, timeframe, kind, detail FROM data_warnings ORDER BY id DESC LIMIT 20")
            return {**base, "summary": perf["summary"], "limitations": perf["limitations"],
                    "by_strategy": perf["by_strategy"], "by_instrument": perf["by_instrument"],
                    "by_session": perf["by_session"], "by_timeframe": perf["by_timeframe"],
                    "equity": analytics.equity_curve(db), "recent": recent, "per_day": per_day, "jobs": jobs,
                    "warnings": warnings}
        finally:
            db.close()

    def analysis(self, analysis_id: str) -> dict | None:
        db = self._db()
        if db is None:
            return None
        try:
            row = db.one("SELECT payload, content_hash FROM analyses WHERE analysis_id=?", (analysis_id,))
            if row is None:
                return None
            return {"analysis": json.loads(row["payload"]), "content_hash": row["content_hash"],
                    "outcome": db.one("SELECT * FROM outcomes WHERE analysis_id=?", (analysis_id,)),
                    "events": db.query("SELECT market_ts, recorded_at, from_status, to_status, price, detail FROM "
                                       "outcome_events WHERE analysis_id=? ORDER BY id", (analysis_id,)),
                    "publications": db.query("SELECT chat_id, kind, status, message_id, sent_at, error FROM publications "
                                             "WHERE ref=?", (analysis_id,)),
                    "review": {k: _j(v) for k, v in (db.one("SELECT * FROM sl_reviews WHERE analysis_id=?",
                                                            (analysis_id,)) or {}).items()} or None}
        finally:
            db.close()

    def table(self, name: str) -> list[dict]:
        sql = {
            "outcomes": "SELECT a.analysis_id, a.created_at, a.symbol, a.timeframe, a.session, a.strategy_id, "
                        "a.strategy_version, a.direction, a.entry, a.sl, a.tp, o.status, o.entry_time, o.exit_time, "
                        "o.exit_price, o.r_multiple, o.cost_r FROM analyses a JOIN outcomes o ON o.analysis_id=a.analysis_id "
                        "ORDER BY a.created_at DESC LIMIT 300",
            "strategies": "SELECT s.*, (SELECT json_group_array(json_object('symbol', t.symbol, 'timeframe', t.timeframe, "
                          "'period_start', t.period_start, 'period_end', t.period_end, 'sample_size', t.sample_size, "
                          "'win_rate', t.win_rate, 'avg_rr', t.avg_rr, 'expectancy', t.expectancy, 'max_dd', t.max_dd, "
                          "'created_at', t.created_at)) FROM strategy_stats t WHERE t.strategy_id=s.strategy_id AND "
                          "t.version=s.version) AS stats FROM strategies s ORDER BY s.strategy_id, s.version",
            "reviews": "SELECT r.*, a.symbol, a.timeframe FROM sl_reviews r JOIN analyses a ON a.analysis_id=r.analysis_id "
                       "ORDER BY r.created_at DESC LIMIT 200",
            "sources": "SELECT * FROM research_sources ORDER BY retrieved_at DESC LIMIT 300",
            "experiments": "SELECT * FROM experiments ORDER BY created_at DESC LIMIT 100",
            "reports": "SELECT report_id, kind, period_start, period_end, created_at, text FROM reports "
                       "ORDER BY period_end DESC, kind LIMIT 60",
        }.get(name)
        if sql is None:
            raise KeyError(name)
        db = self._db()
        if db is None:
            return []
        try:
            return [{k: _j(v) for k, v in r.items()} for r in db.query(sql)]
        finally:
            db.close()
