"""Reels ishlab chiqarish: skript -> TTS -> render -> sifat nazorati -> PENDING_APPROVAL (har qadam bazada)."""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from . import render as rnd
from . import script as scr
from . import tts
from .store import TRANSITIONS, StudioStore

log = logging.getLogger(__name__)

TARGET_MIN, TARGET_MAX = 30, 60  # tavsiya etilgan davomiylik (s); sifat nazorati 20..90 ni qabul qiladi
SCENE_LEAD = 0.2                 # yangi sahna tasviri ovozdan shuncha oldin chiqadi
# Statistika hali yo'q: joylash oynalari navbat bilan sinaladi (V5: "experimental schedule"). 3-bosqichda Instagram
# Insights ma'lumoti bilan almashtiriladi.
EXPERIMENT_SLOTS = ("08:30", "12:30", "19:00", "21:30")


class ScriptError(Exception):
    pass


@dataclass
class Result:
    reel_id: str
    version: int
    ok: bool
    message: str
    video: Path | None = None
    duration: float = 0.0
    engine: str = ""
    sha256: str = ""


def _prepare_reel(store: StudioStore, script: dict, reel_id: str | None) -> str:
    if not reel_id:
        return store.create(script["topic"], script.get("category", ""), script["title"])
    reel = store.get(reel_id)
    if reel is None:
        raise ScriptError(f"{reel_id} topilmadi")
    if reel["state"] in ("PENDING_APPROVAL", "APPROVED", "SCHEDULED"):
        store.transition(reel_id, "REVISION_REQUESTED", "agent", "yangi versiya — qayta tasdiq kerak")
    elif reel["state"] not in ("REVISION_REQUESTED", "FAILED"):
        raise ScriptError(f"{reel_id} holati {reel['state']} — qayta ishlab bo'lmaydi")
    return reel_id


def scene_timeline(script: dict, clips: list[tts.Clip], duration: float) -> list[rnd.Scene]:
    scenes = []
    for i, sc in enumerate(script["scenes"]):
        subs = [rnd.SubLine(c.text_screen, c.start, c.end) for c in clips if c.scene == i]
        scenes.append(rnd.Scene(sc["role"], sc["screen"], 0.0, 0.0, subs))
    for i, sc in enumerate(scenes):
        sc.start = 0.0 if i == 0 else max(0.0, sc.subs[0].start - SCENE_LEAD)
    for i, sc in enumerate(scenes):
        sc.end = scenes[i + 1].start if i + 1 < len(scenes) else duration
    return scenes


