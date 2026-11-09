"""Tungi tadqiqot tool'lari (V26): topilma va reja bandini ideas.db ga yozish. Boshqa hech narsaga tegmaydi."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from .. import gate
from ..nightly import IdeasStore, load_config, night_of, tz_of
from .base import ToolContext, ToolResult

KIND_ENUM = ["github", "internet", "youtube"]


def _root(ctx: ToolContext) -> Path:
    return Path(ctx.paths.home) / "tadqiqot"


def _store_and_night(ctx: ToolContext) -> tuple[IdeasStore, str]:
    root = _root(ctx)
    cfg = load_config(root)
    return IdeasStore(root / "ideas.db"), night_of(datetime.now(timezone.utc), tz_of(cfg))


def classify_internal(ctx: ToolContext, args: dict) -> gate.Decision:
    return gate.Decision(host="localhost").escalate(gate.INTERNAL)


async def ideas_source(ctx: ToolContext, args: dict) -> ToolResult:
    url = str(args.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return ToolResult(False, "url http(s) bilan boshlanishi kerak")
    store, night = await asyncio.to_thread(_store_and_night, ctx)
    new = await asyncio.to_thread(store.add_finding, night, {**args, "url": url})
    n = len(store.findings(night))
    return ToolResult(True, ("Topilma saqlandi" if new else "Bu URL bugun allaqachon yozilgan") + f" (tun {night}, jami {n})")


async def ideas_plan(ctx: ToolContext, args: dict) -> ToolResult:
    if not str(args.get("title") or "").strip():
        return ToolResult(False, "title bo'sh")
    store, night = await asyncio.to_thread(_store_and_night, ctx)
    new = await asyncio.to_thread(store.add_plan, night, args)
    n = len(store.plan(night))
    return ToolResult(True, ("Reja bandi saqlandi" if new else "Bunday nomli band allaqachon bor") + f" (tun {night}, jami {n})")


async def ideas_list(ctx: ToolContext, args: dict) -> ToolResult:
    store, night = await asyncio.to_thread(_store_and_night, ctx)
    rows = store.findings(night)
    if not rows:
        return ToolResult(True, f"Tun {night}: topilma yo'q")
    return ToolResult(True, "\n".join(f"[{r['kind']}] ({r['relevance']}/5) {r['title']} — {r['url']}\n   {r['summary']}\n   g'oya: {r['idea']}"
                                      for r in rows)[:12000])


SOURCE_SCHEMA = {"type": "object", "required": ["kind", "url", "title", "summary"], "properties": {
    "kind": {"type": "string", "enum": KIND_ENUM}, "url": {"type": "string"}, "title": {"type": "string"},
    "summary": {"type": "string", "description": "2-4 jumla: nima, nima isbotlangan / nima taxmin"},
    "relevance": {"type": "integer", "description": "1-5: SENTINAL uchun foydasi"},
    "idea": {"type": "string", "description": "qanday funksiyaga aylanishi mumkin"},
    "last_update": {"type": "string", "description": "sahifada ko'ringan bo'lsa; bo'lmasa bo'sh (o'ylab topma)"},
    "license": {"type": "string", "description": "sahifada ko'ringan bo'lsa; bo'lmasa bo'sh"},
    "safety": {"type": "string", "description": "xavfsizlik izohi: nima tekshirildi va nima tekshirilmadi"}}}
SOURCE_DESCRIPTION = ("Tungi tadqiqot topilmasini yozish (GitHub loyiha, maqola, YouTube video). Faqat ideas.db ga yozadi. "
                      "Litsenziya va yangilanish sanasini O'YLAB TOPMA.")
PLAN_SCHEMA = {"type": "object", "required": ["title", "benefit", "description"], "properties": {
    "title": {"type": "string"}, "benefit": {"type": "string"}, "description": {"type": "string"},
    "effort": {"type": "string", "enum": ["S", "M", "L"]}, "risk": {"type": "string"}, "security": {"type": "string"},
    "tests": {"type": "string"}, "sources": {"type": "array", "items": {"type": "string"}},
    "priority": {"type": "integer", "description": "1 eng muhim ... 5"}}}
PLAN_DESCRIPTION = ("Yangi funksiya rejasi bandini yozish (Excel va Word hisobotga tushadi). Bu TAKLIF: amalga oshirish faqat "
                    "egasining tasdig'i bilan. Mavjud funksiyani takrorlama.")
LIST_SCHEMA = {"type": "object", "properties": {}}
LIST_DESCRIPTION = "Bugungi tunda yozilgan topilmalar ro'yxati (reja tuzish uchun)."
