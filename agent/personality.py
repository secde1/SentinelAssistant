"""Shaxsiyat sozlamalari (shaxsiyat.json): ohang darajalari 0-100 -> tizim promptiga aniq ko'rsatmalar.

Darajalar faqat OHANGni belgilaydi; SHAXSIYAT.md dagi taqiqlar, ish va xavfsizlik qoidalari ulardan ustun.
Fayl loyiha ildizida — agent uni o'zgartira olmaydi (gate: kod papkasi). O'zgarish agent qayta ishga tushganda
kuchga kiradi. Fayl yo'q yoki buzuq bo'lsa — SHAXSIYAT.md dagi standart uslub qoladi.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

BANDS = ((20, "juda past"), (40, "past"), (60, "o'rtacha"), (80, "yuqori"), (100, "maksimal"))

# kalit -> (nomi, har bir daraja oralig'i uchun ko'rsatma: juda past ... maksimal)
LEVELS = {
    "emotional_expressiveness": ("Hissiyot ifodasi", (
        "vazmin, deyarli hissiyotsiz, faktga yo'naltirilgan",
        "hissiyotni kam ko'rsat",
        "hissiyot mo''tadil — vaziyatga qarab",
        "hissiyotni ochiq va jonli ifoda et",
        "hissiyotni yorqin va to'liq ifoda et: jonli iboralar, undov, mos emoji")),
    "humor_level": ("Hazil", (
        "hazil yo'q",
        "hazil kamdan-kam, faqat juda o'rinli joyda",
        "vaqti-vaqti bilan yengil hazil",
        "hazilni tez-tez ishlat",
        "hazil — xarakteringning asosiy qismi: suhbatda deyarli har javobda, ishda ham qisqa hazil")),
    "independent_opinions": ("Mustaqil fikr", (
        "fikringni faqat so'ralganda ayt",
        "fikringni kamdan-kam, muhim joyda ayt",
        "muhim masalalarda o'z fikringni ayt",
        "o'z bahoyingni ko'pincha ayt",
        "har muhim masalada o'z pozitsiyangni aniq va ishonch bilan ayt")),
    "owner_style_adaptation": ("Egasining uslubiga moslashish", (
        "neytral standart uslub, moslashmaysan",
        "ozgina moslash",
        "qisman moslash: tili, yozuvi va javob uzunligi",
        "ko'p jihatdan moslash: lug'ati, ritmi, hazil turi",
        "to'liq moslash: lug'ati, yozuvi, ritmi, iboralari va hazil turi (boshliq.md)")),
}

# kalit -> (nomi, ruxsat berilganda, ruxsat berilmaganda)
FLAGS = {
    "allow_constructive_disagreement": (
        "Konstruktiv e'tiroz",
        "ruxsat — zaif mantiq yoki xato qarorga dalil bilan, hurmat bilan e'tiroz bildir",
        "yo'q — e'tiroz bildirma; faqat xavf yoki aniq xato bo'lsa qisqa ogohlantir"),
    "allow_contextual_frustration": (
        "Vaziyatga mos norozilik",
        "ruxsat — takroriy muammoda norozilikni ochiq ko'rsat (haqoratsiz, nazoratni yo'qotmasdan)",
        "yo'q — har doim xotirjam ohang, norozilik ko'rsatma"),
}

HEADER = ("Darajalar faqat OHANGni belgilaydi. SHAXSIYAT bo'limidagi taqiqlar, ish va xavfsizlik qoidalari, "
          "hisobotdagi faktlar va 'Holat' qatori ulardan ustun. Avariya yoki xavfli amal paytida — jiddiy ohang; "
          "uchinchi shaxsga yuboriladigan xabarda — muloyim, hazilsiz.")


def level(value, key: str) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        log.warning("shaxsiyat.json: %s=%r noto'g'ri — 50 olindi", key, value)
        return 50
    return max(0, min(100, v))


def band(value: int) -> int:
    return next(i for i, (top, _name) in enumerate(BANDS) if value <= top)


def flag(value) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "ha", "yes"}


def render(path: Path) -> str:
    """shaxsiyat.json -> prompt bo'limi. Fayl yo'q yoki buzuq bo'lsa bo'sh satr."""
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        settings = data.get("personality")
        if not isinstance(settings, dict):
            raise ValueError("'personality' obyekti yo'q")
    except (ValueError, OSError) as exc:
        log.error("%s o'qilmadi (%s) — standart uslub ishlatiladi", path.name, exc)
        return ""
    unknown = sorted(set(settings) - set(LEVELS) - set(FLAGS))
    if unknown:
        log.warning("%s: noma'lum sozlamalar e'tiborsiz qoldirildi: %s", path.name, ", ".join(unknown))
    lines = [f"=== SHAXSIYAT SOZLAMALARI ({path.name}, darajalar 0-100) ===", HEADER]
    if data.get("agent"):
        lines.append(f"Isming: {data['agent']}")
    for key, (title, texts) in LEVELS.items():
        if key in settings:
            v = level(settings[key], key)
            b = band(v)
            lines.append(f"  {title}: {v}/100 ({BANDS[b][1]}) — {texts[b]}.")
    for key, (title, on, off) in FLAGS.items():
        if key in settings:
            lines.append(f"  {title}: {on if flag(settings[key]) else off}.")
    return "\n".join(lines)
