"""verify — o'zgartirishdan keyin natijani QAYTA o'lchash (faqat o'qish buyruqlari)."""
from __future__ import annotations

import asyncio
import re
import sys

from .. import gate
from . import http_api, powershell, ssh
from .base import ToolContext, ToolResult

METHODS = ["ping", "tcp", "service", "powershell", "ssh", "http"]


def _check(output: str, args: dict, default_ok: bool) -> tuple[bool, str]:
    reasons = []
    ok = default_ok
    if args.get("expect"):
        hit = args["expect"].lower() in output.lower()
        ok = ok and hit
        reasons.append(f"kutilgan '{args['expect']}' {'topildi' if hit else 'TOPILMADI'}")
    if args.get("expect_regex"):
        hit = re.search(args["expect_regex"], output, re.I | re.M) is not None
        ok = ok and hit
        reasons.append(f"regex {'mos' if hit else 'MOS EMAS'}")
    if args.get("expect_absent"):
        present = args["expect_absent"].lower() in output.lower()
        ok = ok and not present
        reasons.append(f"'{args['expect_absent']}' {'BOR (yomon)' if present else 'yo`q (yaxshi)'}")
    return ok, "; ".join(reasons)


def classify(ctx: ToolContext, args: dict) -> gate.Decision:
    method = args.get("method")
    host = args.get("host") or "localhost"
    d = gate.Decision(level=gate.READ, host=host)
    inner = None
    if method == "powershell":
        inner = gate.classify_powershell(args.get("command", ""), host=host, protected_paths=ctx.secret_paths)
    elif method == "ssh":
        found = ctx.inventory.get(host)
        inner = gate.classify_ssh(found[1].get("type") if found else "linux", [args.get("command", "")], host)
    elif method == "http":
        http_api.check_egress(ctx, {"url": args.get("target", "")})
    if inner is not None and inner.level != gate.READ:
        return d.escalate(gate.BLOCK, "verify faqat O'QISH buyrug'ini bajaradi: " + "; ".join(inner.reasons or [inner.level]))
    return d


async def handler(ctx: ToolContext, args: dict) -> ToolResult:
    method = args["method"]
    host = args.get("host")
    target = args.get("target", "")
    desc = args.get("description", "")
    if method == "ping":
        if not target:
            return ToolResult(False, "ping uchun target (IP/host) kerak")
        argv = ["ping", "-n", "3", "-w", "1500", target] if sys.platform == "win32" else ["ping", "-c", "3", "-W", "2", target]
        rc, out = await powershell.exec_process(argv, powershell.child_env(), 30)
        base_ok = rc == 0 and "ttl=" in out.lower()
    elif method == "tcp":
        h, _, port = target.rpartition(":")
        if not h or not port.isdigit():
            return ToolResult(False, "tcp uchun target 'host:port' ko'rinishida bo'lsin")
        try:
            _r, w = await asyncio.wait_for(asyncio.open_connection(h, int(port)), 6)
            w.close()
            out, base_ok = f"{target} TCP ulanish o'rnatildi", True
        except (OSError, asyncio.TimeoutError) as exc:
            out, base_ok = f"{target} TCP ulanish yo'q: {type(exc).__name__} {exc}", False
    elif method == "service":
        name = re.sub(r"[^\w.\- $]", "", target)
        rc, out = await powershell.run_script(
            ctx, f"Get-Service -Name '{name}' | Select-Object Name,DisplayName,Status,StartType | Format-List", host, 60)
        base_ok = rc == 0 and (bool(args.get("expect") or args.get("expect_regex")) or re.search(r"Status\s*:\s*Running", out) is not None)
    elif method == "powershell":
        rc, out = await powershell.run_script(ctx, args.get("command", ""), host, args.get("timeout_sec") or 120)
        base_ok = rc == 0
    elif method == "ssh":
        _name, results = await ssh.run_commands(ctx, host or "", [args.get("command", "")], args.get("timeout_sec") or 60)
        out = "\n".join(o for _, o, _ in results)
        base_ok = all(st == 0 for _, _, st in results)
    elif method == "http":
        res = await http_api.request(ctx, {"method": "GET", "url": target, "session": args.get("session")})
        out, base_ok = res.output, res.ok
    else:
        return ToolResult(False, f"Noma'lum method: {method}")
    passed, why = _check(out, args, base_ok)
    verdict = "PASS ✅" if passed else "FAIL ❌"
    evidence = out.strip()
    if len(evidence) > 3000:
        evidence = evidence[:3000] + "\n(... qisqartirildi)"
    return ToolResult(True, f"VERIFY {verdict}: {desc or method}{(' — ' + why) if why else ''}\n{evidence}",
                      host=host or target, verify_passed=passed)


def summary(args: dict) -> str:
    return f"{args.get('method')} {args.get('host') or ''} {args.get('target') or args.get('command') or ''}".strip()[:300]


SCHEMA = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "enum": METHODS},
        "description": {"type": "string", "description": "Nimani isbotlayapsan (masalan 'Spooler Running')."},
        "target": {"type": "string", "description": "ping: IP/host; tcp: host:port; service: xizmat nomi; http: URL."},
        "host": {"type": "string", "description": "service/powershell uchun Windows host; ssh uchun inventar nomi."},
        "command": {"type": "string", "description": "powershell/ssh uchun O'QISH buyrug'i."},
        "expect": {"type": "string", "description": "Natijada bo'lishi kerak bo'lgan matn."},
        "expect_regex": {"type": "string"},
        "expect_absent": {"type": "string", "description": "Natijada bo'lmasligi kerak bo'lgan matn."},
        "session": {"type": "string"},
        "timeout_sec": {"type": "integer"},
    },
    "required": ["method", "description"],
}

DESCRIPTION = (
    "O'zgartirishdan keyin natijani QAYTA o'lchaydi (self-verification). Faqat o'qish buyruqlari. PASS/FAIL va dalil "
    "qaytaradi. O'zgartiruvchi amaldan keyin verify PASS bo'lmasa, hisobot avtomatik 'TEKSHIRILMAGAN' deb belgilanadi."
)
