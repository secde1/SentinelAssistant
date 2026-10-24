"""write_skill, remember, log_history — o'rganilgan bilim (GitHubga tushadi, shuning uchun redaction majburiy)."""
from __future__ import annotations

import re
from datetime import datetime

from .. import gate
from ..memory import parse_frontmatter
from .base import ToolContext, ToolResult


def _slug(name: str) -> str:
    s = re.sub(r"[ʻʼ’‘`']", "", name.lower())
    s = re.sub(r"[^a-z0-9а-яё]+", "-", s).strip("-")
    return s[:60] or "skill"


def _internal(_ctx: ToolContext, _args: dict) -> gate.Decision:
    return gate.Decision(level=gate.INTERNAL)


def _clean(ctx: ToolContext, text: str) -> tuple[str, bool]:
    red = ctx.redactor.redact(text or "")
    return red, red != (text or "")


# ---------------------------------------------------------------- write_skill
async def write_skill(ctx: ToolContext, args: dict) -> ToolResult:
    name = " ".join(str(args["name"]).split())
    steps, hidden1 = _clean(ctx, args["steps"])
    desc, hidden2 = _clean(ctx, " ".join(str(args["description"]).split()))
    triggers, hidden3 = _clean(ctx, str(args.get("triggers", "")))
    if len(steps.strip()) < 40:
        return ToolResult(False, "steps juda qisqa — HAQIQATAN ishlagan buyruqlar bilan aniq qadamlar yozing.")
    slug = _slug(name)
    folder = ctx.paths.skill / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    today = datetime.now().strftime("%Y-%m-%d")
    created, version = today, 1
    if path.exists():
        old = path.read_text(encoding="utf-8", errors="ignore")
        meta, _ = parse_frontmatter(old)
        created = meta.get("yaratilgan", today)
        try:
            version = int(meta.get("versiya", "1")) + 1
        except ValueError:
            version = 2
        (folder / "SKILL.prev.md").write_text(old, encoding="utf-8")
    body = (
        f"---\nname: {slug}\ndescription: {desc}\ntriggers: {triggers}\n"
        f"yaratilgan: {created}\nyangilangan: {today}\nversiya: {version}\n---\n\n"
        f"# {name}\n\n{steps.strip()}\n"
    )
    path.write_text(body, encoding="utf-8")
    ctx.skill_written = True
    ctx.journal.event("skill", f"Skill yozildi: {slug} (v{version})", task=ctx.task_id, skill=slug, version=version)
    note = " Maxfiy qiymatlar *** bilan yashirildi — skillda faqat placeholder ishlating." if (hidden1 or hidden2 or hidden3) else ""
    return ToolResult(True, f"Skill saqlandi: {path} (versiya {version}).{note}")


# ---------------------------------------------------------------- remember
MEMORY_TARGETS = {"fakt": "fakt.md", "boshliq": "boshliq.md", "inventar": "inventar.md",
                  "prompt_qoshimcha": "prompt_qoshimcha.md"}


async def remember(ctx: ToolContext, args: dict) -> ToolResult:
    target = MEMORY_TARGETS[args["file"]]
    text, hidden = _clean(ctx, " ".join(str(args["text"]).split()))
    path = ctx.paths.xotira / target
    existing = path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""
    if text.lower() in existing.lower():
        return ToolResult(True, f"Bu ma'lumot {target} da allaqachon bor — takror yozilmadi.")
    section = args.get("section")
    line = f"- [{datetime.now():%Y-%m-%d}] {text}\n"
    if section and f"## {section}" in existing:
        idx = existing.index(f"## {section}") + len(f"## {section}")
        nl = existing.find("\n", idx)
        nl = len(existing) if nl == -1 else nl + 1
        existing = existing[:nl] + line + existing[nl:]
        path.write_text(existing, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as f:
            if section:
                f.write(f"\n## {section}\n")
            elif existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line)
    note = " Maxfiy qiymat *** bilan yashirildi." if hidden else ""
    return ToolResult(True, f"{target} ga yozildi.{note}")


