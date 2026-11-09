"""Chiqish papkasi (V27): `data\\chiqish\\` ga tashlangan fayl egasining SHAXSIY Telegram chatiga yuboriladi, so'ng
`yuborildi\\` papkasiga ko'chiriladi. Agent hisobot fayllarini (Word/Excel/PDF) egasiga yetkazishning oddiy yo'li.

Chegaralar: faqat shu papkaning o'zidagi (ichki papkalarsiz) fayllar; ruxsat etilgan kengaytmalar; hajmi <= 20 MB; nuqta bilan
boshlanadigan va yozilayotgan (so'nggi 5 soniyada o'zgargan) fayllar o'tkazib yuboriladi. Faqat egasining chatiga yuboriladi.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

ALLOWED = {".docx", ".xlsx", ".pdf", ".csv", ".txt", ".png", ".jpg", ".jpeg"}
MAX_BYTES = 20 * 1024 * 1024
SETTLE_SEC = 5  # fayl yozib bo'lingandan keyin shuncha kutiladi
MAX_ATTEMPTS = 5


class Outbox:
    def __init__(self, root: Path, send_file: Callable[[Path, str], Awaitable[bool]],
                 notify: Callable[[str], Awaitable] | None = None, now=time.time):
        self.root = Path(root)
        self.sent_dir = self.root / "yuborildi"
        self.root.mkdir(parents=True, exist_ok=True)
        self.send_file, self.notify, self.now = send_file, notify, now
        self.attempts: dict[str, int] = {}

    def candidates(self) -> list[Path]:
        out = []
        for p in sorted(self.root.iterdir()):
            if not p.is_file() or p.name.startswith(".") or p.suffix.lower() not in ALLOWED:
                continue
            st = p.stat()
            if st.st_size == 0 or st.st_size > MAX_BYTES or self.now() - st.st_mtime < SETTLE_SEC:
                continue
            out.append(p)
        return out

    async def tick(self) -> list[str]:
        done = []
        for p in self.candidates():
            ok = False
            try:
                ok = await self.send_file(p, f"📎 {p.name}")
            except Exception:  # noqa: BLE001
                log.exception("chiqish fayli yuborilmadi: %s", p.name)
            if ok:
                self.sent_dir.mkdir(exist_ok=True)
                dest = self.sent_dir / p.name
                if dest.exists():
                    dest = self.sent_dir / f"{int(self.now())}_{p.name}"
                shutil.move(str(p), str(dest))
                self.attempts.pop(p.name, None)
                done.append(p.name)
                continue
            n = self.attempts.get(p.name, 0) + 1
            self.attempts[p.name] = n
            if n == MAX_ATTEMPTS and self.notify:
                await self.notify(f"⚠️ {p.name} faylini {n} urinishda ham yuborib bo'lmadi. Fayl {self.root} da turibdi.")
        return done


async def run_forever(box: Outbox, interval: int = 30) -> None:
    while True:
        try:
            await box.tick()
        except Exception:  # noqa: BLE001
            log.exception("chiqish papkasi")
        await asyncio.sleep(interval)
