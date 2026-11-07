"""Yangi xabar oldingi ishning davomimi (follow-up) va qaysi faylga tegishli — kod aniqlaydi.

"ИТОГО суммасини чиқазиб бер", "шуни ўзгартир", "тўғрилаб бер", "тайёр файлни юбор" kabi qisqa xabarlar faol
ishga bog'lanadi. Maqsad — so'zma-so'z javob emas: o'zgarish SHU faylga kiritiladi, tayyor fayl yuboriladi.
Aniqlik faqat bir nechta mos fayl bo'lib, tanlov natijaga ta'sir qilganda so'raladi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from . import EXCEL_EXT, is_artifact
from .store import ActiveTaskStore

_APOS = str.maketrans({"ʻ": "'", "ʼ": "'", "’": "'", "‘": "'", "`": "'", "´": "'"})

# "бу/bu" ataylab yo'q: juda umumiy so'z ("bu kompyuterda...") — yolg'iz o'zi follow-up belgisi emas.
DEICTIC = re.compile(r"(?<!\w)(шу|шуни|шунга|шундан|буни|бунга|уни|ўша|уша|тепадаги|охирги|юқоридаги|"
                     r"shu|shuni|shunga|buni|bunga|uni|o'sha|osha|tepadagi|oxirgi|yuqoridagi|"
                     r"это|этот|эту)(?!\w)", re.I)
MODIFY = re.compile(r"(қўш|қуш|кўш|qo'?sh|чиқаз|чказ|чиқар|chiqar|chiqaz|ўзгартир|узгартир|o'?zgartir|"
                    r"тўғрила|тогрила|тўгрила|to'?g'?rila|togrila|ё+з|й[оo]+з|yo+z|кирит|kirit|ўчир|учир|o'?chir|"
                    r"олиб ташла|olib tashla|янгила|yangila|алмаштир|almashtir|ҳисобла|хисобла|hisobla|"
                    r"формат|\bformat|ранг|\brang|бўя|bo'ya|добав|исправ|измени|поменя|убери|"
                    r"\badd\b|\bchange\b|\bfix\b|\bupdate\b|\bedit\b|\bremove\b|\breplace\b)", re.I)
DELIVER = re.compile(r"(юбор|yubor|ташла|tashla|жўнат|jo'nat|send|тайёр|тайор|tayyor|final|скачать|отправ)", re.I)
FILE_WORDS = {
    "xlsx": re.compile(r"(excel|эксел|ексел|xlsx|жадвал|jadval|смета|smeta|итого|итог|itogo|жами|jami|сумма|summa|"
                       r"катак|katak|варақ|varaq|формула|formula|курс|kurs)", re.I),
    "docx": re.compile(r"(word|ворд|docx|хат\b|xat\b|ариза|ariza|ҳужжат|хужжат|hujjat|шартнома|shartnoma)", re.I),
    "pdf": re.compile(r"(pdf|пдф)", re.I),
}
GENERIC_FILE = re.compile(r"(файл|fayl|file|ҳужжат|hujjat|документ)", re.I)
NEW_TASK = re.compile(r"\b(янги|yangi|бошқа|boshqa|алоҳида|alohida|новый|новую|другой|new)\b", re.I)
_ATTACHED = re.compile(r"\[Fayl biriktirildi: (?P<path>.+?) \(\d+ bayt")


def _kind(path: Path | str) -> str:
    s = Path(path).suffix.lower()
    return "xlsx" if s in EXCEL_EXT else s.lstrip(".")


@dataclass
class Resolution:
    followup: bool = False
    modify: bool = False
    deliver_only: bool = False
    new_task: bool = False
    file: Path | None = None
    candidates: list[Path] = field(default_factory=list)
    attached: list[Path] = field(default_factory=list)
    reason: str = ""

    @property
    def ambiguous(self) -> bool:
        return self.followup and self.file is None and len(self.candidates) > 1

    def instruction(self) -> str:
        if self.attached and self.file is not None:
            head = f">>> Jamshid fayl yubordi: {self.file}. Shu fayl ishchi fayl."
            if self.modify:
                head += (" O'zgarishni SHU faylga kirit (nusxasi versiyalar papkasida saqlangan), keyin verify_artifact va "
                         "notify_owner(file_path=...).")
            return head
        if not self.followup:
            return ""
        if self.ambiguous:
            names = ", ".join(p.name for p in self.candidates[:5])
            return (f">>> Bu xabar oldingi ishning davomi, lekin bir nechta mos fayl bor: {names}. Qaysi biri ekani natijaga "
                    "ta'sir qiladi — BITTA qisqa savol bilan aniqlashtir (ask_owner).")
        if self.file is None:
            return (">>> Bu xabar oldingi ishning davomi (kod aniqladi). Faol ish maqsadi bo'yicha davom et; ko'rsatmani "
                    "so'zma-so'z emas, asl maqsad kontekstida tushun.")
        lines = [f">>> BU XABAR — FAOL ISHNING DAVOMI (kod aniqladi: {self.reason}). Ishchi fayl: {self.file}"]
        if not self.modify and not self.deliver_only:
            lines.append("  - O'zgartirish so'zi yo'q: savol bo'lsa — shu fayldagi HAQIQIY qiymatlar asosida javob ber "
                         "(inspect_artifact). Agar Jamshid natijani faylda ko'rmoqchi bo'lsa — shu faylga kirit.")
        elif self.deliver_only:
            lines.append("  - Yangi o'zgarish so'ralmagan: shu faylning oxirgi TASDIQLANGAN versiyasini notify_owner("
                         "file_path=...) bilan yubor (kod yuborishdan oldin o'zi tekshiradi). Faylni qaytadan YARATMA, "
                         "formulalarni O'CHIRMA, nomini o'zgartirma.")
        else:
            lines.append("  - Natija shu FAYL ichida bo'lishi kerak: o'zgarishni AYNAN shu faylga kirit. Faqat chatda raqam "
                         "aytish yoki yangi alohida hujjat yaratish — NOTO'G'RI.")
            lines.append("  - Tartib: inspect_artifact -> eng kam o'zgarish (Excel jami uchun excel_total; boshqa o'zgarish — "
                         "skript bilan shu faylni ochib tahrirla, formula va formatlarni saqla) -> verify_artifact (expect "
                         "bilan) -> notify_owner(file_path=shu fayl).")
        lines.append("  - Qaysi fayl ekanini so'rama: ish va fayl aniq.")
        return "\n".join(lines)


def normalize(text: str) -> str:
    return (text or "").translate(_APOS).lower()


def attached_files(notes: list[str]) -> list[Path]:
    out = []
    for n in notes or []:
        m = _ATTACHED.search(n)
        if m and is_artifact(m.group("path")):
            out.append(Path(m.group("path")))
    return out


def resolve(text: str, notes: list[str] | None, store: ActiveTaskStore, now: datetime | None = None) -> Resolution:
    now = now or datetime.now()
    msg = normalize(text)
    words = len(msg.split())
    res = Resolution()
    res.attached = attached_files(notes or [])
    res.new_task = bool(NEW_TASK.search(msg))
    has_modify = bool(MODIFY.search(msg))
    has_deliver = bool(DELIVER.search(msg))
    has_deictic = bool(DEICTIC.search(msg))
    kinds = [k for k, rx in FILE_WORDS.items() if rx.search(msg)]
    has_file_word = bool(kinds) or bool(GENERIC_FILE.search(msg))
    res.modify = has_modify
    res.deliver_only = has_deliver and has_file_word and not has_modify
    # "тайёр файл қилиб бер" — yetkazish; "қил" umumiy fe'l, o'zgartirish emas.
    if res.attached:
        res.file = res.attached[-1]
        res.reason = "Jamshid fayl biriktirdi"
        return res

    active = store.active
    if active is None:
        return res
    try:
        age = now - datetime.fromisoformat(active.get("updated", ""))
    except ValueError:
        age = timedelta(days=99)
    recent = age <= timedelta(hours=6)
    active_file = store.active_file() or store.previous_file()

    signals = []
    if has_deictic and (has_modify or has_deliver or has_file_word or recent):
        signals.append("ishora so'zi")
    if active_file is not None and (_kind(active_file) in kinds or (has_file_word and not kinds)):
        signals.append("fayl turi mos")
    if (has_modify or has_deliver) and words <= 10 and recent:
        signals.append("qisqa o'zgartirish/yuborish so'rovi")
    if res.new_task and not has_deictic:
        res.reason = "yangi ish so'zi"
        return res
    if not signals:
        return res
    res.followup = True
    res.reason = ", ".join(signals)

    # Qaysi fayl: xabardagi tur faol fayl turiga mos kelmasa — so'nggi mos faylni qidiramiz.
    if active_file is not None and (not kinds or _kind(active_file) in kinds):
        res.file = active_file
        return res
    candidates = [Path(k) for k, _v in store.recent_artifacts(24) if not kinds or _kind(k) in kinds]
    if len(candidates) == 1:
        res.file = candidates[0]
    elif candidates:
        res.candidates = candidates
    elif active_file is not None:
        res.file = active_file
    return res
