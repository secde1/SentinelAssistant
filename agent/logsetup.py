"""Python logging: jurnal/agent.log (aylanma) + konsol. Har yozuv Redactor orqali o'tadi."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .redact import Redactor


class RedactFilter(logging.Filter):
    def __init__(self, redactor: Redactor):
        super().__init__()
        self.redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = self.redactor.redact(record.getMessage())
            record.args = None
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = self.redactor.redact(record.exc_text)
        except Exception:  # noqa: BLE001
            pass
        return True


def setup_logging(jurnal_dir: Path, redactor: Redactor, level: int = logging.INFO) -> None:
    jurnal_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    flt = RedactFilter(redactor)
    file_h = logging.handlers.RotatingFileHandler(jurnal_dir / "agent.log", maxBytes=5_000_000, backupCount=5,
                                                  encoding="utf-8")
    console_h = logging.StreamHandler(sys.stdout)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    for h in (file_h, console_h):
        h.setFormatter(fmt)
        h.addFilter(flt)
        root.addHandler(h)
    # httpx INFO darajasida URL (Telegram tokeni bilan) yozadi — o'chiramiz.
    for noisy in ("httpx", "httpcore", "httpx2", "paramiko", "netmiko", "urllib3", "claude_agent_sdk", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
