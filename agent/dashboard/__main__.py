"""Ishga tushirish:
    python -m agent.dashboard               — server + brauzerda ochish (dashboard.cmd shuni chaqiradi)
    python -m agent.dashboard --no-browser  — faqat server
Dashboard allaqachon ishlayotgan bo'lsa — yangi nusxa ochilmaydi, faqat brauzer ochiladi.
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import secrets
import sys
import urllib.request
import webbrowser
from datetime import datetime

from ..claude_cli import prepare_process_env
from ..config import Config
from ..logsetup import RedactFilter
from ..workspace import Paths
from .server import DashboardApp, make_server
from .settings import DashboardSettings


def _setup_logging(jurnal, redactor) -> None:
    jurnal.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler = logging.handlers.RotatingFileHandler(jurnal / "dashboard.log", maxBytes=2_000_000, backupCount=3,
                                                   encoding="utf-8")
    console = logging.StreamHandler(sys.stdout)
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.INFO)
    for h in (handler, console):
        h.setFormatter(fmt)
        h.addFilter(RedactFilter(redactor))
        root.addHandler(h)
    for noisy in ("claude_agent_sdk", "mcp", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:  # noqa: S310
            return json.loads(r.read()).get("app") == "sentinal-control-center"
    except (OSError, ValueError):
        return False


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m agent.dashboard", description="SENTINAL CONTROL CENTER")
    parser.add_argument("--no-browser", action="store_true", help="brauzerni ochmaslik")
    parser.add_argument("--port", type=int, help="port (standart: DASHBOARD_PORT yoki 8790)")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
    settings = DashboardSettings.from_env()
    if args.port:
        settings.port = args.port
    paths = Paths(cfg.agent_home)  # agent papkalariga tegmaydi: faqat o'z fayllari (ish/dashboard*)
    (paths.ish / "dashboard").mkdir(parents=True, exist_ok=True)
    info_file = paths.ish / "dashboard.json"

    if _already_running(settings.port):
        try:
            token = json.loads(info_file.read_text(encoding="utf-8")).get("token", "")
        except (OSError, ValueError):
            token = settings.token
        print(f"Dashboard allaqachon ishlayapti: http://127.0.0.1:{settings.port}/")
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{settings.port}/login/#t={token}")
        return 0

    removed = prepare_process_env()  # chat ham faqat obuna bilan: pullik API credential'lari jarayondan olinadi
    token = settings.token or secrets.token_urlsafe(24)
    app = DashboardApp(cfg, settings, paths, token)
    _setup_logging(paths.jurnal, app.redactor)
    log = logging.getLogger("agent.dashboard")
    if removed:
        log.info("Obuna rejimi: %s jarayon muhitidan olib tashlandi", ", ".join(removed))
    try:
        server = make_server(app)
    except OSError as exc:
        print(f"Port {settings.port} band yoki ochilmadi: {exc}. .env da DASHBOARD_PORT ni o'zgartiring.")
        return 2
    info_file.write_text(json.dumps({"port": settings.port, "token": token, "pid": os.getpid(),
                                     "started": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    app.start_background()
    url = f"http://127.0.0.1:{settings.port}/"
    log.info("SENTINAL CONTROL CENTER: %s (faqat shu kompyuter). To'xtatish: Ctrl+C yoki oynani yoping.", url)
    print(f"Kirish havolasi (token bilan) brauzerda ochiladi. Token: {info_file}")
    if not args.no_browser:
        webbrowser.open(f"{url}login/#t={token}")
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.sampler.stop()
        try:
            info_file.unlink()
        except OSError:
            pass
        log.info("Dashboard to'xtadi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
