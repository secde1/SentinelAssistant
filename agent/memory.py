"""Xotira va skillarni yuklash.

Token/xarajat nazorati: kichik fayllar to'liq qo'shiladi; katta fayllardan (tarix.md, ko'p skill)
faqat so'rovga mos bo'limlar tanlanadi. Barcha skillarning qisqa indeksi (nom + tavsif) doim qo'shiladi.
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

_APOS = re.compile(r"[ʻʼ’‘`']")
_TOKEN = re.compile(r"[0-9a-zа-яёўқғҳ]+", re.I)

STOPWORDS = {
    # uz
    "va", "bilan", "uchun", "bu", "shu", "u", "men", "sen", "biz", "siz", "ham", "esa", "yoki", "lekin", "agar",
    "qil", "qilib", "qiling", "qildim", "kerak", "bor", "yoq", "emas", "edi", "deb", "dan", "ga", "da", "ni",
    "nima", "qanday", "qayer", "qachon", "nega", "iltimos", "endi", "hozir", "yana", "bitta", "ikki", "hamma",
    "barcha", "ish", "ishla", "tekshir", "korib", "chiq",
    # ru
    "и", "в", "на", "с", "по", "не", "что", "как", "это", "для", "из", "у", "к", "о", "а", "но", "пожалуйста",
    # en
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "it", "be", "with", "this", "that",
}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(_APOS.sub("", (text or "").lower())) if t not in STOPWORDS and len(t) > 1]


def stems(text: str) -> set[str]:
    return {t[:5] if len(t) > 5 else t for t in tokenize(text)}


def _match(q: str, t: str) -> bool:
    if q == t:
        return True
    if min(len(q), len(t)) < 4:
        return False
    return t.startswith(q) or q.startswith(t)


def _matches(query: set[str], doc: set[str], weights: dict[str, float] | None = None) -> float:
    score = 0.0
    for q in query:
        if any(_match(q, t) for t in doc):
            score += weights.get(q, 1.0) if weights else 1.0
    return score


# ---------------------------------------------------------------- skillar
@dataclass
class Skill:
    name: str
    description: str
    triggers: str
    path: Path
    body: str
    meta: dict = field(default_factory=dict)

    @property
    def head_stems(self) -> set[str]:
        return stems(f"{self.name} {self.name.replace('-', ' ')} {self.description} {self.triggers}")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip()
    return meta, text[end + 4:].lstrip("\n")


def load_skills(skill_dir: Path) -> list[Skill]:
    out: list[Skill] = []
    if not skill_dir.exists():
        return out
    for path in sorted(skill_dir.glob("*/SKILL.md")):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        meta, body = parse_frontmatter(text)
        out.append(Skill(
            name=meta.get("name") or path.parent.name,
            description=meta.get("description", ""),
            triggers=meta.get("triggers", ""),
            path=path,
            body=body,
            meta=meta,
        ))
    return out


def score_skills(query: str, skills: list[Skill]) -> list[tuple[float, Skill]]:
    q = stems(query)
    if not q or not skills:
        return []
    heads = [s.head_stems for s in skills]
    n = len(skills)
    df = {term: sum(1 for h in heads if any(_match(term, t) for t in h)) for term in q}
    weights = {term: 1.0 + math.log((n + 1) / (df[term] + 0.5)) for term in q}
    scored = []
    for s, head in zip(skills, heads):
        score = 3.0 * _matches(q, head, weights) + _matches(q, stems(s.body[:3000]), weights)
        scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored


def select_skills(query: str, skills: list[Skill], k: int = 3, min_score: float = 3.0) -> list[Skill]:
    return [s for score, s in score_skills(query, skills)[:k] if score >= min_score]


def skill_index(skills: list[Skill], home: Path) -> str:
    limit = 160 if len(skills) <= 150 else 90
    lines = []
    for s in skills:
        desc = s.description if len(s.description) <= limit else s.description[: limit - 1] + "…"
        try:
            rel = s.path.relative_to(home)
        except ValueError:
            rel = s.path
        lines.append(f"- {s.name} — {desc} [{rel}]")
    return "\n".join(lines)


# ---------------------------------------------------------------- xotira fayllari
def split_sections(md: str) -> tuple[str, list[str]]:
    """Fayl boshidagi kirish qismi va '## ' bilan boshlanadigan bo'limlar."""
    parts = re.split(r"(?m)^(?=## )", md)
    if parts and not parts[0].startswith("## "):
        return parts[0], [p for p in parts[1:] if p.strip()]
    return "", [p for p in parts if p.strip()]


