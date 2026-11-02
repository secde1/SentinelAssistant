"""Reels holati va tarixi (SQLite): holatlar mashinasi, versiyalar, auditli o'tishlar, tasdiq.

Tasdiq aynan bitta versiyaga va uning sha256 iga bog'lanadi: video o'zgarsa (yangi versiya) — qayta tasdiq kerak.
Joylash (2-bosqich) faqat APPROVED holatdagi va sha256 mos keladigan versiyani ishlatishi shart.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from datetime import datetime
from pathlib import Path

# Holatlar mashinasi: holat -> ruxsat etilgan keyingi holatlar (kalitlar — barcha holatlar ro'yxati).
TRANSITIONS = {
    "IDEA": {"RESEARCHING", "SCRIPT_READY", "REJECTED", "FAILED"},
    "RESEARCHING": {"SCRIPT_READY", "REJECTED", "FAILED"},
    "SCRIPT_READY": {"VIDEO_RENDERING", "FAILED"},
    "VIDEO_RENDERING": {"QUALITY_CHECK", "FAILED"},
    "QUALITY_CHECK": {"PENDING_APPROVAL", "FAILED"},
    "PENDING_APPROVAL": {"APPROVED", "REVISION_REQUESTED", "REJECTED"},
    "REVISION_REQUESTED": {"SCRIPT_READY", "REJECTED"},
    "APPROVED": {"SCHEDULED", "PUBLISHING", "REVISION_REQUESTED", "REJECTED"},
    "SCHEDULED": {"PUBLISHING", "APPROVED", "REVISION_REQUESTED", "REJECTED"},
    "PUBLISHING": {"PUBLISHED", "FAILED"},
    "FAILED": {"SCRIPT_READY", "REJECTED"},
    "PUBLISHED": set(),
    "REJECTED": set(),
}
STATE_LABELS = {
    "SCRIPT_READY": "skript tayyor", "VIDEO_RENDERING": "video yasalmoqda", "QUALITY_CHECK": "sifat nazorati",
    "PENDING_APPROVAL": "tasdiq kutmoqda", "APPROVED": "tasdiqlangan", "SCHEDULED": "rejalashtirilgan",
    "PUBLISHING": "joylanmoqda", "PUBLISHED": "joylangan", "REVISION_REQUESTED": "qayta ishlash so'ralgan",
    "REJECTED": "rad etilgan", "FAILED": "xato", "IDEA": "g'oya", "RESEARCHING": "tadqiqot",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id TEXT PRIMARY KEY, created TEXT, updated TEXT, state TEXT, topic TEXT, category TEXT, title TEXT,
    version INTEGER DEFAULT 0, approved_version INTEGER, approved_sha256 TEXT, scheduled_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS versions (
    reel_id TEXT, version INTEGER, created TEXT, script_json TEXT, video_path TEXT, sha256 TEXT,
    duration REAL, tts_engine TEXT, PRIMARY KEY (reel_id, version));
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, reel_id TEXT, ts TEXT, version INTEGER, from_state TEXT,
    to_state TEXT, actor TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


class TransitionError(Exception):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class StudioStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "reels.db"
        self._lock = threading.RLock()
        with self._conn() as c:
            c.executescript(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _exec(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock, closing(self._conn()) as c, c:
            return list(c.execute(sql, args))

    # --- reels ------------------------------------------------------------
    def new_id(self, now: datetime | None = None) -> str:
        prefix = f"R{(now or datetime.now()):%m%d}-"
        rows = self._exec("SELECT id FROM reels WHERE id LIKE ?", (prefix + "%",))
        nums = [int(r["id"][len(prefix):]) for r in rows if r["id"][len(prefix):].isdigit()]
        return f"{prefix}{max(nums, default=0) + 1:02d}"

    def create(self, topic: str, category: str, title: str) -> str:
        rid = self.new_id()
        now = _now()
        self._exec("INSERT INTO reels (id, created, updated, state, topic, category, title) VALUES (?,?,?,?,?,?,?)",
                   (rid, now, now, "IDEA", topic, category, title))
        self._event(rid, 0, None, "IDEA", "agent", "yaratildi")
        return rid

    def get(self, rid: str) -> dict | None:
        rows = self._exec("SELECT * FROM reels WHERE id = ?", (rid,))
        return dict(rows[0]) if rows else None

    def recent(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM reels ORDER BY created DESC LIMIT ?", (limit,))]

    def count_today(self, day: str | None = None) -> int:
        """Bugun tayyorlangan (rad etilmagan, xato bo'lmagan) reels soni."""
        day = day or datetime.now().strftime("%Y-%m-%d")
        rows = self._exec("SELECT COUNT(*) AS n FROM reels WHERE created LIKE ? AND state NOT IN ('REJECTED','FAILED')",
                          (day + "%",))
        return int(rows[0]["n"])

    # --- holat ------------------------------------------------------------
    def transition(self, rid: str, to_state: str, actor: str, note: str = "") -> None:
        reel = self.get(rid)
        if reel is None:
            raise TransitionError(f"{rid} topilmadi")
        if to_state not in TRANSITIONS.get(reel["state"], set()):
            raise TransitionError(f"{rid}: {reel['state']} -> {to_state} o'tishi mumkin emas")
        self._exec("UPDATE reels SET state = ?, updated = ? WHERE id = ?", (to_state, _now(), rid))
        self._event(rid, reel["version"], reel["state"], to_state, actor, note)

    def _event(self, rid: str, version: int, from_state: str | None, to_state: str, actor: str, note: str) -> None:
        self._exec("INSERT INTO events (reel_id, ts, version, from_state, to_state, actor, note) VALUES (?,?,?,?,?,?,?)",
                   (rid, _now(), version, from_state, to_state, actor, note))

    def events(self, rid: str) -> list[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM events WHERE reel_id = ? ORDER BY id", (rid,))]

    # --- versiyalar -------------------------------------------------------
    def start_version(self, rid: str, script: dict) -> int:
        reel = self.get(rid)
        version = int(reel["version"]) + 1
        self._exec("INSERT INTO versions (reel_id, version, created, script_json) VALUES (?,?,?,?)",
                   (rid, version, _now(), json.dumps(script, ensure_ascii=False)))
        self._exec("UPDATE reels SET version = ?, topic = ?, category = ?, title = ?, updated = ? WHERE id = ?",
                   (version, script.get("topic", ""), script.get("category", ""), script.get("title", ""), _now(), rid))
        return version

    def finish_version(self, rid: str, version: int, video: Path, duration: float, tts_engine: str) -> str:
        digest = sha256_file(video)
        self._exec("UPDATE versions SET video_path = ?, sha256 = ?, duration = ?, tts_engine = ? "
                   "WHERE reel_id = ? AND version = ?", (str(video), digest, duration, tts_engine, rid, version))
        return digest

    def version(self, rid: str, version: int | None = None) -> dict | None:
        reel = self.get(rid)
        if reel is None:
            return None
        rows = self._exec("SELECT * FROM versions WHERE reel_id = ? AND version = ?", (rid, version or reel["version"]))
        if not rows:
            return None
        row = dict(rows[0])
        row["script"] = json.loads(row.pop("script_json") or "{}")
        return row

    # --- egasi qarorlari ----------------------------------------------------
    def approve(self, rid: str, version: int) -> str:
        """Faqat joriy versiya va uning fayli o'zgarmagan bo'lsa. -> tasdiqlangan sha256."""
        reel = self.get(rid)
        if reel is None or reel["version"] != version:
            raise TransitionError(f"{rid}: v{version} eskirgan — joriy versiya v{reel['version'] if reel else '?'}")
        ver = self.version(rid, version)
        if not ver or not ver.get("video_path") or not Path(ver["video_path"]).exists():
            raise TransitionError(f"{rid}: video fayli topilmadi")
        actual = sha256_file(Path(ver["video_path"]))
        if actual != ver["sha256"]:
            raise TransitionError(f"{rid}: video fayli tasdiqqa yuborilgandan keyin o'zgargan — qayta tasdiq kerak")
        self.transition(rid, "APPROVED", "egasi", f"v{version} sha256={actual[:16]}")
        self._exec("UPDATE reels SET approved_version = ?, approved_sha256 = ? WHERE id = ?", (version, actual, rid))
        return actual

    def set_schedule(self, rid: str, when: datetime) -> None:
        self._exec("UPDATE reels SET scheduled_at = ?, updated = ? WHERE id = ?",
                   (when.isoformat(timespec="minutes"), _now(), rid))
        reel = self.get(rid)
        self._event(rid, reel["version"], reel["state"], reel["state"], "egasi", f"vaqt: {when:%Y-%m-%d %H:%M}")

    def set_note(self, rid: str, note: str) -> None:
        self._exec("UPDATE reels SET note = ?, updated = ? WHERE id = ?", (note, _now(), rid))

    # --- sozlamalar (pauza) -------------------------------------------------
    def setting(self, key: str, default: str = "") -> str:
        rows = self._exec("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else default

    def set_setting(self, key: str, value: str) -> None:
        self._exec("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                   (key, value))
