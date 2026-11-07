"""Kunlik tadqiqot: agent (Claude, WebSearch/WebFetch) navbatdagi mavzuni o'rganadi va har manbani
trading_research_source tool'i bilan bazaga yozadi (URL, nashr sanasi, olingan sana, xulosa, dalil turi).

Ijtimoiy tarmoqdagi mashhurlik — foyda isboti emas. Tasdiqlangan topilma, fikr va gipoteza alohida belgilanadi.
"""
from __future__ import annotations

from datetime import date

RESEARCH_NOTE = ("[AVTOMATIK TOPSHIRIQ — trading kunlik tadqiqoti. Faqat o'qish va internetdan o'rganish: hech qanday "
                 "savdo, buyurtma yoki tizim o'zgarishi yo'q.]")


def topic_for(settings, day: str) -> str:
    topics = settings["research_topics"]
    return topics[date.fromisoformat(day).toordinal() % len(topics)]


def research_prompt(settings, day: str) -> str:
    topic = topic_for(settings, day)
    return (
        f"{RESEARCH_NOTE}\n"
        f"Trading tadqiqoti ({day}). Mavzu: «{topic}».\n"
        "1. WebSearch/WebFetch bilan 3-6 ta ishonchli manba top: avvalo birlamchi manbalar (ilmiy maqola, birja yoki "
        "regulyator hujjati, metodologiya, rasmiy statistika), keyin tajribali mualliflarning hujjatlashtirilgan tahlili. "
        "Ijtimoiy tarmoq/YouTube mashhurligi — foyda isboti EMAS.\n"
        "2. Har bir manba uchun trading_research_source tool'ini chaqir: url, title, publisher, published_at (manbadagi "
        "sana; noma'lum bo'lsa bo'sh qoldir — O'YLAB TOPMA), summary (2-4 jumla, nima isbotlangan / nima taxmin), "
        "evidence_type: verified_finding (ma'lumot yoki tajriba bilan isbotlangan), opinion (muallif fikri), hypothesis "
        "(sinalishi kerak bo'lgan g'oya), topic.\n"
        "3. Oxirida 4-6 qatorlik xulosa: nima o'rganildi, qaysi strategiya gipotezalariga ta'siri bor, qanday eksperiment "
        "taklif qilinadi (agar dalil yetarli bo'lsa). Narx, foyda yoki natija o'ylab topilmaydi.\n"
        "Bu ta'limiy tadqiqot; real savdo qilinmaydi."
    )
