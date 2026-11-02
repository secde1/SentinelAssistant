"""Reels skripti: tuzilma tekshiruvi (kodda), kirill -> lotin (ovoz uchun) va gaplarga bo'lish (subtitr uchun).

Skript (agent yozadi, reel_render tool'iga JSON):
  topic, title, category, scenes[{role, screen, narration}], caption, hashtags[], sources[{title, url}]
Ekrandagi matn va subtitr — o'zbek KIRILL yozuvida (egasi qarori). O'zbekcha TTS ovozi kirillni o'qiy olmaydi,
shuning uchun ovozga matn kod tomonidan lotinga o'giriladi.
"""
from __future__ import annotations

import re

ROLES = ("hook", "problem", "analysis", "insight", "solution", "ending")
ROLE_LABELS = {"hook": "", "problem": "МУАММО", "analysis": "ТАҲЛИЛ", "insight": "ХУЛОСА", "solution": "ЕЧИМ",
               "ending": "СИЗНИНГ ФИКРИНГИЗ"}

MAX_SCREEN = 110          # ekrandagi katta matn (belgi)
MAX_NARRATION = 450       # bitta sahna ovozi (belgi)
MAX_CAPTION = 2200        # Instagram caption chegarasi (hashtaglar bilan)
MAX_HASHTAGS = 30         # Instagram chegarasi
MIN_CYRILLIC_SHARE = 0.6  # harflarning kamida 60% kirill bo'lsin

_CYR_LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "'", "ы": "i", "ь": "", "э": "e",
    "ю": "yu", "я": "ya", "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h",
}
_VOWELS = set("аеёиоуэюяў")


def to_latin(text: str) -> str:
    """O'zbek kirill -> lotin. 'е' so'z boshida, unli yoki ъ/ь dan keyin 'ye' bo'ladi."""
    out: list[str] = []
    prev = ""
    for ch in text:
        low = ch.lower()
        if low == "е":
            lat = "ye" if (not prev.isalpha() or prev in _VOWELS or prev in "ъь") else "e"
        elif low in _CYR_LAT:
            lat = _CYR_LAT[low]
        else:
            out.append(ch)
            prev = low
            continue
        if ch != low and lat:
            lat = lat[0].upper() + lat[1:]
        out.append(lat)
        prev = low
    return "".join(out)


def split_sentences(text: str, limit: int = 110) -> list[str]:
    """Subtitr bo'laklari: gaplar, juda uzun gap esa vergul/oraliq bo'yicha bo'linadi."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?…])\s+", " ".join(text.split())) if p.strip()]
    chunks: list[str] = []
    for part in parts:
        while len(part) > limit:
            cut = max(part.rfind(", ", 0, limit), part.rfind(" — ", 0, limit))
            if cut < limit // 3:
                cut = part.rfind(" ", 0, limit)
            if cut <= 0:
                break
            chunks.append(part[:cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            chunks.append(part)
    return chunks


def cyrillic_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    return sum(1 for c in letters if "Ѐ" <= c <= "ӿ") / len(letters)


def validate(script: dict) -> list[str]:
    """Xatolar ro'yxati (bo'sh — skript to'g'ri)."""
    errors: list[str] = []
    if not isinstance(script, dict):
        return ["skript JSON obyekt bo'lishi kerak"]
    for key in ("topic", "title", "caption"):
        if not str(script.get(key) or "").strip():
            errors.append(f"'{key}' bo'sh")
    scenes = script.get("scenes")
    if not isinstance(scenes, list) or not 4 <= len(scenes) <= 8:
        errors.append("scenes: 4-8 ta sahna kerak (hook ... ending)")
        scenes = scenes if isinstance(scenes, list) else []
    for i, sc in enumerate(scenes, 1):
        if not isinstance(sc, dict):
            errors.append(f"sahna {i}: obyekt emas")
            continue
        role, screen, narration = sc.get("role"), str(sc.get("screen") or ""), str(sc.get("narration") or "")
        if role not in ROLES:
            errors.append(f"sahna {i}: role '{role}' noto'g'ri ({', '.join(ROLES)})")
        if not screen.strip() or len(screen) > MAX_SCREEN:
            errors.append(f"sahna {i}: screen bo'sh yoki {MAX_SCREEN} belgidan uzun")
        if not narration.strip() or len(narration) > MAX_NARRATION:
            errors.append(f"sahna {i}: narration bo'sh yoki {MAX_NARRATION} belgidan uzun")
        for name, val in (("screen", screen), ("narration", narration)):
            if val.strip() and cyrillic_share(val) < MIN_CYRILLIC_SHARE:
                errors.append(f"sahna {i}: {name} o'zbek KIRILL yozuvida bo'lishi kerak")
    if scenes and isinstance(scenes[0], dict) and scenes[0].get("role") != "hook":
        errors.append("birinchi sahna 'hook' bo'lishi kerak")
    if scenes and isinstance(scenes[-1], dict) and scenes[-1].get("role") != "ending":
        errors.append("oxirgi sahna 'ending' bo'lishi kerak")
    hashtags = script.get("hashtags") or []
    if not isinstance(hashtags, list) or len(hashtags) > MAX_HASHTAGS or \
            any(not str(h).startswith("#") or " " in str(h) for h in hashtags):
        errors.append(f"hashtags: '#' bilan boshlanadigan, probelsiz, {MAX_HASHTAGS} tagacha ro'yxat")
    full_caption = full_caption_text(script)
    if len(full_caption) > MAX_CAPTION:
        errors.append(f"caption hashtaglar bilan {len(full_caption)} belgi — {MAX_CAPTION} dan oshmasin")
    sources = script.get("sources") or []
    if not isinstance(sources, list) or not sources or \
            any(not isinstance(s, dict) or not re.match(r"https?://", str(s.get("url", ""))) for s in sources):
        errors.append("sources: kamida bitta manba [{title, url (http...)}] — faktsiz video tayyorlanmaydi")
    return errors


def full_caption_text(script: dict) -> str:
    tags = " ".join(str(h) for h in (script.get("hashtags") or []))
    return (str(script.get("caption") or "").strip() + ("\n\n" + tags if tags else "")).strip()
