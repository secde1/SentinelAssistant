"""Mahalliy boshqaruv serveri — faqat 127.0.0.1. Ustki panel (oynacha) shu orqali agentni kuzatadi va boshqaradi.

Telegram'dan tashqari, kompyuterning o'zida turuvchi panel uchun. Hech narsa tashqariga chiqmaydi:
  • faqat loopback (127.0.0.1) — tashqi tarmoqdan ko'rinmaydi;
  • har so'rovda X-Token majburiy (token maxfiy — ish/control.json da, u GitHub'ga tushmaydi);
  • chiqadigan matn Redactor orqali o'tadi (parol/token ko'rinmaydi).
Panel bilan server BITTA asyncio hodisa siklida ishlaydi: panelda bosilgan "ha" Telegram kutayotgan
o'sha tasdiqni ham yopadi (pending umumiy), topshiriq esa xuddi Telegram'dagidek navbatga tushadi.

Yangi tashqi kutubxona YO'Q — HTTP qo'lda, asyncio.start_server ustida.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from datetime import datetime

from .config import Config
from .journal import Journal
from .loop import AgentRunner, TaskRequest, _elapsed
from .pending import PendingInputs
from .redact import Redactor
from .tasks import TaskManager
from .workspace import Paths

log = logging.getLogger(__name__)

_KINDS = {"approval": "Tasdiq", "question": "Savol", "credential": "Maxfiy ma'lumot"}


class ControlServer:
    def __init__(self, cfg: Config, paths: Paths, journal: Journal, redactor: Redactor,
                 tasks: TaskManager, pending: PendingInputs, runner: AgentRunner):
        self.cfg = cfg
        self.paths = paths
        self.journal = journal
        self.redactor = redactor
        self.tasks = tasks
        self.pending = pending
        self.runner = runner
        self.token = ""
        self._server: asyncio.AbstractServer | None = None

    # ------------------------------------------------------------ hayot sikli
    async def start(self) -> None:
        self.token = self.cfg.control_token or secrets.token_urlsafe(18)
        self.redactor.add(self.token)
        self.paths.ish.mkdir(parents=True, exist_ok=True)
        (self.paths.ish / "control.json").write_text(
            json.dumps({"port": self.cfg.control_port, "token": self.token}, ensure_ascii=False),
            encoding="utf-8")
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", self.cfg.control_port)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ HTTP (qo'lda, oddiy)
    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), 10)
            if not request_line:
                writer.close()
                return
            parts = request_line.decode("latin1").split(" ")
            method, path = (parts + ["", ""])[:2]
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(reader.readline(), 10)
                if line in (b"\r\n", b"\n", b""):
                    break
                k, _, v = line.decode("latin1").partition(":")
                headers[k.strip().lower()] = v.strip()
            body = b""
            n = int(headers.get("content-length", "0") or "0")
            if 0 < n <= 1_000_000:
                body = await asyncio.wait_for(reader.readexactly(n), 10)
            status, payload = await self._route(method, path.split("?")[0], headers, body)
        except asyncio.IncompleteReadError:
            status, payload = 400, {"error": "noto'g'ri so'rov"}
        except Exception as exc:  # noqa: BLE001
            log.warning("control so'rovi: %s", exc)
            status, payload = 500, {"error": f"{type(exc).__name__}"}
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        head = (f"HTTP/1.1 {status} OK\r\nContent-Type: application/json; charset=utf-8\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n").encode("latin1")
        try:
            writer.write(head + data)
            await writer.drain()
        except Exception:  # noqa: BLE001
            pass
        finally:
            writer.close()

    async def _route(self, method: str, path: str, headers: dict[str, str], body: bytes):
        # Browser/boshqa manbadan himoya: Host loopback bo'lsin + to'g'ri token.
        host = headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", ""):
            return 403, {"error": "faqat mahalliy"}
        if headers.get("x-token", "") != self.token:
            return 403, {"error": "token noto'g'ri"}
        if method == "GET" and path == "/api/state":
            return 200, self._state()
        if method == "POST" and path == "/api/task":
            return await self._submit(body)
        if method == "POST" and path == "/api/answer":
            return self._answer(body)
        if method == "POST" and path == "/api/stop":
            return self._stop(body)
        return 404, {"error": "topilmadi"}

    # ------------------------------------------------------------ holat
    def _state(self) -> dict:
        r = self.redactor.redact
        active = []
        for tid, e in self.tasks.active.items():
            st = e.status
            elapsed = _elapsed(time.monotonic() - st.started) if st.started else "navbatda"
            active.append({"id": tid, "elapsed": elapsed, "steps": st.steps,
                           "last": r(st.last_step or ""), "text": r((e.req.text or "")[:160])})
        pend = [{"id": p.id, "kind": p.kind, "label": _KINDS.get(p.kind, p.kind),
                 "task_id": p.task_id, "text": r((p.text or "")[:1200])} for p in self.pending.all()]
        return {
            "ok": True,
            "model": self.cfg.model,
            "plan": self.runner.plan,
            "limits": r(self.runner.last_limits or ""),
            "blocked": self.runner.unavailable_reason() or "",
            "busy": bool(active),
            "tasks": active,
            "pending": pend,
            "activity": self._recent_activity(),
            "reply": self._last_reply(),
            "ts": datetime.now().strftime("%H:%M:%S"),
        }

    def _recent_activity(self, n: int = 8) -> list[dict]:
        day = datetime.now().strftime("%Y-%m-%d")
        out: list[dict] = []
        try:
            records = self.journal.read_records(day)
        except Exception:  # noqa: BLE001
            return out
        for rec in records[-40:]:
            t = rec.get("type")
            ts = (rec.get("ts") or "")[11:19]
            if t == "action":
                mark = "✓" if rec.get("success") else "✗"
                text = f"{mark} {rec.get('tool', '')}: {str(rec.get('result', ''))[:70]}"
            elif t in ("task_error", "task_cancelled", "quota", "claude_auth", "start"):
                text = str(rec.get("error") or rec.get("type"))
            else:
                continue
            out.append({"ts": ts, "text": self.redactor.redact(text)})
        return out[-n:]

    def _last_reply(self) -> str:
        path = self.paths.chat_history
        if not path.exists():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return ""
        for line in reversed(lines[-10:]):
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            return self.redactor.redact((rec.get("reply") or "")[:1500])
        return ""

    # ------------------------------------------------------------ amallar
    async def _submit(self, body: bytes):
        data = _json(body)
        text = (data.get("text") or "").strip()
        if not text:
            return 200, {"error": "topshiriq bo'sh"}
        reason = self.runner.unavailable_reason()
        if reason:
            return 200, {"error": reason}
        req = TaskRequest(id=self.tasks.new_id(), text=text, strong=bool(data.get("strong")))
        self.journal.event("panel_task", f"Ustki paneldan topshiriq: {req.id}", task=req.id, strong=req.strong)
        tid = await self.tasks.submit(req)
        return 200, {"id": tid}

    def _answer(self, body: bytes):
        data = _json(body)
        pid = str(data.get("id") or "")
        p = self.pending.get(pid)
        if p is None:
            return 200, {"ok": False, "error": "so'rov eskirgan"}
        if p.kind == "approval":
            ok = self.pending.resolve(pid, data.get("value") in (True, "yes", "y", "ha"))
        else:
            value = (data.get("value") or "").strip() if isinstance(data.get("value"), str) else data.get("value")
            ok = self.pending.resolve(pid, value or None)
        return 200, {"ok": ok}

    def _stop(self, body: bytes):
        data = _json(body)
        stopped = self.tasks.cancel((data.get("id") or "").strip() or None)
        return 200, {"stopped": stopped}


def _json(body: bytes) -> dict:
    try:
        obj = json.loads(body or b"{}")
        return obj if isinstance(obj, dict) else {}
    except ValueError:
        return {}
