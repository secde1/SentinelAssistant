"""Result Verification: yakuniy hisobot holatini KOD tasdiqlaydi (modelning so'ziga ishonilmaydi).

Model hisobot boshida holatni yozadi:  "Holat: SUCCESS | PARTIAL | NEEDS_SETUP | NEEDS_AUTH | FAILED | BLOCKED".
Kod uni topshiriq faktlari bilan solishtiradi:
  - o'zgartirish bo'lgan, lekin oxirgi verify FAIL     -> SUCCESS bo'la olmaydi: FAILED;
  - o'zgartirish bo'lgan, lekin keyin verify PASS yo'q -> SUCCESS bo'la olmaydi: PARTIAL;
  - qadam/vaqt chegarasi tugagan                         -> SUCCESS bo'la olmaydi: PARTIAL;
  - yaratilgan/o'zgargan hujjat tekshiruvdan o'tmagan   -> SUCCESS bo'la olmaydi: FAILED;
  - follow-up faylni o'zgartirishni so'ragan, fayl o'zgarmagan -> PARTIAL;
  - hujjat yaratilgan/o'zgargan, lekin joriy versiyasi tekshirilmagan -> PARTIAL (tool xatosiz tugagani yetmaydi);
  - model rad etgan / ichki xato                         -> BLOCKED / FAILED.
Model aniqroq muvaffaqiyatsiz holat bergan bo'lsa (masalan NEEDS_AUTH) — o'shanisi qoladi.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

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
    artifacts_unverified: tuple[str, ...] = field(default=())  # joriy versiyasi tekshirilmagan hujjatlar (nomlari)
    artifacts_failed: tuple[str, ...] = field(default=())  # tekshiruvdan o'tmagan (yoki majburan yuborilgan) hujjatlar
    followup_unapplied: bool = False  # follow-up faylni o'zgartirishni so'ragan, lekin fayl o'zgarmagan
    chart_state: str | None = None  # TradingView: confirmed | unverified | needs_setup | invalid


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
    reasons: list[tuple[str, str]] = []
    if facts.mutated and facts.verify_failed:
        reasons.append(("FAILED", "o'zgarishdan keyingi tekshiruv (verify) o'tmadi"))
    elif facts.mutated and not facts.verified:
        reasons.append(("PARTIAL", "o'zgarishdan keyin qayta o'lchanmadi"))
    if facts.artifacts_failed:
        reasons.append(("FAILED", "fayl tekshiruvdan o'tmadi: " + ", ".join(facts.artifacts_failed[:3])))
    if facts.followup_unapplied:
        reasons.append(("PARTIAL", "so'ralgan o'zgarish faylga kiritilmadi"))
    if facts.artifacts_unverified:
        reasons.append(("PARTIAL", "fayl tekshirilmagan: " + ", ".join(facts.artifacts_unverified[:3])))
    if facts.chart_state == "invalid":
        reasons.append(("FAILED", "Pine Script tayyorlanmadi yoki tekshiruvdan o'tmadi"))
    elif facts.chart_state == "needs_setup":
        reasons.append(("NEEDS_SETUP", "TradingView integratsiyasi/qurilmasi tayyor emas"))
    elif facts.chart_state == "unverified":
        reasons.append(("PARTIAL", "TradingView grafigida annotatsiyalar tasdiqlanmagan"))
    if facts.run_code == "limit" and not reasons:
        reasons.append(("PARTIAL", "qadam yoki vaqt chegarasi tugadi"))
    forced = None
    if reasons:
        order = ("FAILED", "NEEDS_SETUP", "PARTIAL")
        worst = next(o for o in order if any(st == o for st, _ in reasons))
        forced = worst, "; ".join(r for st, r in reasons if st == worst)
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
