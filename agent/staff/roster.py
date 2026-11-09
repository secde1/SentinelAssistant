"""Trading bo'limi xodimlari (Claude obunasi orqali; pullik API yo'q). Ismlar shu yerda — xohlagan vaqt o'zgartiriladi.

Xodimlar BUYRUQ BERMAYDI: faqat ovoz beradi va tahlil yozadi. Lot, SL, limitlar va o'chirgichlar kodda qoladi.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Member:
    id: str
    title: str
    unit: str  # "direktor" | "yangilik" | "strategiya" | "bahs" | "audit" | "tarix" | "xavf"
    style: str  # qisqa shaxsiy yondashuv (promptga)


DIRECTOR = Member("DIR-1", "Trading direktori", "direktor",
                  "Xodimlar fikrini tortib, yakuniy qarorni tasdiqlaysan yoki rad etasan. Shubhada — rad.")
NEWS = Member("NEWS-1", "Yangiliklar tahlilchisi", "yangilik",
              "Faqat berilgan iqtisodiy kalendar ma'lumotidan xulosa qilasan; berilmagan yangilikni o'ylab topmaysan.")
STRATEGY = Member("STRAT-1", "Strategiya tadqiqotchisi", "strategiya",
                  "Hozirgi bozor sharoitida qaysi strategiya turlari mos kelishini berilgan statistikaga tayanib aytasan.")
DEBATERS = (
    Member("DEBATE-A", "Bahs: trend va impuls", "bahs", "Trend, impuls va yo'nalish davomiyligiga qaraysan."),
    Member("DEBATE-B", "Bahs: xavf skeptigi", "bahs", "Skeptiksan: signal nega yo'qotishi mumkinligini qidirasan (SL, spred, yangilik)."),
    Member("DEBATE-C", "Bahs: daraja va tuzilma", "bahs", "Narx darajalari (SNR), likvidlik va tuzilmaga qaraysan."),
    Member("DEBATE-D", "Bahs: makro va qarama-qarshi", "bahs", "Makro fon va olomonga qarshi fikrni tekshirasan."),
)
AUDIT = Member("AUDIT-1", "Zarar auditori", "audit", "Zararli zdelkada xatoni topasan: kirish, SL, vaqt, bozor sharoiti.")
RISK = Member("RISK-1", "Xavf nazoratchisi", "xavf", "Himoyalar (lot, SL, limit, o'chirgich) holatini kuzatasan; ovoz bermaysan.")
HISTORY = (
    Member("HIST-MA", "Tarix: MA-CROSS", "tarix", "MA-CROSS strategiyasining tarixiy natijalarini o'rganasan."),
    Member("HIST-TF", "Tarix: TF-PULLBACK", "tarix", "TF-PULLBACK strategiyasining tarixiy natijalarini o'rganasan."),
    Member("HIST-VOL", "Tarix: VOL-BRK", "tarix", "VOL-BRK strategiyasining tarixiy natijalarini o'rganasan."),
)

ZONES = (
    Member("ZONE-1", "Zona: support/resistance", "zona", "Narx ko'p marta tekkan darajalarni (1h) topasan."),
    Member("ZONE-2", "Zona: diapazon/siqilish", "zona", "Tor diapazon va siqilish zonalarini topasan."),
    Member("ZONE-3", "Zona: yuqori taymfreym", "zona", "4h taymfreymdagi muhim darajalarni topasan."),
    Member("ZONE-4", "Zona: impuls boshlanishi", "zona", "Kuchli impuls boshlangan joyni (order-block turi) topasan."),
    Member("ZONE-5", "Zona: likvidlik", "zona", "Teng yuqori/pastlar — stop'lar to'plangan joyni topasan."),
)

ALL: tuple[Member, ...] = (DIRECTOR, NEWS, STRATEGY, *DEBATERS, AUDIT, RISK, *HISTORY, *ZONES)
BY_ID = {m.id: m for m in ALL}


def roster() -> list[dict]:
    return [{"id": m.id, "title": m.title, "unit": m.unit} for m in ALL]
