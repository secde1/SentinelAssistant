"""reel_render, reel_list — Instagram Reels studiyasi (1-bosqich).

reel_render: skriptni tekshiradi -> ovoz -> video -> sifat nazorati -> egasiga Telegram'da tasdiq tugmalari bilan.
Joylash yo'q (2-bosqich): video faqat egasi tasdiqlagandan keyin va aynan o'sha versiya joylanadi.
"""
from __future__ import annotations

from .. import gate
from .base import ToolContext, ToolResult


def _internal(_ctx: ToolContext, _args: dict) -> gate.Decision:
    return gate.Decision(level=gate.INTERNAL)


def _store(ctx: ToolContext):
    from ..studio.store import StudioStore

    return StudioStore(ctx.paths.studio)


async def reel_render(ctx: ToolContext, args: dict) -> ToolResult:
    if not ctx.cfg.reels_enabled:
        return ToolResult(False, "Reels studiyasi o'chiq (REELS_ENABLED=0) — holat NEEDS_SETUP.")
    import imageio_ffmpeg

    from ..studio import pipeline

    store = _store(ctx)
    try:
        result = await pipeline.produce(store, ctx.cfg, imageio_ffmpeg.get_ffmpeg_exe(), args["script"],
                                        args.get("reel_id") or None)
    except pipeline.ScriptError as exc:
        return ToolResult(False, f"Skript qabul qilinmadi: {exc}. Tuzatib qayta chaqir.")
    if not result.ok:
        return ToolResult(False, f"{result.message} Holat: FAILED ({result.reel_id} v{result.version}).")
    short, details = pipeline.preview_texts(store, result.reel_id)
    await ctx.channel.send_video(result.video, short, pipeline.buttons(result.reel_id, result.version))
    await ctx.channel.send(details)
    engine = "Azure (rasmiy)" if result.engine == "azure" else "edge-tts (sinov)"
    return ToolResult(True, f"{result.message} Ovoz: {engine}. Egasiga tasdiqqa yuborildi — holat PENDING_APPROVAL. "
                            "Joylash egasining tasdig'isiz bo'lmaydi.")


async def reel_list(ctx: ToolContext, args: dict) -> ToolResult:
    from ..studio.store import STATE_LABELS

    store = _store(ctx)
    rows = store.recent(int(args.get("limit") or 20))
    state = (args.get("state") or "").upper()
    if state:
        rows = [r for r in rows if r["state"] == state]
    if not rows:
        return ToolResult(True, "Reels hali yo'q.")
    lines = [f"{r['id']} v{r['version']} {r['state']} ({STATE_LABELS.get(r['state'], '')}) — {r['topic']}"
             f" [{r['category'] or '-'}]" + (f" · sabab: {r['note']}" if r.get("note") else "")
             + (f" · vaqt: {r['scheduled_at']}" if r.get("scheduled_at") else "") for r in rows]
    return ToolResult(True, "\n".join(lines))


classify = _internal

RENDER_SCHEMA = {
    "type": "object",
    "properties": {
        "script": {
            "type": "object",
            "description": (
                "Reels skripti. Maydonlar: topic (qisqa mavzu), title, category (barqaror teg, masalan "
                "oila-muloqot, raqamli-qaramlik, kiberbulling), scenes — 4-8 ta {role, screen, narration}: role "
                "hook|problem|analysis|insight|solution|ending (birinchisi hook, oxirgisi ending); screen — ekrandagi "
                "qisqa katta matn (<=110 belgi); narration — ovoz matni (<=450 belgi). screen va narration O'ZBEK "
                "KIRILL yozuvida, emojisiz. caption (hashtaglarsiz), hashtags ['#...'] (3-10 ta tavsiya), sources "
                "[{title, url}] — kamida bitta ishonchli manba. Umumiy ovoz ~75-130 so'z (30-60 s)."),
        },
        "reel_id": {"type": "string", "description": "Mavjud videoni qayta ishlash uchun (masalan R1031-01). Yangi video — bo'sh."},
    },
    "required": ["script"],
}
LIST_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {"type": "string", "description": "Filtr: PENDING_APPROVAL, APPROVED, REJECTED, FAILED ..."},
        "limit": {"type": "integer"},
    },
}