# ---------------------------------------------------------------- log_history
async def log_history(ctx: ToolContext, args: dict) -> ToolResult:
    fields = {k: _clean(ctx, " ".join(str(args.get(k, "")).split()))[0]
              for k in ("kategoriya", "sarlavha", "belgi", "sabab", "tuzatish", "natija", "saboq")}
    kategoriya = _slug(fields["kategoriya"] or "boshqa")
    if ctx.mutations:
        status = "tasdiqlangan" if ctx.verified_after_mutation and ctx.last_verify_ok else "tekshirilmagan"
    else:
        status = "o'zgartirish bo'lmagan"
    entry = (
        f"\n## {datetime.now():%Y-%m-%d %H:%M} | {fields['sarlavha'] or kategoriya}\n"
        f"- Kategoriya: {kategoriya}\n- Belgi: {fields['belgi']}\n- Sabab: {fields['sabab']}\n"
        f"- Tuzatish: {fields['tuzatish']}\n- Natija: {fields['natija']} ({status})\n"
    )
    if fields["saboq"]:
        entry += f"- Saboq: {fields['saboq']}\n"
    entry += f"- Topshiriq: {ctx.task_id}\n"
    with (ctx.paths.xotira / "tarix.md").open("a", encoding="utf-8") as f:
        f.write(entry)
    ctx.history_logged = True
    ctx.journal.event("history", f"Tarix: {kategoriya} — {fields['sarlavha']}", task=ctx.task_id,
                      kategoriya=kategoriya, sarlavha=fields["sarlavha"], saboq=fields["saboq"], holat=status)
    return ToolResult(True, f"tarix.md ga yozildi (kategoriya: {kategoriya}, holat: {status}).")


classify = _internal

SKILL_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Qisqa nom, masalan 'unifi-ap-adopt'."},
        "description": {"type": "string", "description": "Bir jumla: qachon ishlatiladi."},
        "steps": {"type": "string", "description": "Markdown: HAQIQATAN ishlagan buyruqlar bilan aniq qadamlar, tekshiruv usuli, "
                                                   "tipik xatolar. Parol o'rniga {{inv:NOM.password}} yoki 'inventar.json dan oladi'."},
        "triggers": {"type": "string", "description": "Vergul bilan kalit so'zlar (uz/ru/en): unifi, adopt, controller..."},
    },
    "required": ["name", "description", "steps"],
}
REMEMBER_SCHEMA = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "enum": list(MEMORY_TARGETS),
                 "description": "fakt=doimiy fakt; boshliq=Jamshid uslubi/qoidasi; inventar=host/IP/VM (parolsiz); "
                                "prompt_qoshimcha=o'z ish uslubingga qo'shimcha qoida."},
        "text": {"type": "string"},
        "section": {"type": "string", "description": "Ixtiyoriy '## bo'lim' nomi (masalan 'Mikrotik', 'Printerlar')."},
    },
    "required": ["file", "text"],
}
HISTORY_SCHEMA = {
    "type": "object",
    "properties": {
        "kategoriya": {"type": "string", "description": "Qisqa barqaror teg (haftalik statistika shundan): unifi-adopt, "
                                                        "printer-navbat, abonent-tezlik, disk-joy, ad-blok..."},
        "sarlavha": {"type": "string"},
        "belgi": {"type": "string"},
        "sabab": {"type": "string"},
        "tuzatish": {"type": "string"},
        "natija": {"type": "string", "description": "O'lchangan dalil bilan."},
        "saboq": {"type": "string", "description": "Kuchayish sikli: nimani bilmay qoldim / nima ortiqcha edi / nimani avtomatlashtirsa bo'ladi."},
    },
    "required": ["kategoriya", "sarlavha", "belgi", "sabab", "tuzatish", "natija"],
}
