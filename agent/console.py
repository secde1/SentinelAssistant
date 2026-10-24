"""Konsol kanali: `python -m agent --once "..."` — Telegramsiz sinash uchun."""
from __future__ import annotations

import asyncio
import getpass
from pathlib import Path

from .redact import Redactor


class ConsoleChannel:
    def __init__(self, redactor: Redactor):
        self.redactor = redactor

    async def send(self, text: str) -> None:
        print(f"\n[agent] {self.redactor.redact(text)}\n", flush=True)

    async def send_file(self, path: Path, caption: str = "") -> None:
        print(f"\n[agent fayl] {path} — {self.redactor.redact(caption)}\n", flush=True)

    async def request_approval(self, text: str) -> bool:
        print("\n" + self.redactor.redact(text), flush=True)
        answer = await asyncio.to_thread(input, "Tasdiqlaysizmi? (ha/yo'q): ")
        return answer.strip().lower() in {"ha", "xa", "yes", "y"}

    async def ask(self, question: str) -> str | None:
        answer = await asyncio.to_thread(input, f"\n[savol] {question}\n> ")
        return answer.strip() or None

    async def request_secret(self, prompt: str) -> str | None:
        print("\n" + prompt + "\n(Har maydonni 'kalit: qiymat' ko'rinishida kiriting; bo'sh qator — tugatish.)", flush=True)
        lines = []
        while True:
            line = await asyncio.to_thread(getpass.getpass, "> ")
            if not line.strip():
                break
            lines.append(line)
        return "\n".join(lines) or None
