"""call_http_api — UniFi / Zabbix / NVR / ESXi / Mikrotik REST va boshqa HTTP API.

Egress nazorati: {{inv:NOM...}} faqat URL hosti shu yozuvga tegishli bo'lsa almashtiriladi;
{{secret:...}} faqat inventardagi hostlarga yuboriladi. Ma'lumot ichidan topilgan begona manzilga
maxfiy narsa ketmaydi.
"""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlparse

from .. import gate
from ..inventory import PlaceholderError, has_placeholders, placeholder_entries, SECRET_RE
from .base import ToolContext, ToolResult

_TEXT_FIELDS = ("url", "body")
_OBJ_FIELDS = ("json_body", "headers", "params")


def _url_host(url: str) -> str:
    host = urlparse(url or "").hostname
    if not host:
        raise PlaceholderError(f"URL noto'g'ri: {url!r} (http(s)://host/... ko'rinishida bo'lsin)")
    return host.lower()


def allowed_entries_for(ctx: ToolContext, url: str) -> set[str]:
    host = _url_host(url)
    return {n for n in ctx.inventory.names() if host in ctx.inventory.entry_hosts(n)}


def check_egress(ctx: ToolContext, args: dict) -> set[str]:
    """Maxfiy qiymat faqat o'z hostiga ketishini tekshiradi. Ruxsat etilgan yozuvlar to'plamini qaytaradi."""
    url = args.get("url", "")
    host = _url_host(url)
    allowed = allowed_entries_for(ctx, url)
    allowed_low = {a.lower() for a in allowed}
    texts = [str(args.get(f) or "") for f in _TEXT_FIELDS]
    texts += [json.dumps(args.get(f) or {}, ensure_ascii=False) for f in _OBJ_FIELDS]
    for ref in set().union(*(placeholder_entries(t) for t in texts)):
        found = ctx.inventory.get(ref)
        canon = found[0] if found else ref
        if canon.lower() not in allowed_low:
            raise PlaceholderError(
                f"'{canon}' maxfiy qiymati {host} ga yuborilmaydi: bu host '{canon}' yozuviga tegishli emas. "
                "Maxfiy qiymat faqat o'z hostiga ketadi."
            )
    if any(SECRET_RE.search(t) for t in texts) and host not in ctx.inventory.all_hosts():
        raise PlaceholderError(f"{{{{secret:...}}}} faqat inventardagi hostlarga yuboriladi ({host} inventarda yo'q).")
    auth_entry = args.get("auth_entry")
    if auth_entry:
        found = ctx.inventory.get(auth_entry)
        if not found or found[0].lower() not in allowed_low:
            raise PlaceholderError(f"auth_entry '{auth_entry}' ning hosti {host} emas — login boshqa hostga yuborilmaydi.")
    return allowed


def _resolve_obj(ctx: ToolContext, obj, allowed: set[str]):
    if isinstance(obj, str):
        return ctx.inventory.resolve(obj, allowed_entries=allowed)[0] if has_placeholders(obj) else obj
    if isinstance(obj, dict):
        return {k: _resolve_obj(ctx, v, allowed) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_obj(ctx, v, allowed) for v in obj]
    return obj


def _session(ctx: ToolContext, name: str):
    import requests
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    sess = ctx.http_sessions.get(name)
    if sess is None:
        sess = requests.Session()
        ctx.http_sessions[name] = sess
    return sess


def _format_response(resp) -> str:
    ctype = resp.headers.get("content-type", "")
    body = resp.text or ""
    if "json" in ctype:
        try:
            body = json.dumps(resp.json(), ensure_ascii=False, indent=1)
        except ValueError:
            pass
    loc = resp.headers.get("location")
    head = f"HTTP {resp.status_code} {resp.reason or ''} ({ctype or '?'}, {len(resp.content or b'')} bayt)"
    if loc:
        head += f"\nLocation: {loc}"
    return f"{head}\n{body.strip() or '(bo`sh javob)'}"


