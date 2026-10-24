"""Haftalik xulosa (Task Scheduler bilan haftada bir marta: `python -m agent.weekly`).

Kodda hisoblanadi (promptga ishonilmaydi): jurnal/*.jsonl va xotira/tarix.md dan oxirgi 7 kun —
eng ko'p takrorlangan 3 muammo, yangi skillar, saboqlar, tekshirilmagan ishlar. 5 qatorlik matn Telegramga yuboriladi.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta

from .memory import load_skills, stems, _match
from .workspace import Paths


def _records(paths: Paths, now: datetime, days: int) -> list[dict]:
    out: list[dict] = []
    for i in range(days + 1):
        f = paths.jurnal / f"{(now - timedelta(days=i)).strftime('%Y-%m-%d')}.jsonl"
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


_TARIX_HEAD = re.compile(r"(?m)^## (\d{4}-\d{2}-\d{2})[^\n|]*\|\s*(.*)$")
_TARIX_CAT = re.compile(r"(?mi)^- Kategoriya:\s*(\S+)")
_TARIX_LESSON = re.compile(r"(?mi)^- Saboq:\s*(.+)$")


def _from_tarix(paths: Paths, since: str) -> list[dict]:
    path = paths.xotira / "tarix.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    out = []
    for block in re.split(r"(?m)^(?=## )", text):
        m = _TARIX_HEAD.search(block)
        if not m or m.group(1) < since:
            continue
        cat = _TARIX_CAT.search(block)
        lesson = _TARIX_LESSON.search(block)
        out.append({"kategoriya": cat.group(1) if cat else "boshqa", "sarlavha": m.group(2).strip(),
                    "saboq": lesson.group(1).strip() if lesson else ""})
    return out


def collect(paths: Paths, now: datetime | None = None, days: int = 7) -> dict:
    now = now or datetime.now()
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    recs = [r for r in _records(paths, now, days) if str(r.get("ts", ""))[:10] >= since]
    tasks = [r for r in recs if r.get("type") == "task"]
    actions = [r for r in recs if r.get("type") == "action"]
    history = [r for r in recs if r.get("type") == "history"] or _from_tarix(paths, since)
    approvals = [r for r in recs if r.get("type") == "approval"]
    skills = load_skills(paths.skill)
    new_skills = [s.name for s in skills if s.meta.get("yaratilgan", "") >= since]
    updated = [s.name for s in skills if s.meta.get("yangilangan", "") >= since and s.name not in new_skills]
    cats = Counter((h.get("kategoriya") or "boshqa") for h in history)
    return {
        "since": since, "until": now.strftime("%Y-%m-%d"),
        "tasks": len(tasks), "actions": len(actions),
        "failed_actions": sum(1 for a in actions if not a.get("success")),
        "approvals": len(approvals), "denied": sum(1 for a in approvals if not a.get("approved")),
        "unverified": sum(1 for t in tasks if t.get("mutated") and not t.get("verified")),
        "top": cats.most_common(3),
        "new_skills": new_skills, "updated_skills": updated, "skills_total": len(skills),
        "lessons": [h.get("saboq") for h in history if h.get("saboq")][-3:],
        "skill_heads": {s.name: s.head_stems for s in skills},
    }


def _has_skill(category: str, heads: dict[str, set[str]]) -> bool:
    cat = stems(category.replace("-", " "))
    return any(cat and all(any(_match(c, t) for t in head) for c in cat) for head in heads.values())


def build_summary(stats: dict) -> str:
    d1 = datetime.strptime(stats["since"], "%Y-%m-%d").strftime("%d.%m")
    d2 = datetime.strptime(stats["until"], "%Y-%m-%d").strftime("%d.%m")
    line1 = (f"📊 Hafta {d1}–{d2}: {stats['tasks']} ta ish, {stats['actions']} ta amal ({stats['failed_actions']} xato), "
             f"{stats['approvals']} tasdiq so'rovi ({stats['denied']} rad).")
    if stats["top"]:
        parts = []
        for cat, n in stats["top"]:
            mark = "skill bor" if _has_skill(cat, stats["skill_heads"]) else "skill YO'Q"
            parts.append(f"{cat} ×{n} ({mark})")
        line2 = "🔁 Eng ko'p: " + "; ".join(parts) + "."
    else:
        line2 = "🔁 Bu hafta tarix.md ga muammo yozilmadi."
    new = ", ".join(stats["new_skills"]) or "yo'q"
    line3 = f"🧠 Yangi skill: {new}" + (f"; yangilangan: {', '.join(stats['updated_skills'])}" if stats["updated_skills"] else "") \
        + f" (jami {stats['skills_total']})."
    lessons = "; ".join(x[:120] for x in stats["lessons"]) or "saboq yozilmagan"
    line4 = f"📘 O'rganildi: {lessons}."
    missing = [cat for cat, n in stats["top"] if n >= 2 and not _has_skill(cat, stats["skill_heads"])]
    if missing:
        line5 = f"💡 Taklif: '{missing[0]}' {dict(stats['top'])[missing[0]]} marta takrorlandi — skill va avto-tuzatish yozish."
    elif stats["unverified"]:
        line5 = f"💡 Taklif: {stats['unverified']} ta o'zgartirish tekshirilmagan — verify bosqichini kuchaytirish."
    elif stats["top"]:
        line5 = f"💡 Taklif: '{stats['top'][0][0]}' ni Zabbix monitoringi bilan oldindan aniqlash."
    else:
        line5 = "💡 Taklif: muammolarni log_history bilan yozib borish — statistika shundan chiqadi."
    return "\n".join([line1, line2, line3, line4, line5])


def make_summary(paths: Paths) -> str:
    text = build_summary(collect(paths))
    (paths.jurnal / f"haftalik-{datetime.now():%Y-%m-%d}.md").write_text(text + "\n", encoding="utf-8")
    return text


def main() -> int:
    import httpx

    from .config import Config
    from .redact import Redactor
    from .workspace import ensure_workspace

    cfg = Config.from_env()
    paths = ensure_workspace(cfg.agent_home)
    text = make_summary(paths)
    print(text)
    problems = cfg.problems()
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 2
    red = Redactor()
    red.add(cfg.telegram_token, cfg.claude_oauth_token)
    try:
        r = httpx.post(f"https://api.telegram.org/bot{cfg.telegram_token}/sendMessage",
                       json={"chat_id": cfg.allowed_chat_id, "text": red.redact(text)}, timeout=30)
        ok = r.json().get("ok")
    except (httpx.HTTPError, ValueError) as exc:
        print(f"Telegramga yuborilmadi: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
