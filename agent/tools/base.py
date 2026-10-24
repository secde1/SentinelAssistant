"""Tool'lar uchun umumiy turlar: kontekst, natija, spetsifikatsiya."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..channel import OwnerChannel
from ..config import ENV_FILE, PROJECT_ROOT, Config
from ..gate import Decision
from ..inventory import Inventory
from ..journal import Journal
from ..redact import Redactor
from ..workspace import Paths


@dataclass
class ToolResult:
    ok: bool
    output: str
    host: str | None = None
    meta: dict = field(default_factory=dict)
    verify_passed: bool | None = None


@dataclass
class ToolContext:
    task_id: str
    cfg: Config
    paths: Paths
    inventory: Inventory
    redactor: Redactor
    journal: Journal
    channel: OwnerChannel
    http_sessions: dict = field(default_factory=dict)
    auto_task: bool = False  # topshiriqni Jamshid emas, kod boshlagan (Zabbix alerti / kunlik jadval)
    backups: list[dict] = field(default_factory=list)
    mutations: list[str] = field(default_factory=list)
    verified_after_mutation: bool = True
    last_verify_ok: bool | None = None
    history_logged: bool = False
    skill_written: bool = False
    successful_calls: int = 0
    consecutive_failures: int = 0
    failed_signatures: Counter = field(default_factory=Counter)
    questions_asked: int = 0
    approvals: list[dict] = field(default_factory=list)
    steps: int = 0
    last_step: str = ""
    _out_counter: int = 0

    @property
    def work_dir(self) -> Path:
        d = self.paths.ish / self.task_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def secret_paths(self) -> list[Path]:
        return [self.paths.maxfiy, ENV_FILE]

    @property
    def code_root(self) -> Path:
        return PROJECT_ROOT

    def resolve_path(self, raw: str) -> Path:
        p = Path(str(raw).strip().strip('"').strip("'"))
        return p if p.is_absolute() else (self.paths.home / p)

    # --- zaxira kuzatuvi ---------------------------------------------------
    def host_aliases(self, host: str | None) -> set[str]:
        h = (host or "localhost").strip().lower()
        aliases = {h}
        if h in {"", ".", "localhost", "127.0.0.1"}:
            aliases |= {"localhost", ".", "127.0.0.1"}
        found = self.inventory.get(h)
        if found:
            aliases.add(found[0].lower())
            if found[1].get("host"):
                aliases.add(str(found[1]["host"]).lower())
        return aliases

    def record_backup(self, host: str, kind: str, path: Path) -> None:
        self.backups.append({"host": host, "aliases": self.host_aliases(host), "kind": kind, "path": str(path)})

    def backup_for(self, host: str) -> dict | None:
        aliases = self.host_aliases(host)
        for b in reversed(self.backups):
            if b["aliases"] & aliases:
                return b
        return None

    # --- katta natijalar ---------------------------------------------------
    def fit_output(self, text: str, tool: str) -> str:
        limit = max(2000, self.cfg.tool_output_limit)
        if len(text) <= limit:
            return text
        self._out_counter += 1
        path = self.work_dir / f"natija-{self._out_counter:03d}-{tool}.txt"
        path.write_text(text, encoding="utf-8")
        head, tail = text[: int(limit * 0.7)], text[-int(limit * 0.25):]
        return (f"{head}\n\n[... {len(text) - len(head) - len(tail)} belgi qisqartirildi ...]\n\n{tail}\n\n"
                f"[To'liq natija ({len(text)} belgi): {path} — kerak bo'lsa read_file bilan qismlab o'qing]")

    def new_file(self, name: str) -> Path:
        self._out_counter += 1
        return self.work_dir / f"{self._out_counter:03d}-{name}"


Handler = Callable[[ToolContext, dict], Awaitable[ToolResult]]
Classifier = Callable[[ToolContext, dict], Decision]


@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict
    handler: Handler
    classify: Classifier
    summary: Callable[[dict], str] = lambda a: json.dumps(a, ensure_ascii=False)[:300]
    counts_as_work: bool = True


def today_dir(root: Path) -> Path:
    d = root / datetime.now().strftime("%Y-%m-%d")
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(text: str, limit: int = 40) -> str:
    out = "".join(c if c.isalnum() or c in "-_." else "_" for c in (text or "x"))
    return out.strip("._")[:limit] or "x"


def validate_args(schema: dict, args: Any) -> str | None:
    """JSON-schema'ning kichik qismi: required, type, enum. Xato matni yoki None."""
    if not isinstance(args, dict):
        return "argumentlar obyekt (JSON) bo'lishi kerak"
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args or args[req] in (None, ""):
            return f"'{req}' majburiy maydon berilmagan"
    types = {"string": str, "integer": int, "boolean": bool, "array": list, "object": dict, "number": (int, float)}
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            return f"noma'lum maydon '{key}'. Ruxsat etilganlar: {', '.join(props)}"
        expected = types.get(spec.get("type", ""))
        if expected and value is not None:
            if spec.get("type") == "integer" and isinstance(value, bool):
                return f"'{key}' butun son bo'lishi kerak"
            if not isinstance(value, expected):
                return f"'{key}' turi {spec.get('type')} bo'lishi kerak"
        if "enum" in spec and value not in spec["enum"]:
            return f"'{key}' qiymati {spec['enum']} dan biri bo'lishi kerak"
    return None
