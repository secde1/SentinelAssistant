"""maxfiy/inventar.json — ulanish ma'lumotlari, placeholderlar va agent yaratgan parollar.

Model maxfiy qiymatni hech qachon ko'rmaydi. U buyruqqa placeholder yozadi:
  {{inv:NOM.maydon}}   — inventardagi qiymat, masalan {{inv:mikrotik-asosiy.password}}
  {{secret:NOM}}       — generate_secret bilan yaratilgan parol
Tool bajarilish paytida (faqat ruxsat etilgan hostga) almashtiradi; jurnalga placeholder yoziladi.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import string
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .redact import MASK, is_secret_key

INV_RE = re.compile(r"\{\{\s*inv:([^}\s]+)\.([A-Za-z0-9_\-]+)\s*\}\}")
SECRET_RE = re.compile(r"\{\{\s*secret:([A-Za-z0-9_.\-]+)\s*\}\}")

TYPE_ALIASES = {
    "mikrotik": "mikrotik_routeros",
    "routeros": "mikrotik_routeros",
    "unifi_ap": "unifi",
    "unifi-ap": "unifi",
    "ubiquiti": "unifi",
    "vmware": "esxi",
    "esx": "esxi",
    "win": "windows",
    "windows_server": "windows",
}

_PASSWORD_SYMBOLS = "-_=+.!#*"


class PlaceholderError(Exception):
    pass


def normalize_type(value: str | None) -> str:
    v = (value or "").strip().lower()
    return TYPE_ALIASES.get(v, v)


def _secret_strings(obj: Any, key_is_secret: bool = False) -> list[str]:
    out: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _secret_strings(v, key_is_secret or is_secret_key(str(k)))
    elif isinstance(obj, list):
        for v in obj:
            out += _secret_strings(v, key_is_secret)
    elif key_is_secret and isinstance(obj, (str, int)) and str(obj):
        out.append(str(obj))
    return out


def _mask(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: (MASK if is_secret_key(str(k)) and not isinstance(v, (dict, list)) else _mask(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_mask(v) for v in obj]
    return obj


def has_placeholders(text: str) -> bool:
    return bool(INV_RE.search(text or "") or SECRET_RE.search(text or ""))


def placeholder_entries(text: str) -> set[str]:
    return {m.group(1) for m in INV_RE.finditer(text or "")}


def generate_password(length: int = 16) -> str:
    length = max(12, min(int(length), 64))
    alphabet = string.ascii_letters + string.digits + _PASSWORD_SYMBOLS
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (any(c.islower() for c in pw) and any(c.isupper() for c in pw)
                and any(c.isdigit() for c in pw) and any(c in _PASSWORD_SYMBOLS for c in pw)):
            return pw


class Inventory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cache: dict | None = None
        self._mtime: int | None = None

    # --- o'qish / yozish -------------------------------------------------
    def _load(self) -> dict:
        with self._lock:
            try:
                st = self.path.stat()
            except FileNotFoundError:
                return {"hosts": {}, "generated": {}}
            if self._cache is not None and self._mtime == st.st_mtime_ns:
                return self._cache
            raw = self.path.read_text(encoding="utf-8-sig").strip()
            data = json.loads(raw) if raw else {}
            data.setdefault("hosts", {})
            data.setdefault("generated", {})
            self._cache, self._mtime = data, st.st_mtime_ns
            return data

    def _save(self, data: dict) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
            self._cache, self._mtime = None, None

    # --- hostlar ---------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self._load()["hosts"].keys())

    def get(self, ref: str | None) -> tuple[str, dict] | None:
        """Nom (katta-kichik harf farqsiz) yoki host/IP bo'yicha topadi."""
        if not ref:
            return None
        hosts = self._load()["hosts"]
        r = ref.strip().lower()
        for name, entry in hosts.items():
            if name.lower() == r:
                return name, dict(entry)
        for name, entry in hosts.items():
            if str(entry.get("host", "")).lower() == r:
                return name, dict(entry)
        return None

    def set_fields(self, name: str, fields: dict) -> dict:
        with self._lock:
            data = json.loads(json.dumps(self._load()))
            found = self.get(name)
            canon = found[0] if found else name.strip()
            entry = data["hosts"].setdefault(canon, {})
            for k, v in fields.items():
                if v is None or v == "":
                    continue
                entry[k] = normalize_type(v) if k == "type" else v
            self._save(data)
            return dict(entry)

    def missing(self, name: str, fields: list[str]) -> list[str]:
        found = self.get(name)
        entry = found[1] if found else {}
        return [f for f in fields if f not in entry or entry[f] in (None, "")]

    def public_view(self) -> dict:
        return _mask(self._load()["hosts"])

    def secret_values(self) -> list[str]:
        data = self._load()
        values = _secret_strings(data["hosts"])
        values += [str(g.get("value", "")) for g in data["generated"].values() if g.get("value")]
        return values

    def entry_hosts(self, name: str) -> set[str]:
        found = self.get(name)
        if not found:
            return set()
        entry = found[1]
        out = set()
        if entry.get("host"):
            out.add(str(entry["host"]).lower())
        if entry.get("url"):
            h = urlparse(str(entry["url"])).hostname
            if h:
                out.add(h.lower())
        for h in entry.get("allowed_hosts", []) or []:
            out.add(str(h).lower())
        return out

    def all_hosts(self) -> set[str]:
        out: set[str] = set()
        for name in self.names():
            out |= self.entry_hosts(name)
        return out

    # --- yaratilgan parollar --------------------------------------------
    def generate_secret(self, name: str, length: int = 16, note: str = "") -> str:
        with self._lock:
            data = json.loads(json.dumps(self._load()))
            value = generate_password(length)
            data["generated"][name] = {"value": value, "note": note, "created": datetime.now().isoformat(timespec="seconds")}
            self._save(data)
            return value

    def generated_value(self, name: str) -> str | None:
        g = self._load()["generated"].get(name)
        return g.get("value") if g else None

    def generated_names(self) -> list[str]:
        return sorted(self._load()["generated"].keys())

    # --- placeholderlar --------------------------------------------------
    def resolve(self, text: str, allowed_entries: set[str] | None = None, allow_generated: bool = True) -> tuple[str, list[str]]:
        """Placeholderlarni haqiqiy qiymat bilan almashtiradi.

        allowed_entries — faqat shu inventar yozuvlariga ruxsat (egress nazorati). None — cheklovsiz.
        """
        if not text:
            return text, []
        used: list[str] = []
        allowed = {a.lower() for a in allowed_entries} if allowed_entries is not None else None

        def inv_sub(m: re.Match[str]) -> str:
            ref, field = m.group(1), m.group(2)
            found = self.get(ref)
            if not found:
                raise PlaceholderError(f"inventarda '{ref}' yo'q — avval request_credentials yoki inventory_set chaqiring")
            canon, entry = found
            if allowed is not None and canon.lower() not in allowed:
                raise PlaceholderError(
                    f"'{canon}' maxfiy qiymati bu manzilga yuborilmaydi (faqat o'z hostiga). Buyruqni tekshiring."
                )
            key = next((k for k in entry if k.lower() == field.lower()), None)
            if key is None or entry[key] in (None, ""):
                raise PlaceholderError(f"'{canon}' yozuvida '{field}' maydoni yo'q — request_credentials chaqiring")
            used.append(f"inv:{canon}.{key}")
            return str(entry[key])

        def sec_sub(m: re.Match[str]) -> str:
            name = m.group(1)
            if not allow_generated:
                raise PlaceholderError("bu yerda {{secret:...}} ishlatib bo'lmaydi")
            value = self.generated_value(name)
            if value is None:
                raise PlaceholderError(f"'{name}' nomli yaratilgan parol yo'q — generate_secret chaqiring")
            used.append(f"secret:{name}")
            return value

        out = INV_RE.sub(inv_sub, text)
        out = SECRET_RE.sub(sec_sub, out)
        return out, used
