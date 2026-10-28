"""Jamshiddan kutilayotgan javoblar: tasdiq (approval), savol (question), maxfiy ma'lumot (credential).

Har biri bir martalik: hal qilingach o'chiriladi — "ha" faqat o'sha amalga tegishli.
"""
from __future__ import annotations

import asyncio
import itertools
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Pending:
    id: str
    kind: str  # approval | question | credential
    task_id: str
    future: asyncio.Future
    message_id: int | None = None
    text: str = ""  # so'rov matni (ustki panelda ko'rsatish uchun)
    created: float = field(default_factory=time.monotonic)


class PendingInputs:
    def __init__(self) -> None:
        self._items: dict[str, Pending] = {}
        self._ids = itertools.count(1)

    def create(self, kind: str, task_id: str) -> Pending:
        pid = f"{kind[0]}{next(self._ids)}"
        p = Pending(pid, kind, task_id, asyncio.get_running_loop().create_future())
        self._items[pid] = p
        return p

    def get(self, pid: str) -> Pending | None:
        return self._items.get(pid)

    def resolve(self, pid: str, value: Any) -> bool:
        p = self._items.pop(pid, None)
        if p is None or p.future.done():
            return False
        p.future.set_result(value)
        return True

    def discard(self, pid: str) -> None:
        self._items.pop(pid, None)

    def by_kind(self, kind: str) -> list[Pending]:
        return sorted((p for p in self._items.values() if p.kind == kind), key=lambda p: p.created)

    def by_message(self, message_id: int | None) -> Pending | None:
        if message_id is None:
            return None
        return next((p for p in self._items.values() if p.message_id == message_id), None)

    def cancel_task(self, task_id: str) -> None:
        for p in [p for p in self._items.values() if p.task_id == task_id]:
            self.resolve(p.id, None)

    def all(self) -> list[Pending]:
        return sorted(self._items.values(), key=lambda p: p.created)

    async def wait(self, p: Pending, timeout: float) -> Any:
        """Javobni kutadi; timeout -> None (va so'rov bekor qilinadi)."""
        try:
            return await asyncio.wait_for(asyncio.shield(p.future), timeout)
        except asyncio.TimeoutError:
            self.discard(p.id)
            return None
        finally:
            if not p.future.done():
                self.discard(p.id)
