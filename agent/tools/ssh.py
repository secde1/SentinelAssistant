"""run_remote_ssh — Mikrotik / switch (netmiko) va Linux / UniFi / ESXi (paramiko exec)."""
from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from pathlib import Path

from .. import gate
from ..inventory import PlaceholderError, normalize_type
from .base import ToolContext, ToolResult

LINUX_LIKE = {"linux", "unifi", "esxi"}

_CLI_ERROR = re.compile(
    r"(?im)^\s*(?:% ?Invalid input|% ?Incomplete command|% ?Ambiguous command|% ?Unknown command|bad command name"
    r"|expected end of command|syntax error|failure:|input does not match any value|no such item|invalid value)"
)


def device_entry(ctx: ToolContext, host: str) -> tuple[str, dict]:
    found = ctx.inventory.get(host)
    if not found:
        raise PlaceholderError(
            f"Inventarda '{host}' yo'q. Avval request_credentials(name='{host}', fields=['host','username','password'], "
            "known={'type': 'mikrotik_routeros|linux|unifi|esxi|cisco_ios|...'}) chaqiring."
        )
    name, entry = found
    if not entry.get("host"):
        raise PlaceholderError(f"'{name}' yozuvida 'host' (IP) yo'q — inventory_set bilan qo'shing.")
    return name, entry


def _paramiko_exec(entry: dict, commands: list[str], timeout: int, known_hosts: Path) -> list[tuple[str, str, int]]:
    import paramiko

    host, port = str(entry["host"]), int(entry.get("port", 22))
    user, password = entry.get("username"), entry.get("password")
    client = paramiko.SSHClient()
    if known_hosts.exists():
        client.load_host_keys(str(known_hosts))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    transport = None
    try:
        try:
            client.connect(hostname=host, port=port, username=user, password=password,
                           key_filename=entry.get("key_file") or None, timeout=20, banner_timeout=20,
                           auth_timeout=20, look_for_keys=False, allow_agent=False)
            transport = client.get_transport()
        except paramiko.BadHostKeyException as exc:
            raise RuntimeError(
                f"{host}: SSH host kaliti O'ZGARGAN (MITM bo'lishi mumkin). Jamshidga xabar bering; "
                f"ishonchli bo'lsa {known_hosts} dan eski kalitni o'chirish kerak."
            ) from exc
        except paramiko.AuthenticationException:
            # ESXi va ba'zi qurilmalar faqat keyboard-interactive qabul qiladi.
            transport = paramiko.Transport((host, port))
            transport.connect()
            transport.auth_interactive(user, lambda title, instr, prompts: [password for _ in prompts])
        with suppress(Exception):
            client.save_host_keys(str(known_hosts))
        results = []
        for cmd in commands:
            chan = transport.open_session()
            chan.settimeout(timeout)
            chan.exec_command(cmd)
            out = chan.makefile("rb").read().decode("utf-8", errors="replace")
            err = chan.makefile_stderr("rb").read().decode("utf-8", errors="replace")
            status = chan.recv_exit_status()
            chan.close()
            text = out + (f"\n[stderr]\n{err}" if err.strip() else "")
            results.append((cmd, text, status))
        return results
    finally:
        if transport is not None and transport is not client.get_transport():
            transport.close()
        client.close()


def _netmiko_exec(entry: dict, device_type: str, commands: list[str], timeout: int,
                  config_set: bool) -> list[tuple[str, str, int]]:
    from netmiko import ConnectHandler

    params = dict(device_type=device_type, host=str(entry["host"]), username=entry.get("username"),
                  password=entry.get("password", ""), port=int(entry.get("port", 22)), conn_timeout=20,
                  banner_timeout=20, auth_timeout=20, fast_cli=False)
    if entry.get("key_file"):
        params.update(use_keys=True, key_file=entry["key_file"])
    if entry.get("enable_secret"):
        params["secret"] = entry["enable_secret"]
    conn = ConnectHandler(**params)
    try:
        if entry.get("enable_secret"):
            conn.enable()
        if config_set:
            out = conn.send_config_set(commands, read_timeout=timeout)
            return [("config: " + " ; ".join(commands), out, 1 if _CLI_ERROR.search(out) else 0)]
        results = []
        for cmd in commands:
            out = conn.send_command(cmd, read_timeout=timeout, strip_prompt=True, strip_command=True)
            results.append((cmd, out, 1 if _CLI_ERROR.search(out) else 0))
        return results
    finally:
        conn.disconnect()


