"""Jurnal: har amal ikki joyga — jurnal/YYYY-MM-DD.md (o'qishga qulay) va .jsonl (struktura).

Yozishdan oldin hamma narsa Redactor orqali o'tadi.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from .redact import Redactor

_MD_HEADER = "# Jurnal {date}\n\n| Vaqt | Host | Nima qildim | Natija |\n|---|---|---|---|\n"


def _one_line(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    s = s.replace("|", "\\|")
    return s if len(s) <= limit else s[: limit - 1] + "…"


class Journal:
    def __init__(self, jurnal_dir: Path, redactor: Redactor):
        self.dir = Path(jurnal_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.redactor = redactor
        self._lock = threading.Lock()

    def _paths(self, now: datetime) -> tuple[Path, Path]:
        day = now.strftime("%Y-%m-%d")
        return self.dir / f"{day}.md", self.dir / f"{day}.jsonl"

    def _write(self, now: datetime, md_row: str | None, record: dict) -> None:
        md, jl = self._paths(now)
        with self._lock:
            if md_row is not None:
                if not md.exists():
                    md.write_text(_MD_HEADER.format(date=now.strftime("%Y-%m-%d")), encoding="utf-8")
                with md.open("a", encoding="utf-8") as f:
                    f.write(md_row)
            with jl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def action(self, *, task_id: str, host: str, tool: str, summary: str, params: dict, result: str,
               success: bool, level: str, duration_ms: int | None = None, extra: dict | None = None) -> None:
        now = datetime.now()
        r = self.redactor
        result_red = r.redact(result or "")
        record = {
            "ts": now.isoformat(timespec="seconds"),
            "type": "action",
            "task": task_id,
            "host": host,
            "tool": tool,
            "level": level,
            "params": r.redact_obj(params),
            "result": result_red[:2000],
            "success": success,
            "duration_ms": duration_ms,
        }
        if extra:
            record.update(r.redact_obj(extra))
        mark = "✓" if success else "✗"
        row = (f"| {now.strftime('%H:%M:%S')} | {_one_line(host, 40)} | {_one_line(tool + ': ' + r.redact(summary), 160)} "
               f"| {mark} {_one_line(result_red, 120)} |\n")
        self._write(now, row, record)

    def event(self, type_: str, md_text: str | None = None, **fields: Any) -> None:
        now = datetime.now()
        record = {"ts": now.isoformat(timespec="seconds"), "type": type_}
        record.update(self.redactor.redact_obj(fields))
        row = None
        if md_text is not None:
            row = f"| {now.strftime('%H:%M:%S')} | — | {_one_line(self.redactor.redact(md_text), 200)} | |\n"
        self._write(now, row, record)

    def read_records(self, day: str) -> list[dict]:
        path = self.dir / f"{day}.jsonl"
        out: list[dict] = []
        if not path.exists():
            return out
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out
