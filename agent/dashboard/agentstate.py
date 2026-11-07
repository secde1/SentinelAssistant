"""Telegram agentining holati — faqat o'qish: ish/agent.state va ustki panel serverining GET /api/state.

Dashboard agentga hech narsa yubormaydi (topshiriq, tasdiq, stop — yo'q). Agentni boshqarish Telegram va
agentctl.cmd da qoladi.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ALIVE_WINDOW_SEC = 180  # agent har 60 s da "tirik" belgisini yangilaydi


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def agent_status(ish: Path, timeout: float = 2.0) -> dict:
    state = _read_json(ish / "agent.state")
    stop = _read_json(ish / "agent.stop")
    out = {"running": False, "pid": state.get("pid"), "version": state.get("version"), "started": state.get("started"),
           "last_alive": state.get("last_alive"), "stopped_by_owner": bool(stop) and not stop.get("allow"),
           "control": None, "control_error": None}
    try:
        age = (datetime.now() - datetime.fromisoformat(str(state.get("last_alive")))).total_seconds()
        out["running"] = not state.get("clean") and age < ALIVE_WINDOW_SEC
    except (TypeError, ValueError):
        pass
    ctl = _read_json(ish / "control.json")
    if ctl.get("port") and ctl.get("token"):
        req = urllib.request.Request(f"http://127.0.0.1:{int(ctl['port'])}/api/state",
                                     headers={"X-Token": str(ctl["token"])}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — faqat 127.0.0.1
                data = json.loads(resp.read().decode("utf-8"))
            out["running"] = True
            out["control"] = {
                "model": data.get("model"), "plan": data.get("plan"), "limits": data.get("limits"),
                "blocked": data.get("blocked"), "busy": data.get("busy"),
                "tasks": [{"id": t.get("id"), "elapsed": t.get("elapsed"), "steps": t.get("steps"),
                           "last": t.get("last"), "text": t.get("text")} for t in data.get("tasks") or []],
                "pending": [{"id": p.get("id"), "label": p.get("label"), "task_id": p.get("task_id")}
                            for p in data.get("pending") or []],
            }
        except (urllib.error.URLError, OSError, ValueError) as exc:
            out["control_error"] = type(exc).__name__
    return out
