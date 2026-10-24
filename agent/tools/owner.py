"""Jamshid bilan muloqot va inventar: ask_owner, notify_owner, request_credentials, inventory_set,
list_inventory, generate_secret."""
from __future__ import annotations

import json
import re

from .. import gate
from ..inventory import normalize_type
from ..redact import MASK, is_secret_key
from .base import ToolContext, ToolResult

KNOWN_FIELDS = {"host", "username", "password", "port", "type", "url", "token", "api_key", "enable_secret",
                "community", "key_file", "auth", "ssl", "verify_tls", "description"}


def _internal(_ctx: ToolContext, _args: dict) -> gate.Decision:
    return gate.Decision(level=gate.INTERNAL)


def parse_credential_reply(text: str, fields: list[str]) -> dict:
    """'kalit: qiymat' qatorlari; kalitsiz qatorlar yetishmayotgan maydonlarga tartib bo'yicha."""
    wanted = {f.lower(): f for f in fields}
    result: dict = {}
    free: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*[:=]\s*(.+)$", line)
        key = m.group(1).lower() if m else ""
        if m and (key in wanted or key in KNOWN_FIELDS):
            result[wanted.get(key, key)] = m.group(2).strip()
        else:
            free.append(line)
    for field, value in zip([f for f in fields if f not in result], free):
        result[field] = value
    return result


# ---------------------------------------------------------------- ask / notify
async def ask_owner(ctx: ToolContext, args: dict) -> ToolResult:
    if ctx.questions_asked >= ctx.cfg.max_questions_per_task:
        return ToolResult(False, f"Bu topshiriqda savol limiti ({ctx.cfg.max_questions_per_task}) tugadi. Eng oqilona "
                                 "va xavfsiz variant bilan davom et yoki hisobotda aniq nima kerakligini yoz.")
    ctx.questions_asked += 1
    answer = await ctx.channel.ask(ctx.redactor.redact(args["question"]))
    if answer is None:
        return ToolResult(True, "Javob kelmadi (timeout). Xavfsiz variant bilan davom et; tasdiq talab qiladigan "
                                "ishni BAJARMA.")
    return ToolResult(True, f"Jamshid javobi: {answer}")


async def notify_owner(ctx: ToolContext, args: dict) -> ToolResult:
    text = ctx.redactor.redact(args.get("text", ""))
    if args.get("file_path"):
        path = ctx.resolve_path(args["file_path"])
        if gate.classify_file_read(path, ctx.secret_paths).level == gate.BLOCK:
            return ToolResult(False, "maxfiy papkadagi faylni yuborib bo'lmaydi")
        if not path.is_file():
            return ToolResult(False, f"Fayl topilmadi: {path}")
        await ctx.channel.send_file(path, text)
        return ToolResult(True, f"Fayl yuborildi: {path.name}")
    if not text.strip():
        return ToolResult(False, "text bo'sh")
    await ctx.channel.send(text)
    return ToolResult(True, "Yuborildi.")


# ---------------------------------------------------------------- inventar
async def request_credentials(ctx: ToolContext, args: dict) -> ToolResult:
    name = args["name"].strip()
    fields = [f.strip() for f in args.get("fields") or ["host", "username", "password"] if f.strip()]
    known = {k: v for k, v in (args.get("known") or {}).items() if not is_secret_key(k)}
    if known:
        ctx.inventory.set_fields(name, known)
    missing = ctx.inventory.missing(name, fields)
    if not missing:
        return ToolResult(True, f"'{name}' uchun {', '.join(fields)} allaqachon inventarda bor — qayta so'ralmadi. "
                                f"Placeholder: {{{{inv:{name}.password}}}}")
    lines = [f"🔐 '{name}' uchun ma'lumot kerak" + (f" — {args['reason']}" if args.get("reason") else "") + ".",
             "Keyingi xabaringizni shu ko'rinishda yuboring (har biri alohida qatorda):"]
    lines += [f"{f}: ..." for f in missing]
    lines.append("Xabar modelga BERILMAYDI: faqat maxfiy/inventar.json ga yoziladi va chatdan o'chiriladi. Bekor: /bekor")
    reply = await ctx.channel.request_secret("\n".join(lines))
    if reply is None:
        return ToolResult(False, "Ma'lumot kelmadi (bekor yoki timeout). Usiz davom etib bo'lmasa — hisobotda ayt.")
    parsed = parse_credential_reply(reply, missing)
    if "type" in parsed:
        parsed["type"] = normalize_type(parsed["type"])
    if "port" in parsed and str(parsed["port"]).isdigit():
        parsed["port"] = int(parsed["port"])
    ctx.inventory.set_fields(name, parsed)
    still = ctx.inventory.missing(name, fields)
    shown = ", ".join(f"{k}={MASK if is_secret_key(k) else v}" for k, v in parsed.items())
    ctx.journal.event("credentials", f"Inventar yangilandi: {name} ({', '.join(parsed)})", task=ctx.task_id,
                      name=name, fields=list(parsed))
    msg = f"Saqlandi: {name} ({shown})."
    if still:
        msg += f" Hali yetishmaydi: {', '.join(still)}."
    return ToolResult(not still, msg + f" Endi placeholder ishlating: {{{{inv:{name}.<maydon>}}}}")


