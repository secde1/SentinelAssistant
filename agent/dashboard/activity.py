"""Faoliyat tarixi va hisobotlar: agent jurnali (jurnal/YYYY-MM-DD.jsonl) va suhbat tarixi (ish/suhbat.jsonl).

Faqat o'qiladi. Jurnal yozilayotganda redaction'dan o'tgan; bu yerda ham chiqishdan oldin yana Redactor ishlaydi
(server qatlamida). Telegram Business yozuvlari ("business", "stale") ko'rsatilmaydi — ular shovqin va begona
suhbatlarga oid.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HIDDEN = {"business", "stale"}
_TASK_TYPES = {"task_start", "task", "task_error", "task_cancelled", "claude_session", "panel_task"}
_ERROR_EVENTS = {"agent_crash", "agent_config_error", "agent_crash_loop", "zabbix_error", "quota", "unauthorized"}
MAX_DAYS = 92


def available_days(jurnal: Path) -> list[str]:
    return sorted((p.stem for p in jurnal.glob("*.jsonl") if _DAY_RE.match(p.stem)), reverse=True)


def parse_range(start: str | None, end: str | None, default_days: int = 7) -> tuple[date, date]:
    today = date.today()
    try:
        e = date.fromisoformat(end) if end else today
    except ValueError:
        e = today
    try:
        s = date.fromisoformat(start) if start else e - timedelta(days=default_days - 1)
    except ValueError:
        s = e - timedelta(days=default_days - 1)
    if s > e:
        s, e = e, s
    if (e - s).days >= MAX_DAYS:
        s = e - timedelta(days=MAX_DAYS - 1)
    return s, e


def load_records(jurnal: Path, start: date, end: date) -> list[dict]:
    out: list[dict] = []
    day = start
    while day <= end:
        path = jurnal / f"{day.isoformat()}.jsonl"
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("type") not in _HIDDEN:
                    out.append(rec)
        day += timedelta(days=1)
    return out


def chat_replies(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("task"):
            out[str(rec["task"])] = rec
    return out


def _short(text: object, limit: int) -> str:
    s = str(text or "").strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def build_tasks(records: list[dict], replies: dict[str, dict]) -> list[dict]:
    tasks: dict[str, dict] = {}

    def get(tid: str, ts: str) -> dict:
        return tasks.setdefault(tid, {
            "id": tid, "ts": ts, "finished": None, "description": None, "model": None, "origin": "telegram",
            "status": "running", "steps": 0, "actions": 0, "failed_actions": 0, "devices": [], "mutated": None,
            "verified": None, "result": None, "error": None, "failures": []})

    for r in records:
        tid = str(r.get("task") or "")
        if not tid:
            continue
        t = r.get("type")
        ts = str(r.get("ts") or "")
        if t not in _TASK_TYPES and t != "action":
            continue
        task = get(tid, ts)
        if ts and ts < task["ts"]:
            task["ts"] = ts
        if t == "task_start":
            task["description"] = _short(r.get("text"), 2000)
            task["model"] = r.get("model")
            if r.get("auto"):
                task["origin"] = "automatic"
        elif t == "panel_task":
            task["origin"] = "desktop panel"
        elif t == "task":
            task["status"] = r.get("status") or "unknown"
            task["steps"] = r.get("steps") or task["steps"]
            task["mutated"] = r.get("mutated")
            task["verified"] = r.get("verified")
            task["finished"] = ts
        elif t == "task_error":
            task["status"] = "error"
            task["error"] = _short(r.get("error"), 1000)
            task["finished"] = ts
        elif t == "task_cancelled":
            task["status"] = "cancelled"
            task["error"] = "Stopped by owner (/stop)"
            task["finished"] = ts
        elif t == "action":
            task["actions"] += 1
            host = str(r.get("host") or "").strip()
            if host and host not in task["devices"]:
                task["devices"].append(host)
            if not r.get("success"):
                task["failed_actions"] += 1
                if len(task["failures"]) < 5:
                    task["failures"].append({"ts": ts, "tool": r.get("tool"), "host": host,
                                             "result": _short(r.get("result"), 400)})
    stale_before = (datetime.now() - timedelta(hours=3)).isoformat(timespec="seconds")
    for tid, task in tasks.items():
        if tid.startswith("CLI-"):
            task["origin"] = "console"
        if task["status"] == "running" and task["ts"] < stale_before:
            # Yakun yozuvi yo'q va TASK_TIMEOUT (2 soat) o'tib ketgan — agent o'sha paytda to'xtagan bo'lishi mumkin.
            task["status"] = "incomplete"
            task["error"] = task["error"] or "No completion record in the journal (agent may have stopped mid-task)"
        reply = replies.get(tid)
        if reply:
            task["result"] = _short(reply.get("reply"), 1500)
            if not task["description"]:
                task["description"] = _short(reply.get("user"), 2000)
        if task["status"] in ("error", "quota", "limit", "refusal") and not task["error"] and task["result"]:
            task["error"] = _short(task["result"], 600)
    return sorted(tasks.values(), key=lambda x: x["ts"], reverse=True)


def build_actions(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        if r.get("type") != "action":
            continue
        params = r.get("params") if isinstance(r.get("params"), dict) else {}
        detail = params.get("command") or params.get("script") or params.get("path") or params.get("url") or ""
        out.append({"ts": r.get("ts"), "task": r.get("task"), "host": r.get("host"), "tool": r.get("tool"),
                    "level": r.get("level"), "success": bool(r.get("success")), "duration_ms": r.get("duration_ms"),
                    "detail": _short(detail, 600), "result": _short(r.get("result"), 1200)})
    return sorted(out, key=lambda x: str(x["ts"]), reverse=True)


def build_events(records: list[dict]) -> list[dict]:
    out = []
    for r in records:
        t = r.get("type")
        if t in _TASK_TYPES or t == "action":
            continue
        fields = {k: v for k, v in r.items() if k not in ("ts", "type", "traceback")}
        summary = r.get("error") or r.get("sarlavha") or r.get("reason") or r.get("text") or ""
        out.append({"ts": r.get("ts"), "type": t, "error": t in _ERROR_EVENTS or bool(r.get("error")),
                    "summary": _short(summary, 400), "fields": {k: _short(v, 300) for k, v in fields.items()}})
    return sorted(out, key=lambda x: str(x["ts"]), reverse=True)


def report(records: list[dict], replies: dict[str, dict], start: date, end: date) -> dict:
    tasks = build_tasks(records, replies)
    actions = [r for r in records if r.get("type") == "action"]
    per_day: dict[str, Counter] = defaultdict(Counter)
    day = start
    while day <= end:
        per_day[day.isoformat()]  # bo'sh kunlar ham grafikda ko'rinsin
        day += timedelta(days=1)
    for t in tasks:
        per_day[t["ts"][:10]][_bucket(t["status"])] += 1
    status = Counter(t["status"] for t in tasks)
    hosts = Counter(str(a.get("host") or "—") for a in actions)
    tools = Counter(str(a.get("tool") or "—") for a in actions)
    failed_tools = Counter(str(a.get("tool") or "—") for a in actions if not a.get("success"))
    durations = [a["duration_ms"] for a in actions if isinstance(a.get("duration_ms"), (int, float))]
    finished = sum(v for k, v in status.items() if k != "running")
    ok = status.get("ok", 0)
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "tasks_total": len(tasks),
        "tasks_ok": ok,
        "tasks_failed": finished - ok,
        "success_rate": round(ok / finished * 100, 1) if finished else None,
        "changes_made": sum(1 for t in tasks if t["mutated"]),
        "changes_verified": sum(1 for t in tasks if t["mutated"] and t["verified"]),
        "actions_total": len(actions),
        "actions_failed": sum(1 for a in actions if not a.get("success")),
        "avg_action_ms": round(sum(durations) / len(durations)) if durations else None,
        "status": dict(status),
        "per_day": [{"day": d, "ok": c.get("ok", 0), "failed": c.get("failed", 0), "running": c.get("running", 0)}
                    for d, c in sorted(per_day.items())],
        "top_devices": [{"name": k, "count": v} for k, v in hosts.most_common(10)],
        "top_tools": [{"name": k, "count": v, "failed": failed_tools.get(k, 0)} for k, v in tools.most_common(10)],
        "quota_events": sum(1 for r in records if r.get("type") in ("quota", "quota_warning")),
        "agent_restarts": sum(1 for r in records if r.get("type") == "agent_start"),
        "agent_crashes": sum(1 for r in records if r.get("type") in ("agent_crash", "agent_crash_loop")),
    }


def _bucket(status: str) -> str:
    if status == "ok":
        return "ok"
    return "running" if status == "running" else "failed"


def today_summary(jurnal: Path, replies: dict[str, dict], now: datetime | None = None) -> dict:
    day = (now or datetime.now()).date()
    records = load_records(jurnal, day, day)
    tasks = build_tasks(records, replies)
    return {"tasks": len(tasks), "ok": sum(1 for t in tasks if t["status"] == "ok"),
            "failed": sum(1 for t in tasks if t["status"] not in ("ok", "running")),
            "running": sum(1 for t in tasks if t["status"] == "running"),
            "actions": sum(1 for r in records if r.get("type") == "action"),
            "recent": tasks[:8]}
