"""Artefaktlar (agent yaratgan yoki o'zgartirgan fayllar): Excel formulalarini mustaqil hisoblash, kesh qiymatlar,
tekshiruv (validation), versiyalar va faol ish konteksti (Active Task Context).

Kod darajasidagi kafolatlar:
  • formula hisoblagichi (formula.py) — openpyxl formulani hisoblamaydi; biz o'zimiz hisoblaymiz va natijani
    faylga kesh qiymat qilib yozamiz (formula O'CHIRILMAYDI) — Telegram/telefon ko'rgichida ham jami ko'rinadi;
  • tekshiruv (validate.py) — fayl ochiladimi, formulalar xatosiz hisoblanadimi, ИТОГО ko'rinadimi, kutilgan
    qiymatlar mosmi, oldingi versiyaga nisbatan formula/varaq/grafik yo'qolmadimi;
  • faol ish (store.py, intent.py) — "шуни ўзгартир", "ИТОГО қўш", "тайёр файлни юбор" qaysi faylga tegishli.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

# Kuzatiladigan hujjat turlari (agent yaratadigan "natija" fayllari).
ARTIFACT_EXT = {".xlsx", ".xlsm", ".docx", ".pdf", ".pptx", ".csv"}
EXCEL_EXT = {".xlsx", ".xlsm"}


def is_artifact(path: Path | str) -> bool:
    p = Path(path)
    return p.suffix.lower() in ARTIFACT_EXT and not p.name.startswith(("~$", ".~"))


def sha256(path: Path | str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