async def produce(store: StudioStore, cfg, ffmpeg: str, script: dict, reel_id: str | None = None) -> Result:
    errors = scr.validate(script)
    if errors:
        raise ScriptError("; ".join(errors))
    rid = _prepare_reel(store, script, reel_id)
    version = store.start_version(rid, script)
    store.transition(rid, "SCRIPT_READY", "agent", f"v{version}")
    work = store.root / rid
    work.mkdir(parents=True, exist_ok=True)
    temp: list[Path] = []
    try:
        store.transition(rid, "VIDEO_RENDERING", "kod", "")
        engine = tts.pick_engine(cfg.reels_tts, cfg.azure_speech_key)
        clips: list[tts.Clip] = []
        audio = []
        for si, scene in enumerate(script["scenes"]):
            for sentence in scr.split_sentences(scene["narration"]):
                mp3 = work / f"v{version}_{len(clips):02d}.mp3"
                temp.append(mp3)
                await tts.synth(scr.to_latin(sentence), mp3, engine, cfg.reels_voice, cfg.reels_rate,
                                cfg.azure_speech_key, cfg.azure_speech_region)
                audio.append(await asyncio.to_thread(tts.decode, mp3))
                clips.append(tts.Clip(scene=si, text_screen=sentence))
        track, duration = tts.build_track(clips, audio)
        wav = work / f"v{version}.wav"
        temp.append(wav)
        tts.write_wav(track, wav)
        video = work / f"{rid}_v{version}.mp4"
        font = rnd.find_font(cfg.reels_font)
        await asyncio.to_thread(rnd.render, scene_timeline(script, clips, duration), duration, wav, video, ffmpeg,
                                font, cfg.reels_brand)
        store.transition(rid, "QUALITY_CHECK", "kod", "")
        qc = await asyncio.to_thread(rnd.probe, video, ffmpeg)
        if not qc.ok:
            store.transition(rid, "FAILED", "kod", "; ".join(qc.problems))
            hint = " Skriptni qisqartiring yoki uzaytiring." if any("davomiylik" in p for p in qc.problems) else ""
            return Result(rid, version, False, f"Sifat nazorati o'tmadi: {'; '.join(qc.problems)}.{hint}", video,
                          qc.duration, engine)
        digest = store.finish_version(rid, version, video, qc.duration, engine)
        store.transition(rid, "PENDING_APPROVAL", "kod", f"{qc.duration:.1f} s, {qc.size_mb:.1f} MB, sha256={digest[:16]}")
        note = ""
        if not TARGET_MIN <= qc.duration <= TARGET_MAX:
            note = f" Davomiylik {qc.duration:.0f} s — tavsiya {TARGET_MIN}-{TARGET_MAX} s."
        return Result(rid, version, True, f"{rid} v{version} tayyor ({qc.duration:.1f} s).{note}", video, qc.duration,
                      engine, digest)
    except Exception as exc:
        reel = store.get(rid)
        if reel and "FAILED" in TRANSITIONS.get(reel["state"], set()):
            store.transition(rid, "FAILED", "kod", f"{type(exc).__name__}: {exc}"[:300])
        raise
    finally:
        for p in temp:
            p.unlink(missing_ok=True)


# --------------------------------------------------------------------- egasi bilan muloqot matnlari
def preview_texts(store: StudioStore, rid: str) -> tuple[str, str]:
    """(video ostidagi qisqa yozuv, alohida batafsil xabar)."""
    reel, ver = store.get(rid), store.version(rid)
    script = ver["script"]
    warn = "" if ver["tts_engine"] == "azure" else (
        "\n⚠️ Ovoz: edge-tts (sinov). Ochiq e'lon uchun rasmiy Azure Speech kaliti tavsiya etiladi.")
    short = (f"🎬 {rid} · v{ver['version']} — {script['title']}\n"
             f"⏱ {ver['duration']:.0f} s · tasdiq kutmoqda{warn}")[:1000]
    sources = "\n".join(f"{i}. {s.get('title', '').strip() or s['url']} — {s['url']}"
                        for i, s in enumerate(script.get("sources", []), 1))
    when = (f"🕒 Belgilangan vaqt: {reel['scheduled_at']}" if reel.get("scheduled_at") else
            f"🕒 Tavsiya etilgan vaqt: {suggest_slot(rid)} (tajriba — joylash statistikasi hali yo'q, oynalar "
            "navbat bilan sinaladi)")
    details = (f"📝 {rid} — Instagram caption:\n{scr.full_caption_text(script)}\n\n"
               f"📚 Manbalar:\n{sources}\n\n{when}\n\n"
               "Instagram hali ulanmagan: tasdiqlangan video navbatda saqlanadi va 2-bosqichda aynan shu "
               "versiya joylanadi.")
    return short, details


def suggest_slot(rid: str) -> str:
    """Tajribaviy joylash oynasi: kun va tartib raqami bo'yicha navbat (bir xil vaqtga yopishib qolmaslik uchun)."""
    m = re.match(r"R(\d{2})(\d{2})-(\d+)$", rid)
    if not m:
        return EXPERIMENT_SLOTS[0]
    day = int(m.group(1)) * 31 + int(m.group(2))
    return EXPERIMENT_SLOTS[(day * 2 + int(m.group(3)) - 1) % len(EXPERIMENT_SLOTS)]


