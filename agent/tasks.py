"""Fon vazifalar menejeri: har topshiriq alohida asyncio task'da — bot hech qachon bloklanmaydi.

1 daqiqadan uzoq ishlarda avtomatik progress xabari yuboriladi; /stop bilan to'xtatiladi; obuna limiti tugasa —
tiklanguncha yangi topshiriq qabul qilinmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable

from .channel import OwnerChannel
from .config import Config
from .journal import Journal
from .loop import AgentRunner, TaskOutcome, TaskRequest, TaskStatus, _elapsed

log = logging.getLogger(__name__)


@dataclass
class ActiveTask:
    req: TaskRequest
    status: TaskStatus
    task: asyncio.Task | None = None


class TaskManager:
    def __init__(self, runner: AgentRunner, cfg: Config, journal: Journal,
                 notify: Callable[[str], Awaitable], channel_factory: Callable[[str], OwnerChannel],
                 send_outcome: Callable[[TaskOutcome], Awaitable], on_finish: Callable[[str], None] | None = None):
        self.runner = runner
        self.cfg = cfg
        self.journal = journal
        self.notify = notify
        self.channel_factory = channel_factory
        self.send_outcome = send_outcome
        self.on_finish = on_finish
        self.active: dict[str, ActiveTask] = {}
        self.sem = asyncio.Semaphore(max(1, cfg.max_concurrent_tasks))

    def new_id(self) -> str:
        base = "T" + datetime.now().strftime("%m%d-%H%M%S")
        tid, n = base, 1
        while tid in self.active:
            n += 1
            tid = f"{base}-{n}"
        return tid

    async def submit(self, req: TaskRequest) -> str | None:
        reason = self.runner.unavailable_reason()
        if reason:  # obuna limiti tugagan — tiklanishigacha CLI'ni bekorga urmaymiz
            await self.notify(reason)
            return None
        entry = ActiveTask(req=req, status=TaskStatus())
        self.active[req.id] = entry
        entry.task = asyncio.create_task(self._run(entry), name=req.id)
        return req.id

    async def _run(self, entry: ActiveTask) -> None:
        req, status = entry.req, entry.status
        heartbeat = asyncio.create_task(self._heartbeat(entry))
        try:
            if self.sem.locked():
                await self.notify(f"🕒 {req.id} navbatga qo'yildi (bir vaqtda {self.cfg.max_concurrent_tasks} ta ish).")
            async with self.sem:
                status.started = time.monotonic()
                outcome = await self.runner.run(req, self.channel_factory(req.id), status)
            await self.send_outcome(outcome)
        except asyncio.CancelledError:
            self.journal.event("task_cancelled", f"Topshiriq {req.id} to'xtatildi (/stop)", task=req.id,
                               steps=status.steps)
            await self.notify(f"⛔ {req.id} to'xtatildi. Bajarilgan amallar: {status.steps} (jurnalda).")
        except Exception as exc:  # noqa: BLE001
            log.exception("Topshiriq %s yiqildi", req.id)
            self.journal.event("task_error", f"Topshiriq {req.id} xato: {type(exc).__name__}", task=req.id,
                               error=f"{type(exc).__name__}: {exc}")
            await self.notify(f"❌ {req.id} ichki xato bilan to'xtadi: {type(exc).__name__}: {str(exc)[:300]}")
        finally:
            heartbeat.cancel()
            self.active.pop(req.id, None)
            if self.on_finish:
                self.on_finish(req.id)

    async def _heartbeat(self, entry: ActiveTask) -> None:
        await asyncio.sleep(self.cfg.progress_after)
        last = -1
        while entry.req.id in self.active:
            st = entry.status
            if st.steps != last:
                last = st.steps
                now = _elapsed(time.monotonic() - st.started)
                await self.notify(f"⏳ {entry.req.id} · {now} · {st.steps} amal · hozir: {st.last_step or 'tahlil qilyapman'}")
            await asyncio.sleep(self.cfg.progress_interval)

    def cancel(self, task_id: str | None = None) -> list[str]:
        targets = [tid for tid in self.active if task_id is None or tid.lower() == task_id.lower()]
        for tid in targets:
            task = self.active[tid].task
            if task:
                task.cancel()
        return targets

    def status_text(self) -> str:
        if not self.active:
            return "Faol topshiriq yo'q."
        rows = []
        for tid, e in self.active.items():
            st = e.status
            rows.append(f"• {tid} · {_elapsed(time.monotonic() - st.started)} · {st.steps} amal\n"
                        f"  {e.req.text[:80]}\n  hozir: {st.last_step or '—'}")
        return "\n".join(rows)