async def run_commands(ctx: ToolContext, host: str, commands: list[str], timeout: int | None = None,
                       config_set: bool = False) -> tuple[str, list[tuple[str, str, int]]]:
    name, entry = device_entry(ctx, host)
    timeout = max(5, min(int(timeout or 120), 3600))
    resolved = [ctx.inventory.resolve(c, allowed_entries={name})[0] for c in commands]
    dtype = normalize_type(entry.get("type")) or "linux"
    if dtype in LINUX_LIKE:
        results = await asyncio.to_thread(_paramiko_exec, entry, resolved, timeout, ctx.paths.known_hosts)
    else:
        results = await asyncio.to_thread(_netmiko_exec, entry, dtype, resolved, timeout, config_set)
    # Ko'rsatishda placeholderli asl buyruq ishlatiladi.
    shown = [(commands[i] if i < len(commands) and not config_set else c, out, st) for i, (c, out, st) in enumerate(results)]
    return name, shown


def classify(ctx: ToolContext, args: dict) -> gate.Decision:
    host = args.get("host", "")
    found = ctx.inventory.get(host)
    dtype = normalize_type(found[1].get("type")) if found else "linux"
    d = gate.classify_ssh(dtype, list(args.get("commands") or []), found[0] if found else host)
    if args.get("config_set") and dtype not in LINUX_LIKE:
        d.escalate(gate.DANGER, "Tarmoq uskunasi config rejimida yoziladi", "network_config")
    return d


async def handler(ctx: ToolContext, args: dict) -> ToolResult:
    name, results = await run_commands(ctx, args["host"], list(args["commands"]), args.get("timeout_sec"),
                                       bool(args.get("config_set")))
    lines = []
    for cmd, out, status in results:
        lines.append(f"$ {cmd}" + (f"   [exit {status}]" if status else ""))
        lines.append(out.rstrip() or "(bo'sh)")
    ok = all(st == 0 for _, _, st in results)
    return ToolResult(ok=ok, output=f"[{name}]\n" + "\n".join(lines), host=name)


def summary(args: dict) -> str:
    return " ; ".join(args.get("commands") or [])[:300]


SCHEMA = {
    "type": "object",
    "properties": {
        "host": {"type": "string", "description": "Inventar nomi (yoki inventardagi IP)."},
        "commands": {"type": "array", "items": {"type": "string"}, "description": "Ketma-ket bajariladigan buyruqlar."},
        "config_set": {"type": "boolean", "description": "Cisco/HP kabi switchlarda config rejimida yuborish (send_config_set)."},
        "timeout_sec": {"type": "integer", "description": "Har buyruq uchun, standart 120."},
        "purpose": {"type": "string", "description": "Nima uchun va qanday TA'SIR qiladi (tasdiq so'rovida ko'rsatiladi)."},
    },
    "required": ["host", "commands"],
}

DESCRIPTION = (
    "SSH orqali qurilmada buyruq bajaradi. Qurilma turi inventardagi 'type' dan olinadi: mikrotik_routeros, "
    "cisco_ios, hp_procurve va boshqa netmiko turlari (CLI sessiya), yoki linux / unifi / esxi (exec). Login/parol "
    "inventardan avtomatik olinadi. Mikrotik/switch/UniFi konfiguratsiyasiga YOZISH kod tomonidan tasdiqqa yuboriladi "
    "va undan oldin backup_before_change majburiy."
)