async def request(ctx: ToolContext, args: dict) -> ToolResult:
    import requests

    allowed = check_egress(ctx, args)
    method = (args.get("method") or "GET").upper()
    url = _resolve_obj(ctx, args["url"], allowed)
    host = _url_host(url)
    entry = None
    if allowed:
        found = ctx.inventory.get(sorted(allowed)[0])
        entry = found[1] if found else None
    verify = args.get("verify_tls")
    if verify is None:
        verify = str((entry or {}).get("verify_tls", "false")).lower() in {"1", "true", "yes"}
    kwargs: dict = {"timeout": max(3, min(int(args.get("timeout_sec") or 60), 600)), "verify": verify}
    if args.get("json_body") is not None:
        kwargs["json"] = _resolve_obj(ctx, args["json_body"], allowed)
    if args.get("body"):
        kwargs["data"] = _resolve_obj(ctx, args["body"], allowed).encode("utf-8")
    if args.get("headers"):
        kwargs["headers"] = _resolve_obj(ctx, args["headers"], allowed)
    if args.get("params"):
        kwargs["params"] = _resolve_obj(ctx, args["params"], allowed)
    if args.get("auth_entry"):
        _, auth = ctx.inventory.get(args["auth_entry"])
        user, pw = str(auth.get("username", "")), str(auth.get("password", ""))
        if (args.get("auth_type") or "basic").lower() == "digest":
            kwargs["auth"] = requests.auth.HTTPDigestAuth(user, pw)
        else:
            kwargs["auth"] = (user, pw)
    sess = _session(ctx, args.get("session") or f"_{host}")
    resp = await asyncio.to_thread(sess.request, method, url, **kwargs)
    # UniFi OS: keyingi so'rovlar uchun CSRF tokenni sessiyada saqlaymiz (modelga ko'rsatilmaydi).
    csrf = resp.headers.get("x-updated-csrf-token") or resp.headers.get("x-csrf-token")
    if csrf:
        sess.headers["X-CSRF-Token"] = csrf
    return ToolResult(ok=resp.status_code < 400, output=_format_response(resp), host=host,
                      meta={"status": resp.status_code})


def classify(ctx: ToolContext, args: dict) -> gate.Decision:
    check_egress(ctx, args)
    body_text = json.dumps(args.get("json_body"), ensure_ascii=False) if args.get("json_body") is not None else str(args.get("body") or "")
    return gate.classify_http(args.get("method", "GET"), args.get("url", ""), body_text,
                              args.get("system", "other"), _url_host(args.get("url", "")))


async def handler(ctx: ToolContext, args: dict) -> ToolResult:
    return await request(ctx, args)


def summary(args: dict) -> str:
    body = args.get("json_body")
    tail = f" {json.dumps(body, ensure_ascii=False)[:150]}" if body is not None else ""
    return f"{(args.get('method') or 'GET').upper()} {args.get('url', '')}{tail}"[:300]


SCHEMA = {
    "type": "object",
    "properties": {
        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]},
        "url": {"type": "string", "description": "To'liq URL, masalan https://10.0.0.5:8443/api/s/default/stat/device"},
        "system": {"type": "string", "enum": ["unifi", "zabbix", "esxi", "nvr", "mikrotik", "other"],
                   "description": "Qaysi tizim — xavfsizlik-gate shu bo'yicha baholaydi."},
        "json_body": {"type": "object", "description": "JSON tana. Parol o'rniga {{inv:NOM.password}}."},
        "body": {"type": "string", "description": "Xom matn tana (json_body o'rniga)."},
        "headers": {"type": "object"},
        "params": {"type": "object", "description": "Query parametrlar."},
        "auth_entry": {"type": "string", "description": "HTTP Basic/Digest uchun inventar nomi (login/parol shu yerdan)."},
        "auth_type": {"type": "string", "enum": ["basic", "digest"]},
        "session": {"type": "string", "description": "Cookie sessiya nomi (masalan 'unifi') — login'dan keyin shu nom bilan davom eting."},
        "verify_tls": {"type": "boolean", "description": "Standart: inventardagi verify_tls yoki false (ichki self-signed)."},
        "timeout_sec": {"type": "integer"},
        "purpose": {"type": "string", "description": "Nima uchun va qanday TA'SIR qiladi."},
    },
    "required": ["method", "url"],
}

DESCRIPTION = (
    "HTTP API chaqiruvi (UniFi controller, Zabbix JSON-RPC, NVR ISAPI, ESXi/vCenter REST, Mikrotik REST). "
    "Login uchun json_body ichida {{inv:NOM.username}} / {{inv:NOM.password}} yoki auth_entry ishlating — qiymat faqat "
    "o'sha yozuvning hostiga yuboriladi. session nomi bilan cookie saqlanadi. GET — o'qish; konfiguratsiyaga yozish va "
    "o'chirish kod tomonidan tasdiqqa yuboriladi."
)