def revision_prompt(store: StudioStore, rid: str, feedback: str) -> str:
    import json

    ver = store.version(rid)
    return (f"Instagram Reels {rid} (v{ver['version']}) ni egasining fikri bo'yicha qayta ishla va "
            f"reel_render(reel_id='{rid}', script=...) bilan YANGI versiyani yasa (u qayta tasdiqqa yuboriladi).\n"
            f"Egasining fikri: {feedback}\n"
            f"Joriy skript (JSON):\n{json.dumps(ver['script'], ensure_ascii=False)}")


def status_report(store: StudioStore, per_day: int, limit: int = 10) -> str:
    rows = store.recent(limit)
    paused = store.setting("paused") == "1"
    from .store import STATE_LABELS

    head = (f"🎬 Reels: bugun {store.count_today()}/{per_day} tayyorlangan"
            f"{' · ⏸ kunlik tayyorlash PAUZADA' if paused else ''}")
    if not rows:
        return head + "\nHali video yo'q. /reels_tayyorla — hozir tayyorlash."
    lines = [f"• {r['id']} · v{r['version']} · {STATE_LABELS.get(r['state'], r['state'])} — {r['topic']}"
             + (f" · 🕒 {r['scheduled_at']}" if r.get("scheduled_at") else "") for r in rows]
    return head + "\n" + "\n".join(lines)


def buttons(rid: str, version: int) -> dict:
    cb = f"rl:{rid}:{version}:"
    return {"inline_keyboard": [
        [{"text": "✅ Tasdiqlash", "callback_data": cb + "ok"}, {"text": "✏️ Qayta ishlash", "callback_data": cb + "rev"}],
        [{"text": "❌ Rad etish", "callback_data": cb + "rej"}, {"text": "🕒 Vaqt", "callback_data": cb + "time"}],
    ]}


def parse_when(text: str, now: datetime | None = None) -> datetime | None:
    """'19:30', 'ertaga 19:30' / 'завтра 19:30', '31.10 19:30' -> kelajakdagi vaqt; tushunarsiz bo'lsa None."""
    now = now or datetime.now()
    t = text.strip().lower()
    m = re.search(r"(\d{1,2})[:.](\d{2})\s*$", t)
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh < 24 and 0 <= mm < 60):
        return None
    d = re.match(r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s+", t)
    if d:
        try:
            when = datetime(int(d.group(3) or now.year), int(d.group(2)), int(d.group(1)), hh, mm)
        except ValueError:
            return None
        return when if when > now else None
    when = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if any(w in t for w in ("ertaga", "эртага", "завтра")):
        when += timedelta(days=1)
    elif when <= now:
        when += timedelta(days=1)
    return when


def daily_prompt(store: StudioStore, count: int) -> str:
    """Kunlik topshiriq matni: nechta video, oxirgi mavzular (takrorlanmasin), rad etilganlar (sababi bilan)."""
    recent = store.recent(40)
    done = [f"- {r['topic']} ({r['state']})" for r in recent if r["state"] != "REJECTED"][:20]
    rejected = [f"- {r['topic']}" + (f" — sabab: {r['note']}" if r.get("note") else "")
                for r in recent if r["state"] == "REJECTED"][:10]
    return (f"Bugun {count} ta Instagram Reels tayyorla (STUDIYA qoidalari bo'yicha). Har biri uchun: WebSearch bilan "
            "dolzarb va ishonchli manbalarni top, faktlarni tekshir, o'zbek KIRILL yozuvida skript yoz va reel_render "
            "bilan videoni yasa. Har video egasiga tasdiqqa o'zi yuboriladi.\n"
            "Oxirgi mavzular (takrorlama):\n" + ("\n".join(done) or "- hali yo'q") +
            "\nRad etilgan mavzular (shunga o'xshashini qilma):\n" + ("\n".join(rejected) or "- yo'q"))
