"""HTTP server: statik Next.js eksporti (web/out) + JSON API. Faqat 127.0.0.1.

Himoya:
  • faqat loopback'ga bog'lanadi; Host sarlavhasi 127.0.0.1/localhost:<port> bo'lmasa — rad (DNS rebinding);
  • API — sessiya cookie (HttpOnly, SameSite=Strict) bilan; sessiya faqat token bilan ochiladi (token
    ish/dashboard.json da, u GitHub'ga tushmaydi). Skriptlar uchun: X-Dashboard-Token sarlavhasi;
  • POST so'rovlarda X-Requested-With: sentinal majburiy va Origin (bo'lsa) o'zimizniki bo'lishi shart (CSRF);
  • har javob Redactor'dan o'tadi; inventardan faqat maxfiy bo'lmagan maydonlar olinadi;
  • buyruq bajaradigan, faylga yozadigan (o'z keshidan tashqari) yoki boshqa kompyuterga ulanadigan endpoint YO'Q.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import re
import logging
import mimetypes
import secrets
import sys
import threading
import time
from collections import deque
from datetime import date, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import psutil

from .. import __version__
from ..config import Config
from ..inventory import Inventory
from ..redact import Redactor
from ..workspace import Paths
from . import activity
from .agentstate import agent_status
from .devices import DeviceCatalog, hierarchy
from .localsys import LocalInventory, Sampler
from .settings import DashboardSettings

log = logging.getLogger(__name__)

COOKIE = "sentinal_sid"
_LOGIN_KEYS = {"username", "user", "login", "account", "phone", "api_id", "api_hash", "code"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/plain", ".txt")


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class DashboardApp:
    def __init__(self, cfg: Config, settings: DashboardSettings, paths: Paths, token: str):
        self.cfg = cfg
        self.settings = settings
        self.paths = paths
        self.token = token
        self.inventory = Inventory(paths.inventory_json)
        # Dashboard'da parol/tokenlardan tashqari inventardagi login nomlari ham yashiriladi (credential juftining yarmi).
        self.redactor = Redactor(lambda: [*self.inventory.secret_values(), *_inventory_logins(self.inventory)])
        self.redactor.add(cfg.telegram_token, cfg.claude_oauth_token, cfg.control_token, cfg.azure_speech_key, token)
        self.local = LocalInventory(paths.ish / "dashboard" / "local_inventory.json")
        self.sampler = Sampler(settings.sample_sec, settings.history_points)
        self.catalog = DeviceCatalog(paths.home, self.inventory, settings.ad_exports, self.local, settings.stale_days)
        self.sessions: dict[str, float] = {}
        self._fails: deque = deque(maxlen=50)
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        self._chat_status: tuple[float, dict] | None = None
        self.started = datetime.now().isoformat(timespec="seconds")
        self.chat = None
        self.loop: asyncio.AbstractEventLoop | None = None
        if settings.chat_enabled:
            from .chat import ReadOnlyChat
            self.chat = ReadOnlyChat(cfg, paths.home, self.redactor, self.inventory.public_view,
                                     paths.ish / "dashboard" / "web_chat.jsonl")
            self.loop = asyncio.new_event_loop()
            threading.Thread(target=self.loop.run_forever, name="dashboard-chat-loop", daemon=True).start()

    def start_background(self) -> None:
        self.sampler.start()
        threading.Thread(target=self.local.get, name="dashboard-local-inventory", daemon=True).start()

    # ------------------------------------------------------------------ sessiya
    def login(self, token: str) -> str:
        now = time.time()
        with self._lock:
            recent = [t for t in self._fails if now - t < 60]
            if len(recent) >= 10:
                raise ApiError(429, "Too many attempts. Wait a minute.")
            if not token or not hmac.compare_digest(token.encode(), self.token.encode()):
                self._fails.append(now)
                raise ApiError(401, "Invalid access token")
            sid = secrets.token_urlsafe(32)
            self.sessions = {k: v for k, v in self.sessions.items() if v > now}
            self.sessions[sid] = now + self.settings.session_hours * 3600
            return sid

    def valid_session(self, sid: str | None, header_token: str | None) -> bool:
        if header_token and hmac.compare_digest(header_token.encode(), self.token.encode()):
            return True
        if not sid:
            return False
        with self._lock:
            exp = self.sessions.get(sid)
            return bool(exp and exp > time.time())

    def logout(self, sid: str | None) -> None:
        with self._lock:
            self.sessions.pop(sid or "", None)

    # ------------------------------------------------------------------ yordamchilar
    def devices(self) -> tuple[list[dict], list]:
        return self.catalog.build()

    def _replies(self) -> dict:
        return activity.chat_replies(self.paths.chat_history)

    def _device_or_404(self, device_id: str) -> tuple[dict, list[dict]]:
        devices, _ = self.devices()
        dev = next((d for d in devices if d["id"] == device_id), None)
        if dev is None:
            raise ApiError(404, "Device not found")
        return dev, devices

    def _run_async(self, coro, timeout: float):
        if self.loop is None:
            raise ApiError(503, "Chat is disabled (DASHBOARD_CHAT=0)")
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=timeout)

    # ------------------------------------------------------------------ API
    def api(self, method: str, path: str, query: dict, body: dict) -> object:
        q = {k: v[-1] for k, v in query.items()}
        routes_get = {
            "/api/session": lambda: {"ok": True},
            "/api/overview": self.overview,
            "/api/devices": self.devices_list,
            "/api/hierarchy": self.hierarchy,
            "/api/monitoring/current": self.sampler.current,
            "/api/monitoring/history": lambda: {"interval": self.settings.sample_sec, "points": self.sampler.series()},
            "/api/monitoring/system": self.local_system,
            "/api/monitoring/software": self.software,
            "/api/activity": lambda: self.activity(q),
            "/api/activity/days": lambda: {"days": activity.available_days(self.paths.jurnal)},
            "/api/reports": lambda: self.reports(q),
            "/api/agent": lambda: agent_status(self.paths.ish),
            "/api/chat/status": self.chat_status,
            "/api/chat/history": self.chat_history,
            "/api/settings": self.settings_view,
        }
        if method == "GET" and path in routes_get:
            return routes_get[path]()
        if method == "GET" and path.startswith("/api/devices/"):
            return self.device_detail(unquote(path[len("/api/devices/"):]))
        if method == "POST" and path == "/api/monitoring/refresh":
            return self.refresh_local()
        if method == "POST" and path == "/api/chat":
            return self.chat_ask(body)
        raise ApiError(404, "Not found")

    def overview(self) -> dict:
        devices, sources = self.devices()
        tree = hierarchy(devices)
        status: dict[str, int] = {}
        os_count: dict[str, int] = {}
        for d in devices:
            status[d["status"]] = status.get(d["status"], 0) + 1
            os_count[d["os"] or "Unknown"] = os_count.get(d["os"] or "Unknown", 0) + 1
        objects = {(o["name"], ob["name"]) for o in tree for ob in o["objects"] if ob["name"]}
        depts = {(o["name"], ob["name"], dep["name"]) for o in tree for ob in o["objects"] for dep in ob["departments"]
                 if dep["name"]}
        local = self.local.get()
        return {
            "devices_total": len(devices),
            "device_status": status,
            "os": sorted(({"name": k, "count": v} for k, v in os_count.items()), key=lambda x: -x["count"]),
            "organizations": len([o for o in tree if o["name"]]),
            "objects": len(objects),
            "departments": len(depts),
            "unassigned": sum(o["count"] for o in tree if not o["name"]),
            "local": {"name": local.get("computer_name"), "os": (local.get("windows") or {}).get("label"),
                      "id": next((d["id"] for d in devices if d["is_local"]), None)},
            "metrics": self.sampler.current(),
            "today": activity.today_summary(self.paths.jurnal, self._replies()),
            "agent": agent_status(self.paths.ish),
            "sources": [s.__dict__ for s in sources],
        }

    def devices_list(self) -> dict:
        devices, sources = self.devices()
        return {"devices": devices, "sources": [s.__dict__ for s in sources], "stale_days": self.settings.stale_days}

    def hierarchy(self) -> dict:
        devices, sources = self.devices()
        return {"tree": hierarchy(devices), "total": len(devices), "tuzilma_path": str(self.catalog.tuzilma_path),
                "sources": [s.__dict__ for s in sources]}

    def device_detail(self, device_id: str) -> dict:
        dev, _ = self._device_or_404(device_id)
        names = {n.lower() for n in [dev["name"], *(dev["inventory_names"] or []), *(dev["ipv4"] or [])] if n}
        if dev["host"]:
            names |= {dev["host"].lower(), dev["host"].split(".")[0].lower()}
        if dev["is_local"]:
            names |= {"localhost", "127.0.0.1"}
        end = date.today()
        records = activity.load_records(self.paths.jurnal, end - timedelta(days=29), end)
        related = [a for a in activity.build_actions(records) if str(a["host"] or "").lower() in names]
        task_ids = {a["task"] for a in related}
        tasks = [t for t in activity.build_tasks(records, self._replies()) if t["id"] in task_ids]
        out = {"device": dev, "actions": related[:50], "tasks": tasks[:30], "activity_window_days": 30}
        if dev["is_local"]:
            local = self.local.get()
            out["local"] = {k: v for k, v in local.items() if k != "software"}
            out["metrics"] = self.sampler.current()
        return out

    def local_system(self) -> dict:
        local = self.local.get()
        return {k: v for k, v in local.items() if k != "software"}

    def software(self) -> dict:
        local = self.local.get()
        return {"collected_at": local.get("collected_at"), "count": local.get("software_count"),
                "software": local.get("software") or []}

    def refresh_local(self) -> dict:
        now = time.time()
        if now - self._last_refresh < 20:
            raise ApiError(429, "Inventory was refreshed moments ago. Try again in a few seconds.")
        self._last_refresh = now
        data = self.local.refresh()
        return {"ok": True, "collected_at": data.get("collected_at"), "software_count": data.get("software_count")}

    def activity(self, q: dict) -> dict:
        start, end = activity.parse_range(q.get("start"), q.get("end"))
        records = activity.load_records(self.paths.jurnal, start, end)
        view = q.get("view") or "tasks"
        if view == "actions":
            items = activity.build_actions(records)
        elif view == "events":
            items = activity.build_events(records)
        else:
            view = "tasks"
            items = activity.build_tasks(records, self._replies())
        text = (q.get("q") or "").strip().lower()
        if text:
            items = [i for i in items if text in json.dumps(i, ensure_ascii=False, default=str).lower()]
        status = q.get("status") or ""
        if status == "failed":
            items = [i for i in items if (i.get("status") not in ("ok", "running") if view == "tasks"
                                          else not i.get("success", True) or i.get("error") is True)]
        elif status == "ok":
            items = [i for i in items if (i.get("status") == "ok" if view == "tasks" else i.get("success", True)
                                          and not i.get("error"))]
        total = len(items)
        limit = min(max(int(q.get("limit") or 300), 1), 1000)
        return {"view": view, "range": {"start": start.isoformat(), "end": end.isoformat()}, "total": total,
                "items": items[:limit], "truncated": total > limit}

    def reports(self, q: dict) -> dict:
        start, end = activity.parse_range(q.get("start"), q.get("end"), default_days=30)
        records = activity.load_records(self.paths.jurnal, start, end)
        rep = activity.report(records, self._replies(), start, end)
        devices, sources = self.devices()
        by = lambda key: sorted(  # noqa: E731
            ({"name": k, "count": v} for k, v in _count(devices, key).items()), key=lambda x: -x["count"])
        rep["inventory"] = {"total": len(devices), "by_status": by("status"), "by_os": by("os"),
                            "by_department": by("department"), "by_object": by("object"),
                            "sources": [s.__dict__ for s in sources]}
        return rep

    def chat_status(self) -> dict:
        if self.chat is None:
            return {"enabled": False, "available": False}
        cached = self._chat_status
        if cached and time.time() - cached[0] < 60:
            return cached[1]
        st = {"enabled": True, **self._run_async(self.chat.status(), 90)}
        self._chat_status = (time.time(), st)
        return st

    def chat_history(self) -> dict:
        path = self.paths.ish / "dashboard" / "web_chat.jsonl"
        items = []
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-40:]:
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue
        return {"items": items}

    def chat_ask(self, body: dict) -> dict:
        if self.chat is None:
            raise ApiError(503, "Chat is disabled (DASHBOARD_CHAT=0)")
        from .chat import snapshot_text
        devices, _ = self.devices()
        snap = snapshot_text(devices, self.local.get(), self.sampler.current(),
                             activity.today_summary(self.paths.jurnal, self._replies()), agent_status(self.paths.ish))
        messages = body.get("messages") if isinstance(body.get("messages"), list) else []
        result = self._run_async(self.chat.ask(messages, snap), 360)
        if result.get("error"):
            self._chat_status = None
        return result

    def settings_view(self) -> dict:
        c, s = self.cfg, self.settings
        web_index = s.web_dir / "index.html"
        _, sources = self.devices()
        return {
            "app": {"name": "SENTINAL CONTROL CENTER", "version": "12.1", "agent_version": __version__,
                    "started": self.started, "python": sys.version.split()[0], "psutil": psutil.__version__,
                    "web_build": datetime.fromtimestamp(web_index.stat().st_mtime).isoformat(timespec="seconds")
                    if web_index.is_file() else None},
            "dashboard": {"bind": f"127.0.0.1:{s.port}", "chat_enabled": s.chat_enabled, "sample_sec": s.sample_sec,
                          "history_points": s.history_points, "session_hours": s.session_hours,
                          "stale_days": s.stale_days, "ad_exports": s.ad_exports,
                          "login_origin": "DASHBOARD_TOKEN (.env)" if s.token else "generated at each start (ish/dashboard.json)"},
            "agent": {"home": str(self.paths.home), "model": c.model, "strong_model": c.strong_model,
                      "effort": c.effort, "web_search": c.web_search, "max_concurrent_tasks": c.max_concurrent_tasks,
                      "control_panel": f"127.0.0.1:{c.control_port}" if c.control_enabled and c.control_port else None,
                      "stt": c.stt_enabled, "reels": c.reels_enabled,
                      "zabbix_poll_sec": c.zabbix_poll_sec, "daily_check_at": c.daily_check_at or None},
            # Faqat "sozlanganmi" belgisi — qiymat emas (kalit nomlari ro'yxat ichida: redaction ularni yashirmasin).
            "secrets_configured": [{"name": n, "configured": bool(v)} for n, v in (
                ("TELEGRAM_BOT_TOKEN", c.telegram_token), ("CLAUDE_CODE_OAUTH_TOKEN", c.claude_oauth_token),
                ("AZURE_SPEECH_KEY", c.azure_speech_key))],
            "inventory_entries": len(self.inventory.names()),
            "sources": [x.__dict__ for x in sources],
            "tuzilma_path": str(self.catalog.tuzilma_path),
            "restrictions": [
                "Bound to 127.0.0.1 only; requests with a foreign Host header are rejected.",
                "Read-only: no endpoint runs commands, changes settings or contacts other computers.",
                "Inventory credentials are never read into responses (only type, host, description).",
                "AI chat runs with all tools disabled; changes must go through the Telegram agent's approval flow.",
                "Local monitoring uses psutil and the Windows registry only (no network scanning).",
            ],
        }


def _inventory_logins(inventory: Inventory) -> list[str]:
    out = []
    for entry in inventory._load()["hosts"].values():  # noqa: SLF001 — faqat o'qish, javobga chiqmaydi
        for k, v in entry.items():
            if k.lower() in _LOGIN_KEYS and isinstance(v, str) and v.strip():
                out.append(v.strip())
    return out


def _count(devices: list[dict], key: str) -> dict:
    out: dict = {}
    for d in devices:
        k = d.get(key) or "Unknown"
        out[k] = out.get(k, 0) + 1
    return out


# ---------------------------------------------------------------------------------------------- HTTP handler
def make_handler(app: DashboardApp):
    allowed_hosts = {f"127.0.0.1:{app.settings.port}", f"localhost:{app.settings.port}"}
    web_dir = app.settings.web_dir.resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "SentinalDashboard"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003 — so'rovlar logi (token yo'q)
            log.debug("%s %s", self.address_string(), fmt % args)

        # -------------------------------------------------------------- javob
        def _headers(self, status: int, ctype: str, length: int, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()

        def _json(self, status: int, payload: object, extra: dict | None = None) -> None:
            snap = Redactor()
            snap.add(*app.redactor.known_values())
            data = json.dumps(snap.redact_obj(payload), ensure_ascii=False, default=str).encode("utf-8")
            headers = {"Cache-Control": "no-store"}
            headers.update(extra or {})
            self._headers(status, "application/json; charset=utf-8", len(data), headers)
            if self.command != "HEAD":
                self.wfile.write(data)

        def _cookie(self) -> str | None:
            raw = self.headers.get("Cookie")
            if not raw:
                return None
            try:
                c = SimpleCookie(raw)
            except Exception:  # noqa: BLE001
                return None
            return c[COOKIE].value if COOKIE in c else None

        # -------------------------------------------------------------- marshrut
        def _dispatch(self) -> None:
            host = (self.headers.get("Host") or "").lower()
            if host not in allowed_hosts:
                self._json(403, {"error": "Local access only"})
                return
            url = urlsplit(self.path)
            path = url.path
            if path.startswith("/api/"):
                self._api(path, parse_qs(url.query))
            elif self.command in ("GET", "HEAD"):
                self._static(path)
            else:
                self._json(405, {"error": "Method not allowed"})

        def _read_body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > 256_000:
                raise ApiError(413, "Request too large")
            raw = self.rfile.read(n) if n > 0 else b""
            if not raw:
                return {}
            try:
                data = json.loads(raw)
            except ValueError:
                raise ApiError(400, "Invalid JSON") from None
            return data if isinstance(data, dict) else {}

        def _api(self, path: str, query: dict) -> None:
            try:
                if self.command == "POST":
                    origin = self.headers.get("Origin")
                    if self.headers.get("X-Requested-With") != "sentinal" or (
                            origin and origin.lower() not in {f"http://{h}" for h in allowed_hosts}):
                        raise ApiError(403, "Cross-site request rejected")
                    body = self._read_body()
                elif self.command in ("GET", "HEAD"):
                    body = {}
                else:
                    raise ApiError(405, "Method not allowed")
                if path == "/api/health":
                    self._json(200, {"ok": True, "app": "sentinal-control-center"})
                    return
                if path == "/api/login" and self.command == "POST":
                    sid = app.login(str(body.get("token") or ""))
                    cookie = (f"{COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/; "
                              f"Max-Age={app.settings.session_hours * 3600}")
                    self._json(200, {"ok": True}, {"Set-Cookie": cookie})
                    return
                sid = self._cookie()
                if path == "/api/logout" and self.command == "POST":
                    app.logout(sid)
                    self._json(200, {"ok": True}, {"Set-Cookie": f"{COOKIE}=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0"})
                    return
                if not app.valid_session(sid, self.headers.get("X-Dashboard-Token")):
                    raise ApiError(401, "Not signed in")
                self._json(200, app.api(self.command, path, query, body))
            except ApiError as exc:
                self._json(exc.status, {"error": exc.message})
            except TimeoutError:
                self._json(504, {"error": "Timed out"})
            except Exception as exc:  # noqa: BLE001
                log.exception("API xatosi: %s", path)
                self._json(500, {"error": f"Internal error: {type(exc).__name__}"})

        def _static(self, path: str) -> None:
            if not (web_dir / "index.html").is_file():
                msg = (b"<!doctype html><meta charset=utf-8><title>SENTINAL</title><body style='background:#0d0d0d;"
                       b"color:#f0efec;font-family:system-ui;padding:40px'><h1>Web UI is not built</h1><p>Run: "
                       b"<code>cd web &amp;&amp; npm ci &amp;&amp; npm run build</code></p>")
                self._headers(503, "text/html; charset=utf-8", len(msg), {"Cache-Control": "no-store"})
                self.wfile.write(msg)
                return
            rel = unquote(path).lstrip("/")
            target = (web_dir / rel).resolve()
            if not target.is_relative_to(web_dir):
                self._json(404, {"error": "Not found"})
                return
            if target.is_dir():
                if not path.endswith("/"):
                    self._headers(308, "text/plain", 0, {"Location": path + "/"})
                    return
                target = target / "index.html"
            elif not target.is_file() and target.with_suffix(".html").is_file():
                target = target.with_suffix(".html")
            if not target.is_file():  # Next prefetch: /chart/__next.chart.__PAGE__.txt -> /chart/__next.chart/__PAGE__.txt
                m = re.fullmatch(r"(__next\..+)\.(__PAGE__\.txt)", target.name)
                alt = target.parent / m.group(1) / m.group(2) if m else None
                if alt is not None and alt.is_file() and alt.resolve().is_relative_to(web_dir):
                    target = alt.resolve()
            status = 200
            if not target.is_file():
                target, status = web_dir / "404.html", 404
                if not target.is_file():
                    self._json(404, {"error": "Not found"})
                    return
            data = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            immutable = "/_next/static/" in path
            self._headers(status, ctype, len(data),
                          {"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch()

        def do_HEAD(self) -> None:  # noqa: N802
            self._dispatch()

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch()

        def do_PUT(self) -> None:  # noqa: N802
            self._json(405, {"error": "Method not allowed"})

        do_DELETE = do_PATCH = do_OPTIONS = do_PUT

    return Handler


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # Windows'da SO_REUSEADDR boshqa jarayonga portni "o'g'irlash"ga yo'l qo'yadi


def make_server(app: DashboardApp) -> DashboardServer:
    return DashboardServer(("127.0.0.1", app.settings.port), make_handler(app))
