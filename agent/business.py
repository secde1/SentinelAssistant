"""Telegram Business: ulanish va suhbatlarni eslab qolish, Jamshid buyrug'i bilan xabar yuborish.
Begona xabarlar BUYRUQ EMAS — faqat chat ID/ismi saqlanadi."""
from __future__ import annotations

import json
import time
from pathlib import Path


class BusinessStore:
    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"connections": {}, "chats": {}}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def record_connection(self, c: dict) -> None:
        d = self._load()
        d["connections"][c["id"]] = {"user_chat_id": c.get("user_chat_id"), "enabled": c.get("is_enabled", True),
                                     "can_reply": bool((c.get("rights") or {}).get("can_reply", c.get("can_reply", True)))}
        self._save(d)

    def record_message(self, m: dict) -> None:
        chat = m.get("chat") or {}
        cid = chat.get("id")
        if cid is None or not m.get("business_connection_id"):
            return
        name = " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("title") or ""
        d = self._load()
        d["chats"][str(cid)] = {"name": name, "username": chat.get("username", ""),
                                "connection_id": m["business_connection_id"], "last_ts": int(m.get("date") or time.time())}
        self._save(d)

    def chats(self) -> dict:
        return self._load()["chats"]

    def find(self, query: str) -> list[tuple[str, dict]]:
        q = str(query).strip().lower().lstrip("@")
        out = []
        for cid, v in self.chats().items():
            if q == cid or q in (v.get("name", "").lower(), v.get("username", "").lower()) or (q and q in v.get("name", "").lower()):
                out.append((cid, v))
        return out