async def inventory_set(ctx: ToolContext, args: dict) -> ToolResult:
    fields = args.get("fields") or {}
    secret = [k for k in fields if is_secret_key(k)]
    if secret:
        return ToolResult(False, f"Maxfiy maydon ({', '.join(secret)}) bu yerda yozilmaydi — request_credentials ishlating.")
    entry = ctx.inventory.set_fields(args["name"], fields)
    public = {k: (MASK if is_secret_key(k) else v) for k, v in entry.items()}
    return ToolResult(True, f"Inventar: {args['name']} = {json.dumps(public, ensure_ascii=False)}")


async def list_inventory(ctx: ToolContext, args: dict) -> ToolResult:
    view = ctx.inventory.public_view()
    gen = ctx.inventory.generated_names()
    out = json.dumps(view, ensure_ascii=False, indent=1) if view else "Inventar bo'sh."
    if gen:
        out += f"\nYaratilgan parollar ({{{{secret:NOM}}}}): {', '.join(gen)}"
    return ToolResult(True, out)


async def generate_secret(ctx: ToolContext, args: dict) -> ToolResult:
    name = re.sub(r"[^A-Za-z0-9_.\-]", "_", args["name"])
    ctx.inventory.generate_secret(name, int(args.get("length") or 16), args.get("note", ""))
    return ToolResult(True, f"Parol yaratildi va maxfiy/inventar.json ga saqlandi. Buyruqda {{{{secret:{name}}}}} deb "
                            f"ishlating. Jamshid uni Telegramda '/parol {name}' bilan o'zi ko'radi — sen parolni ko'rmaysan "
                            "va hisobotga yozmaysan.")


async def send_business_message(ctx: ToolContext, args: dict) -> ToolResult:
    """Jamshidning Business hisobidagi suhbatga uning nomidan xabar yuboradi (tasdiqdan keyin)."""
    import httpx
    from ..business import BusinessStore
    store = BusinessStore(ctx.paths.ish / "business.json")
    query = str(args.get("chat") or "").strip()
    chats = store.chats()
    if not query:
        if not chats:
            return ToolResult(True, "Hali Business suhbat ko'rilmagan. Suhbatdosh botga ulangan chatda yozishi kerak.")
        return ToolResult(True, "Ma'lum suhbatlar: " + json.dumps(chats, ensure_ascii=False))
    found = store.find(query)
    if len(found) != 1:
        return ToolResult(False, f"'{query}' bo'yicha {len(found)} ta suhbat topildi. Ma'lum: " + json.dumps(chats, ensure_ascii=False))
    cid, info = found[0]
    text = str(args.get("text") or "").strip()
    if not text:
        return ToolResult(False, "text bo'sh")
    url = f"https://api.telegram.org/bot{ctx.cfg.telegram_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=30) as cl:
            r = await cl.post(url, json={"business_connection_id": info["connection_id"], "chat_id": int(cid), "text": text})
            data = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        return ToolResult(False, f"tarmoq xatosi ({type(exc).__name__})")
    if data.get("ok"):
        return ToolResult(True, f"Yuborildi: {info.get('name') or cid} (message_id={data['result'].get('message_id')})")
    return ToolResult(False, f"Telegram rad etdi: {data.get('error_code')} {data.get('description')}")


def classify_business_send(_ctx: ToolContext, args: dict) -> gate.Decision:
    d = gate.Decision(level=gate.INTERNAL)
    if args.get("chat"):
        d.escalate(gate.DANGER, "Jamshid nomidan uchinchi shaxsga xabar yuboriladi", "business_send")
    return d


classify = _internal

BUSINESS_SEND_SCHEMA = {"type": "object", "properties": {
    "chat": {"type": "string", "description": "Suhbat ID, username yoki ismi. Bo'sh qoldirilsa — ma'lum suhbatlar ro'yxati."},
    "text": {"type": "string", "description": "Yuboriladigan matn (aynan shu holda ketadi)."}}}

ASK_SCHEMA = {"type": "object", "properties": {"question": {"type": "string", "description": "BITTA eng muhim savol."}},
              "required": ["question"]}
NOTIFY_SCHEMA = {"type": "object", "properties": {
    "text": {"type": "string"}, "file_path": {"type": "string", "description": "Ixtiyoriy: yuboriladigan fayl (hisobot, jadval)."}},
    "required": ["text"]}
CRED_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "description": "Inventar nomi, masalan 'mikrotik-asosiy', 'unifi-controller', 'srv-file01'."},
    "fields": {"type": "array", "items": {"type": "string"}, "description": "Kerakli maydonlar: host, username, password, port, token..."},
    "known": {"type": "object", "description": "Ma'lum bo'lgan maxfiy BO'LMAGAN qiymatlar: type, host, port, url."},
    "reason": {"type": "string"}},
    "required": ["name", "fields"]}
INV_SET_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string"},
    "fields": {"type": "object", "description": "Maxfiy bo'lmagan maydonlar: host, type, port, url, verify_tls, auth, ssl, description."}},
    "required": ["name", "fields"]}
LIST_SCHEMA = {"type": "object", "properties": {}}
GEN_SCHEMA = {"type": "object", "properties": {
    "name": {"type": "string", "description": "Masalan 'ad-ivanov-yangi'."},
    "length": {"type": "integer"}, "note": {"type": "string"}},
    "required": ["name"]}
