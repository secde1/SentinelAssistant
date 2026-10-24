"""Agent bilan Jamshid o'rtasidagi kanal (Telegram yoki konsol) interfeysi."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class OwnerChannel(Protocol):
    async def send(self, text: str) -> None: ...

    async def send_file(self, path: Path, caption: str = "") -> None: ...

    async def request_approval(self, text: str) -> bool:
        """True faqat aniq "ha" kelganda. Yo'q / noaniq / timeout -> False."""
        ...

    async def ask(self, question: str) -> str | None:
        """Bitta savol; javob matni yoki None (timeout)."""
        ...

    async def request_secret(self, prompt: str) -> str | None:
        """Maxfiy ma'lumot so'rash. Javob modelga BERILMAYDI — faqat inventarga yoziladi."""
        ...