def select_sections(query: str, md: str, limit_chars: int, top: int = 6, keep_last: int = 3) -> str:
    if len(md) <= limit_chars:
        return md
    head, sections = split_sections(md)
    if not sections:
        return md[-limit_chars:]
    q = stems(query)
    scored = [(_matches(q, stems(sec)), i) for i, sec in enumerate(sections)]
    chosen = {i for score, i in sorted(scored, reverse=True)[:top] if score > 0}
    chosen |= set(range(max(0, len(sections) - keep_last), len(sections)))
    out, total = [head.strip()], len(head)
    for i in sorted(chosen):
        sec = sections[i].strip()
        if total + len(sec) > limit_chars:
            sec = sec[: max(0, limit_chars - total)]
        if sec:
            out.append(sec)
            total += len(sec)
        if total >= limit_chars:
            break
    omitted = len(sections) - len(chosen)
    if omitted > 0:
        out.append(f"(... yana {omitted} ta bo'lim qo'shilmadi — kerak bo'lsa read_file bilan to'liq o'qing)")
    return "\n\n".join(p for p in out if p)


_UZ_DAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]

MEMORY_FILES = [
    ("inventar.md", 6000),
    ("fakt.md", 5000),
    ("boshliq.md", 4000),
    ("tarix.md", 9000),
    ("prompt_qoshimcha.md", 3000),
]


def recent_chat(path: Path, now: datetime, limit: int = 5, max_age_hours: int = 12) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-50:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    cutoff = now - timedelta(hours=max_age_hours)
    fresh = []
    for r in rows:
        try:
            if datetime.fromisoformat(r.get("ts", "")) >= cutoff:
                fresh.append(r)
        except ValueError:
            continue
    return fresh[-limit:]


def build_context(*, query: str, home: Path, task_id: str, model: str, inventory_public: dict,
                  now: datetime | None = None, chat_path: Path | None = None) -> tuple[str, list[Skill]]:
    """Har topshiriq boshida modelga beriladigan kontekst. (matn, tanlangan skillar)."""
    now = now or datetime.now()
    xotira = home / "xotira"
    parts = [
        "=== ISH KONTEKSTI (kod tomonidan har topshiriqda yig'iladi) ===",
        f"Sana/vaqt: {now.strftime('%Y-%m-%d %H:%M')} ({_UZ_DAYS[now.weekday()]})",
        f"Topshiriq ID: {task_id} | Model: {model}",
    ]
    if inventory_public:
        inv = [f"{n} ({e.get('type', '?')}, {e.get('host', e.get('url', '?'))})" for n, e in sorted(inventory_public.items())]
        parts.append("Inventar yozuvlari (placeholder uchun nomlar): " + "; ".join(inv))
    else:
        parts.append("Inventar yozuvlari: hali yo'q (kerak bo'lsa request_credentials).")

    for name, limit in MEMORY_FILES:
        path = xotira / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        keep_last = 3 if name == "tarix.md" else 1
        parts.append(f"\n--- XOTIRA: {name} ---\n{select_sections(query, text, limit, keep_last=keep_last)}")

    skills = load_skills(home / "skill")
    selected = select_skills(query, skills)
    if skills:
        parts.append(f"\n--- SKILL INDEKSI (jami {len(skills)}) ---\n{skill_index(skills, home)}")
    else:
        parts.append("\n--- SKILL INDEKSI ---\nHali skill yo'q.")
    if selected:
        parts.append("\n--- SO'ROVGA MOS SKILLAR (avval shulardan foydalan) ---")
        for s in selected:
            body = s.body if len(s.body) <= 8000 else s.body[:8000] + "\n(... qisqartirildi)"
            parts.append(f"### {s.path.relative_to(home)}\n{body}")

    chat = recent_chat(chat_path, now) if chat_path else []
    if chat:
        parts.append("\n--- SO'NGGI SUHBAT (faqat kontekst) ---")
        for r in chat:
            t = r.get("ts", "")[11:16]
            parts.append(f"[{t}] Jamshid: {str(r.get('user', ''))[:400]}")
            parts.append(f"[{t}] Agent: {str(r.get('reply', ''))[:600]}")
    return "\n".join(parts), selected
