"""run_powershell — lokal yoki WinRM orqali masofaviy PowerShell."""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import uuid
from contextlib import suppress
from pathlib import Path

from .. import gate
from .base import ToolContext, ToolResult

WRAPPER = Path(__file__).resolve().parent.parent / "ps" / "remote_wrapper.ps1"
LOCAL_HOSTS = {"", ".", "localhost", "127.0.0.1"}
_SECRET_ENV = ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")

_PRELUDE = """$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8
$global:__agentErr = $Error.Count
& {
"""
_EPILOGUE = """
} 2>&1 | Out-String -Width 220 -Stream
if ($Error.Count -gt $global:__agentErr) { exit 1 }
if ($LASTEXITCODE) { exit $LASTEXITCODE }
exit 0
"""


def pwsh_path(configured: str = "") -> str:
    if configured:
        return configured
    for cand in (shutil.which("pwsh"), r"C:\Program Files\PowerShell\7\pwsh.exe"):
        if cand and Path(cand).exists():
            return cand
    return shutil.which("powershell") or "powershell.exe"


def child_env(extra: dict | None = None, agent_home: Path | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _SECRET_ENV}
    if agent_home:
        env["AGENT_HOME"] = str(agent_home)
    env.update(extra or {})
    return env


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        with suppress(ProcessLookupError):
            os.kill(pid, 9)


async def exec_process(argv: list[str], env: dict, timeout: int) -> tuple[int, str]:
    """Jarayonni ishga tushiradi; timeout yoki bekor qilinsa butun daraxtni o'ldiradi."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, env=env, **kwargs,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        _kill_tree(proc.pid)
        with suppress(Exception):
            await asyncio.wait_for(proc.wait(), 10)
        if isinstance(exc, asyncio.CancelledError):
            raise
        return 124, f"[TIMEOUT: {timeout} soniyada tugamadi — jarayon to'xtatildi]"
    return proc.returncode or 0, decode(out or b"")


def resolve_host(ctx: ToolContext, host: str | None) -> tuple[str, dict | None, str | None]:
    """(hostname, inventar yozuvi, inventar nomi). Lokal bo'lsa hostname = 'localhost'."""
    h = (host or "").strip()
    if h.lower() in LOCAL_HOSTS:
        return "localhost", None, None
    found = ctx.inventory.get(h)
    if found:
        name, entry = found
        return str(entry.get("host") or name), entry, name
    return h, None, None


async def run_script(ctx: ToolContext, script: str, host: str | None = None, timeout: int | None = None) -> tuple[int, str]:
    """Placeholderlari almashtirilgan skriptni bajaradi. Vaqtinchalik fayllar har doim o'chiriladi."""
    timeout = max(5, min(int(timeout or ctx.cfg.command_timeout), 3600))
    hostname, entry, _name = resolve_host(ctx, host)
    resolved, _used = ctx.inventory.resolve(script)
    run_dir = ctx.work_dir / "run"
    run_dir.mkdir(exist_ok=True)
    exe = pwsh_path(ctx.cfg.pwsh_path)
    files: list[Path] = []
    try:
        if hostname == "localhost":
            path = run_dir / f"{uuid.uuid4().hex}.ps1"
            path.write_text(_PRELUDE + resolved + _EPILOGUE, encoding="utf-8-sig")
            files.append(path)
            argv = [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)]
            return await exec_process(argv, child_env(agent_home=ctx.paths.home), timeout)
        path = run_dir / f"{uuid.uuid4().hex}.ps1"
        path.write_text(resolved, encoding="utf-8-sig")
        files.append(path)
        extra = {"AGENT_SCRIPT_PATH": str(path), "AGENT_REMOTE_HOST": hostname}
        if entry:
            if entry.get("username"):
                extra["AGENT_REMOTE_USER"] = str(entry["username"])
                extra["AGENT_REMOTE_PASS"] = str(entry.get("password", ""))
            if entry.get("port"):
                extra["AGENT_REMOTE_PORT"] = str(entry["port"])
            if str(entry.get("ssl", "")).lower() in {"1", "true", "yes"}:
                extra["AGENT_REMOTE_SSL"] = "1"
            if entry.get("auth"):
                extra["AGENT_REMOTE_AUTH"] = str(entry["auth"])
        argv = [exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(WRAPPER)]
        return await exec_process(argv, child_env(extra, ctx.paths.home), timeout)
    finally:
        for f in files:
            with suppress(OSError):
                f.unlink()


def classify(ctx: ToolContext, args: dict) -> gate.Decision:
    cmd = args.get("command", "")
    host = (args.get("host") or "localhost").strip() or "localhost"
    extra = gate.referenced_scripts(cmd, ctx.paths.home)
    return gate.classify_powershell(cmd, host=host, extra_texts=extra, protected_paths=ctx.secret_paths)


async def handler(ctx: ToolContext, args: dict) -> ToolResult:
    host = args.get("host")
    rc, out = await run_script(ctx, args["command"], host, args.get("timeout_sec"))
    hostname = resolve_host(ctx, host)[0]
    body = out.strip() or "(bo'sh natija)"
    return ToolResult(ok=rc == 0, output=f"[exit {rc}] {hostname}\n{body}", host=hostname)


def summary(args: dict) -> str:
    return " ".join(str(args.get("command", "")).split())[:300]


SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "PowerShell skript matni (bir yoki bir necha qator)."},
        "host": {"type": "string", "description": "Masofaviy Windows host: inventar nomi yoki hostname/IP. Bo'sh — shu server."},
        "timeout_sec": {"type": "integer", "description": "Standart 600, maksimal 3600."},
        "purpose": {"type": "string", "description": "Nima uchun va qanday TA'SIR qiladi (tasdiq so'rovida ko'rsatiladi)."},
    },
    "required": ["command"],
}

DESCRIPTION = (
    "Windows serverda PowerShell 7 skriptini bajaradi. host berilsa — o'sha Windows hostda WinRM (Invoke-Command) "
    "orqali; host inventarda bo'lsa login/parol avtomatik olinadi. Maxfiy qiymat kerak bo'lsa placeholder yoz: "
    "{{inv:NOM.password}} yoki {{secret:NOM}}. Natija matn ko'rinishida qaytadi (exit kodi bilan). Xavfli amallar "
    "kod tomonidan avtomatik Jamshid tasdig'iga yuboriladi — alohida so'rama, purpose ga NIMA/QAYERDA/TA'SIR yoz."
)
