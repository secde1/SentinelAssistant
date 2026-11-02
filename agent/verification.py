"""Result Verification: yakuniy hisobot holatini KOD tasdiqlaydi (modelning so'ziga ishonilmaydi).

Model hisobot boshida holatni yozadi:  "Holat: SUCCESS | PARTIAL | NEEDS_SETUP | NEEDS_AUTH | FAILED | BLOCKED".
Kod uni topshiriq faktlari bilan solishtiradi:
  - o'zgartirish bo'lgan, lekin oxirgi verify FAIL     -> SUCCESS bo'la olmaydi: FAILED;
  - o'zgartirish bo'lgan, lekin keyin verify PASS yo'q -> SUCCESS bo'la olmaydi: PARTIAL;
  - qadam/vaqt chegarasi tugagan                         -> SUCCESS bo'la olmaydi: PARTIAL;
  - model rad etgan / ichki xato                         -> BLOCKED / FAILED.
Model aniqroq muvaffaqiyatsiz holat bergan bo'lsa (masalan NEEDS_AUTH) — o'shanisi qoladi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

STATUSES = ("SUCCESS", "PARTIAL", "NEEDS_SETUP", "NEEDS_AUTH", "FAILED", "BLOCKED")
ICONS = {"SUCCESS": "✅", "PARTIAL": "⚠️", "NEEDS_SETUP": "🔧", "NEEDS_AUTH": "🔐", "FAILED": "❌", "BLOCKED": "⛔"}

# "Holat: X" — lotin yoki kirill yozuvida (agent Jamshid qaysi yozuvda yozsa, shunda javob beradi).
_STATUS_LINE = re.compile(r"^[^\w\n]*(?:holat|ҳолат|холат|status|статус)\s*:\s*([A-Za-z_]+)[^\n]*\n?",
                          re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class Facts:
    """Topshiriq haqida kod biladigan haqiqat."""

    mutated: bool  # o'zgartiruvchi amal bajarilgan (muvaffaqiyatsiz urinish ham)
    verified: bool  # oxirgi o'zgarishdan keyin verify PASS
    verify_failed: bool  # oxirgi verify FAIL
    run_code: str  # agent sikli natijasi: ok | limit | refusal | error


ALIASES = {"NEEDS_AUTHORIZATION": "NEEDS_AUTH"}  # V5 dagi to'liq nom


def claimed_status(text: str) -> str | None:
    m = _STATUS_LINE.search(text or "")
    if not m:
        return None
    status = ALIASES.get(m.group(1).upper(), m.group(1).upper())
    return status if status in STATUSES else None


def decide(claimed: str | None, facts: Facts) -> tuple[str | None, str | None]:
    """-> (yakuniy holat, kod tuzatgan bo'lsa sababi). Holatni aniqlab bo'lmasa (None, None)."""
    if facts.run_code == "refusal":
        return "BLOCKED", None if claimed == "BLOCKED" else "model so'rovni rad etdi"
    if facts.run_code == "error":
        return "FAILED", None if claimed == "FAILED" else "ichki xato"
    if facts.mutated and facts.verify_failed:
        forced = "FAILED", "o'zgarishdan keyingi tekshiruv (verify) o'tmadi"
    elif facts.mutated and not facts.verified:
        forced = "PARTIAL", "o'zgarishdan keyin qayta o'lchanmadi"
    elif facts.run_code == "limit":
        forced = "PARTIAL", "qadam yoki vaqt chegarasi tugadi"
    else:
        forced = None
    if forced:
        if claimed in (None, "SUCCESS"):
            return forced
        return claimed, None  # model aniqroq muvaffaqiyatsiz holat bergan
    if claimed is None and facts.mutated and facts.verified:
        return "SUCCESS", None
    return claimed, None


def apply(text: str, facts: Facts) -> tuple[str, str | None]:
    """Hisobotga tasdiqlangan holat qatorini qo'yadi. -> (matn, yakuniy holat)."""
    text = (text or "").strip()
    status, reason = decide(claimed_status(text), facts)
    if facts.mutated and not facts.verified:
        text = re.sub(r"(?i)\btasdiqlandi\b", "tasdiqlanmagan (verify yo'q)", text)
    if status is None:
        return text, None
    line = f"{ICONS[status]} Holat: {status}" + (f" — {reason} (kod tekshiruvi)" if reason else "")
    body = _STATUS_LINE.sub("", text, count=1).strip()
    return f"{line}\n{body}" if body else line, status
