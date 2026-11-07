"""Faol ish konteksti (Active Task Context) va artefakt versiyalari — ish/aktiv_ish.json, ish/versiyalar/.

Har topshiriqdan keyin kod yozadi (model emas):
  • joriy topshiriq ID, asl maqsad, oxirgi ko'rsatmalar;
  • ishchi fayl, oxirgi TASDIQLANGAN versiya (sha256), oxirgi yuborilgan versiya;
  • kutilayotgan o'zgarish (follow-up bajarilmay qolgan bo'lsa), talab qilingan format, tekshiruv talablari;
  • har bir versiyaning nusxasi (tiklash uchun) — faylga oxirgi 10 ta.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from . import sha256

MAX_VERSIONS = 10
MAX_ARTIFACTS = 40
MAX_INSTRUCTIONS = 6
ACTIVE_HOURS = 48  # shundan eski faol ish — endi "faol" emas, faqat tarix

_lock = threading.Lock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _key(path: Path | str) -> str:
    return str(Path(path).resolve())


class ActiveTaskStore:
    def __init__(self, ish: Path):
        self.ish = Path(ish)
        self.path = self.ish / "aktiv_ish.json"
        self.versions_dir = self.ish / "versiyalar"
        self.data = self._load()

    # ------------------------------------------------------------------ saqlash
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("active", None)
                data.setdefault("artifacts", {})
                return data
        except (OSError, ValueError):
            pass
        return {"active": None, "artifacts": {}}

    def save(self) -> None:
        with _lock:
            self.ish.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)

    # ------------------------------------------------------------------ faol ish
    @property
    def active(self) -> dict | None:
        a = self.data.get("active")
        if not a:
            return None
        try:
            if datetime.now() - datetime.fromisoformat(a.get("updated", "")) > timedelta(hours=ACTIVE_HOURS):
                return None
        except ValueError:
            return None
        return a

    def active_file(self) -> Path | None:
        a = self.active
        if a and a.get("file") and Path(a["file"]).is_file():
            return Path(a["file"])
        return None

    def previous_file(self) -> Path | None:
        """Oraliqda boshqa mavzudagi ish bo'lgan bo'lsa — undan oldingi ishchi fayl."""
        a = self.active
        if a and a.get("previous_file") and Path(a["previous_file"]).is_file():
            return Path(a["previous_file"])
        return None

    def start_task(self, task_id: str, text: str, *, followup: bool, file: Path | None) -> dict:
        """Yangi topshiriq: follow-up bo'lsa — maqsad saqlanadi, ko'rsatma qo'shiladi; aks holda yangi maqsad."""
        a = self.data.get("active") or {}
        entry = {"task": task_id, "ts": _now(), "text": text[:600]}
        if followup and a:
            a.setdefault("instructions", []).append(entry)
            a["instructions"] = a["instructions"][-MAX_INSTRUCTIONS:]
            a["task_id"] = task_id
        else:
            old = self.data.get("active") or {}
            a = {"task_id": task_id, "objective": text[:1000], "started": _now(), "instructions": [entry],
                 "file": None, "format": None, "verified": None, "delivered": None, "validation": {}, "pending": [],
                 "previous_file": old.get("file") or old.get("previous_file")}
        if file is not None:
            a["file"] = _key(file)
            a["format"] = Path(file).suffix.lower()
        a["updated"] = _now()
        self.data["active"] = a
        return a

    def set_pending(self, items: list[str]) -> None:
        if self.data.get("active"):
            self.data["active"]["pending"] = items[-3:]

    def set_validation(self, requirements: dict) -> None:
        if self.data.get("active") and requirements:
            self.data["active"]["validation"] = requirements

    # ------------------------------------------------------------------ artefaktlar va versiyalar
    def artifact(self, path: Path | str) -> dict | None:
        return self.data["artifacts"].get(_key(path))

    def recent_artifacts(self, hours: int = ACTIVE_HOURS) -> list[tuple[str, dict]]:
        cutoff = datetime.now() - timedelta(hours=hours)
        out = []
        for k, v in self.data["artifacts"].items():
            try:
                if datetime.fromisoformat(v.get("updated", "")) >= cutoff and Path(k).is_file():
                    out.append((k, v))
            except ValueError:
                continue
        return sorted(out, key=lambda kv: kv[1].get("updated", ""), reverse=True)

    def latest_snapshot(self, path: Path | str, exclude_sha: str | None = None) -> Path | None:
        art = self.artifact(path)
        for v in reversed((art or {}).get("versions", [])):
            snap = Path(v.get("snapshot", ""))
            if v.get("sha") != exclude_sha and snap.is_file():
                return snap
        return None

    def latest_verified(self, path: Path | str) -> dict | None:
        art = self.artifact(path)
        for v in reversed((art or {}).get("versions", [])):
            if v.get("verified"):
                return v
        return None

    def record_version(self, path: Path | str, task_id: str, *, verified: bool = False, summary: str = "",
                       origin: str = "agent") -> dict:
        """Joriy faylni versiya sifatida yozadi (nusxasi bilan). sha o'zgarmagan bo'lsa — mavjud yozuvni yangilaydi."""
        p = Path(path)
        sha = sha256(p)
        art = self.data["artifacts"].setdefault(_key(p), {"name": p.name, "versions": [], "origin": origin})
        versions = art["versions"]
        cur = next((v for v in versions if v.get("sha") == sha), None)
        if cur is None:
            dest_dir = self.versions_dir / f"{p.stem[:40]}-{hashlib.sha1(_key(p).encode('utf-8')).hexdigest()[:8]}"
            dest_dir.mkdir(parents=True, exist_ok=True)
            snap = dest_dir / f"{datetime.now():%Y%m%d-%H%M%S}_{sha[:8]}{p.suffix}"
            shutil.copy2(p, snap)
            cur = {"sha": sha, "ts": _now(), "task": task_id, "snapshot": str(snap), "verified": False, "summary": ""}
            versions.append(cur)
            for old in versions[:-MAX_VERSIONS]:
                try:
                    Path(old["snapshot"]).unlink(missing_ok=True)
                except OSError:
                    pass
            art["versions"] = versions[-MAX_VERSIONS:]
        if verified:
            cur["verified"] = True
            cur["summary"] = summary[:500]
        art["updated"] = _now()
        art["last_task"] = task_id
        self._trim()
        return cur

    def mark_delivered(self, path: Path | str, sha: str, task_id: str) -> None:
        art = self.data["artifacts"].get(_key(path))
        if art is not None:
            art["delivered"] = {"sha": sha, "ts": _now(), "task": task_id}
            art["updated"] = _now()
        a = self.data.get("active")
        if a and a.get("file") == _key(path):
            a["delivered"] = {"sha": sha, "ts": _now(), "task": task_id}

    def set_active_file(self, path: Path | str) -> None:
        a = self.data.get("active")
        if a is None:
            return
        a["file"] = _key(path)
        a["format"] = Path(path).suffix.lower()
        a["updated"] = _now()
        v = self.latest_verified(path)
        a["verified"] = {"sha": v["sha"], "ts": v["ts"], "task": v["task"], "summary": v.get("summary", "")} if v else None

    def _trim(self) -> None:
        arts = self.data["artifacts"]
        if len(arts) <= MAX_ARTIFACTS:
            return
        for k, _v in sorted(arts.items(), key=lambda kv: kv[1].get("updated", ""))[:len(arts) - MAX_ARTIFACTS]:
            arts.pop(k, None)

    # ------------------------------------------------------------------ prompt uchun
    def context_block(self, resolution: Any = None) -> str:
        a = self.active
        lines = ["=== FAOL ISH (Active Task Context — kod yuritadi; follow-up shu bo'yicha tushuniladi) ==="]
        if not a:
            lines.append("Faol ish yo'q.")
            return "\n".join(lines) + self._resolution_text(resolution)
        lines.append(f"Topshiriq: {a.get('task_id')} | Asl maqsad: {a.get('objective', '')[:400]}")
        instr = a.get("instructions") or []
        if len(instr) > 1:
            lines.append("Oxirgi ko'rsatmalar:")
            lines += [f"  - [{i.get('ts', '')[11:16]}] {i.get('text', '')[:200]}" for i in instr[-4:]]
        if a.get("file"):
            f = Path(a["file"])
            state = "fayl topilmadi!" if not f.is_file() else ""
            if f.is_file():
                cur = sha256(f)
                v = self.latest_verified(f)
                if v and v["sha"] == cur:
                    state = f"joriy versiya TASDIQLANGAN ({v['ts'][5:16]}, sha {cur[:8]})"
                elif v:
                    state = (f"joriy versiya tasdiqlanmagan (sha {cur[:8]}); oxirgi tasdiqlangan: {v['ts'][5:16]}, "
                             f"nusxa: {v['snapshot']}")
                else:
                    state = f"hali tasdiqlanmagan (sha {cur[:8]})"
            lines.append(f"Ishchi fayl: {f} ({a.get('format') or f.suffix}) — {state}")
            if a.get("delivered"):
                lines.append(f"Oxirgi yuborilgan versiya: sha {a['delivered']['sha'][:8]} ({a['delivered']['ts'][5:16]})")
        elif a.get("previous_file") and Path(a["previous_file"]).is_file():
            lines.append(f"Oldingi ishchi fayl (boshqa mavzudan oldin): {a['previous_file']}")
        if a.get("validation"):
            lines.append(f"Tekshiruv talablari (avvalgi): {json.dumps(a['validation'], ensure_ascii=False)[:400]}")
        if a.get("pending"):
            lines.append("Bajarilmay qolgan o'zgarish: " + " | ".join(p[:200] for p in a["pending"]))
        others = [(k, v) for k, v in self.recent_artifacts(24) if k != a.get("file")][:4]
        if others:
            lines.append("Boshqa so'nggi fayllar: " + "; ".join(f"{Path(k).name} ({v.get('updated', '')[5:16]})"
                                                             for k, v in others))
        return "\n".join(lines) + self._resolution_text(resolution)

    @staticmethod
    def _resolution_text(res: Any) -> str:
        if res is None:
            return ""
        return "\n" + res.instruction() if res.instruction() else ""
