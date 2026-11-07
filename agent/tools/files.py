"""read_file, write_file, backup_before_change."""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from .. import gate
from ..inventory import PlaceholderError
from . import http_api, powershell, ssh
from .base import ToolContext, ToolResult, safe_name, today_dir


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace")
    if b"\x00" in raw[:8192]:
        raise ValueError("binar fayl — matn sifatida o'qib bo'lmaydi")
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


DOC_SUFFIXES = {".docx", ".xlsx", ".xlsm", ".pdf"}
_MAX_SHEET_ROWS = 20000


def _read_document(path: Path) -> str:
    """Word / Excel / PDF dan matn (jadval qatorlari TAB bilan). Formatlash va rasmlar olinmaydi."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        import docx

        d = docx.Document(str(path))
        parts = [p.text for p in d.paragraphs]
        for i, table in enumerate(d.tables, 1):
            parts.append(f"=== jadval {i} ===")
            parts += ["\t".join(c.text.strip() for c in row.cells) for row in table.rows]
        return "\n".join(parts)
    if suffix in (".xlsx", ".xlsm"):
        import openpyxl
        from openpyxl.utils import get_column_letter

        from ..artifacts import xlsx as axl

        computed: dict = {}
        try:
            if axl.missing_cache(path):  # openpyxl yozgan formulaning natijasi faylda yo'q — o'zimiz hisoblaymiz
                computed = axl.compute(path).values
        except Exception:  # noqa: BLE001 — o'qish baribir davom etadi
            computed = {}
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        try:
            out = []
            if computed:
                out.append(f"(ƒ: {len(computed)} ta formula natijasi faylda saqlanmagan edi — kod hisoblab ko'rsatdi. "
                           "Telegram/telefonda bunday katak BO'SH ko'rinadi; verify_artifact yoki notify_owner uni "
                           "formulani saqlagan holda tuzatadi.)")
            for ws in wb.worksheets:
                out.append(f"=== varaq: {ws.title} ===")
                for n, row in enumerate(ws.iter_rows(min_row=1, values_only=True), start=1):
                    if n > _MAX_SHEET_ROWS:
                        out.append(f"(... {_MAX_SHEET_ROWS} qatordan keyingisi o'qilmadi)")
                        break
                    if computed:
                        row = tuple(computed.get(f"{ws.title}!{get_column_letter(ci)}{n}", v) if v is None else v
                                    for ci, v in enumerate(row, start=1))
                    if any(v is not None for v in row):
                        out.append("\t".join("" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer()
                                                                     else str(v)) for v in row))
            return "\n".join(out)
        finally:
            wb.close()
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [f"--- sahifa {i} ---\n{(page.extract_text() or '').strip()}" for i, page in enumerate(reader.pages, 1)]
    text = "\n".join(pages)
    if not any(p.split("\n", 1)[-1].strip() for p in pages):
        text += "\n(PDF da matn qatlami yo'q — skaner qilingan bo'lishi mumkin)"
    return text


# ---------------------------------------------------------------- read_file
def classify_read(ctx: ToolContext, args: dict) -> gate.Decision:
    return gate.classify_file_read(ctx.resolve_path(args["path"]), ctx.secret_paths)


async def read_file(ctx: ToolContext, args: dict) -> ToolResult:
    path = ctx.resolve_path(args["path"])
    if path.is_dir():
        items = sorted(path.iterdir())[:300]
        listing = "\n".join(f"{'[D]' if p.is_dir() else '   '} {p.name}" for p in items)
        return ToolResult(True, f"{path} (papka, {len(items)} ta element):\n{listing}")
    if not path.exists():
        return ToolResult(False, f"Fayl topilmadi: {path}")
    is_doc = path.suffix.lower() in DOC_SUFFIXES
    text = _read_document(path) if is_doc else _read_text(path)
    lines = text.splitlines()
    start = max(1, int(args.get("start_line") or 1))
    count = max(1, min(int(args.get("max_lines") or 400), 5000))
    chunk = lines[start - 1:start - 1 + count]
    end = start - 1 + len(chunk)
    header = f"{path}{' (hujjat matni)' if is_doc else ''} — jami {len(lines)} qator; {start}-{end} ko'rsatildi"
    if end < len(lines):
        header += f" (davomi: start_line={end + 1})"
    return ToolResult(True, header + "\n" + "\n".join(chunk))


# ---------------------------------------------------------------- write_file
def classify_write(ctx: ToolContext, args: dict) -> gate.Decision:
    d = gate.classify_file_write(ctx.resolve_path(args["path"]), ctx.paths.home, ctx.secret_paths, ctx.code_root)
    risk = gate.trading_risk(str(args.get("content") or ""))
    if risk and risk[2] == "real_trade":  # buyurtma kodi yozish — faqat tasdiq bilan
        d.escalate(*risk)
    return d


def backup_local_file(ctx: ToolContext, path: Path, host: str = "localhost") -> Path:
    dest_dir = today_dir(ctx.paths.zaxira)
    dest = dest_dir / f"{datetime.now():%H%M%S}_{safe_name(host)}_file_{safe_name(path.name)}"
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)
    _index(ctx, host, "file", str(path), dest)
    return dest


def _index(ctx: ToolContext, host: str, kind: str, target: str, dest: Path, note: str = "") -> None:
    ctx.record_backup(host, kind, dest)
    with (dest.parent / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"), "task": ctx.task_id, "host": host,
                            "kind": kind, "target": ctx.redactor.redact(target), "path": str(dest), "note": note},
                           ensure_ascii=False) + "\n")


async def write_file(ctx: ToolContext, args: dict) -> ToolResult:
    path = ctx.resolve_path(args["path"])
    content = args.get("content", "")
    note = ""
    if any(gate.inside(path, d) for d in (ctx.paths.xotira, ctx.paths.skill, ctx.paths.skript)):
        redacted = ctx.redactor.redact(content)
        if redacted != content:
            note = " Maxfiy qiymatlar *** bilan yashirildi (GitHubga tushadigan papka)."
        content = redacted
    backup = ""
    if not gate.inside(path, ctx.paths.home) and path.exists():
        backup = f" Avvalgi holat zaxiralandi: {backup_local_file(ctx, path)}."
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if path.suffix.lower() in {".ps1", ".psm1", ".psd1"} else "utf-8"
    if args.get("mode") == "append" and path.exists():
        with path.open("a", encoding="utf-8") as f:
            f.write(content)
    else:
        path.write_text(content, encoding=encoding)
    return ToolResult(True, f"Yozildi: {path} ({len(content.encode('utf-8'))} bayt).{backup}{note}")


# ---------------------------------------------------------------- backup_before_change
BACKUP_KINDS = ["file", "registry", "powershell", "ssh", "http_get", "mikrotik_export", "dhcp_export",
                "gpo_backup", "firewall_export"]


_UNSAFE_ARG = re.compile(r"['\"`;|&\r\n$]")


def classify_backup(ctx: ToolContext, args: dict) -> gate.Decision:
    kind = args.get("kind")
    host = args.get("host") or "localhost"
    d = gate.Decision(level=gate.INTERNAL, host=host)
    if kind in ("registry", "dhcp_export", "gpo_backup", "mikrotik_export"):
        for value in (args.get("target") or "", host):
            if _UNSAFE_ARG.search(value):
                return d.escalate(gate.BLOCK, f"'{value}' ichida ruxsat etilmagan belgi bor (', \", ;, |, &, $, `)")
    inner = None
    if kind == "powershell":
        inner = gate.classify_powershell(args.get("target", ""), host=host, protected_paths=ctx.secret_paths)
    elif kind == "ssh":
        found = ctx.inventory.get(host)
        dtype = found[1].get("type") if found else "linux"
        inner = gate.classify_ssh(dtype, list(args.get("commands") or [args.get("target", "")]), host)
    elif kind == "http_get":
        http_api.check_egress(ctx, {"url": args.get("target", "")})
    elif kind == "file":
        inner = gate.classify_file_read(ctx.resolve_path(args.get("target", "")), ctx.secret_paths)
    if inner is not None and inner.level in (gate.DANGER, gate.BLOCK):
        return d.escalate(gate.BLOCK, "Zaxira buyrug'i faqat o'qish/eksport bo'lishi kerak: " + "; ".join(inner.reasons))
    return d


async def _save(ctx: ToolContext, host: str, kind: str, target: str, text: str, ext: str, note: str) -> Path:
    dest = today_dir(ctx.paths.zaxira) / f"{datetime.now():%H%M%S}_{safe_name(host)}_{kind}_{safe_name(target, 30)}.{ext}"
    dest.write_text(text, encoding="utf-8")
    _index(ctx, host, kind, target, dest, note)
    return dest


async def backup_before_change(ctx: ToolContext, args: dict) -> ToolResult:
    kind, target = args["kind"], str(args.get("target") or "")
    host = (args.get("host") or "localhost").strip() or "localhost"
    note = args.get("note", "")
    zdir = today_dir(ctx.paths.zaxira)
    stamp = f"{datetime.now():%H%M%S}_{safe_name(host)}"

    if kind == "file":
        path = ctx.resolve_path(target)
        if not path.exists():
            return ToolResult(False, f"Zaxira uchun fayl/papka topilmadi: {path}")
        dest = backup_local_file(ctx, path, host)
    elif kind == "registry":
        dest = zdir / f"{stamp}_registry_{safe_name(target, 40)}.reg"
        rc, out = await powershell.run_script(ctx, f"reg export '{target}' '{dest}' /y", host=None)
        if rc != 0 or not dest.exists():
            return ToolResult(False, f"reg export bajarilmadi:\n{out}")
        _index(ctx, host, kind, target, dest, note)
    elif kind in ("powershell", "firewall_export"):
        script = target
        if kind == "firewall_export":
            script = ("Get-NetFirewallRule -PolicyStore ActiveStore | Select-Object Name,DisplayName,Enabled,Direction,"
                      "Action,Profile | ConvertTo-Json -Depth 3")
        rc, out = await powershell.run_script(ctx, script, host=host)
        if rc != 0 and not out.strip():
            return ToolResult(False, f"Zaxira buyrug'i xato berdi (exit {rc}):\n{out}")
        dest = await _save(ctx, host, kind, target or kind, out, "txt", note)
    elif kind == "dhcp_export":
        dest = zdir / f"{stamp}_dhcp_export.xml"
        server = "" if host in powershell.LOCAL_HOSTS else f" -ComputerName '{powershell.resolve_host(ctx, host)[0]}'"
        rc, out = await powershell.run_script(ctx, f"Export-DhcpServer{server} -File '{dest}' -Leases -Force")
        if rc != 0 or not dest.exists():
            return ToolResult(False, f"Export-DhcpServer bajarilmadi:\n{out}")
        _index(ctx, host, kind, "dhcp", dest, note)
    elif kind == "gpo_backup":
        dest = zdir / f"{stamp}_gpo_backup"
        dest.mkdir(exist_ok=True)
        server = "" if host in powershell.LOCAL_HOSTS else f" -Server '{powershell.resolve_host(ctx, host)[0]}'"
        rc, out = await powershell.run_script(ctx, f"Backup-GPO -All -Path '{dest}'{server} | Select-Object DisplayName,Id | Format-Table -AutoSize")
        if rc != 0:
            return ToolResult(False, f"Backup-GPO bajarilmadi:\n{out}")
        _index(ctx, host, kind, "gpo", dest, note)
    elif kind in ("ssh", "mikrotik_export"):
        commands = list(args.get("commands") or ([target] if target else []))
        if kind == "mikrotik_export":
            commands = ["/export show-sensitive"]
        if not commands:
            return ToolResult(False, "ssh zaxira uchun commands (yoki target) bering, masalan ['show running-config']")
        try:
            name, results = await ssh.run_commands(ctx, host, commands, args.get("timeout_sec") or 180)
            if kind == "mikrotik_export" and results and results[0][2] != 0:
                name, results = await ssh.run_commands(ctx, host, ["/export"], 180)
        except PlaceholderError as exc:
            return ToolResult(False, str(exc))
        text = "\n".join(f"# $ {c}\n{o}" for c, o, _ in results)
        dest = await _save(ctx, name, kind, " ".join(commands), text, "rsc" if kind == "mikrotik_export" else "txt", note)
        host = name
    elif kind == "http_get":
        res = await http_api.request(ctx, {"method": "GET", "url": target, "session": args.get("session"),
                                           "auth_entry": args.get("auth_entry")})
        if not res.ok:
            return ToolResult(False, f"GET xato:\n{res.output[:2000]}")
        dest = await _save(ctx, res.host or host, kind, target, res.output, "txt", note)
        host = res.host or host
    else:
        return ToolResult(False, f"Noma'lum kind: {kind}. Ruxsat: {', '.join(BACKUP_KINDS)}")

    size = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file()) if dest.is_dir() else dest.stat().st_size
    return ToolResult(True, f"Zaxira olindi ({kind}, host={host}): {dest} ({size} bayt). Endi o'zgartirish mumkin.",
                      host=host)


READ_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Fayl yoki papka yo'li. Nisbiy yo'l AGENT_HOME ga nisbatan."},
        "start_line": {"type": "integer"},
        "max_lines": {"type": "integer", "description": "Standart 400."},
    },
    "required": ["path"],
}
WRITE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Nisbiy yo'l AGENT_HOME ga nisbatan (masalan skript/disk_tozalash.ps1)."},
        "content": {"type": "string"},
        "mode": {"type": "string", "enum": ["overwrite", "append"]},
    },
    "required": ["path", "content"],
}
BACKUP_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": BACKUP_KINDS,
                 "description": "file=fayl/papka nusxasi; registry=reg export; powershell=o'qish buyrug'i natijasi; "
                                "ssh=qurilma buyruqlari natijasi (show running-config...); http_get=API javobi; "
                                "mikrotik_export=/export; dhcp_export=Export-DhcpServer; gpo_backup=Backup-GPO -All; "
                                "firewall_export=firewall qoidalari."},
        "target": {"type": "string", "description": "Fayl yo'li / registr kaliti / PowerShell buyrug'i / URL."},
        "host": {"type": "string", "description": "Inventar nomi yoki host. Bo'sh — shu server."},
        "commands": {"type": "array", "items": {"type": "string"}, "description": "kind=ssh uchun buyruqlar."},
        "session": {"type": "string"},
        "auth_entry": {"type": "string"},
        "timeout_sec": {"type": "integer"},
        "note": {"type": "string"},
    },
    "required": ["kind"],
}
