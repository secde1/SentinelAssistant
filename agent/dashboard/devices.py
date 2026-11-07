"""Qurilmalar ro'yxati: mavjud manbalarni birlashtirish. Yangi ma'lumot O'YLAB TOPILMAYDI — yo'q maydon None
(interfeysda "Unknown").

Manbalar (har biri ixtiyoriy):
  1. AD eksport CSV (DASHBOARD_AD_EXPORTS, standart: ish/ActiveComps.csv; ish/StaleComps.csv) — kompyuter nomi, OS,
     oxirgi kirish, DistinguishedName (bo'lsa — tashkilot tuzilmasi shundan olinadi).
  2. maxfiy/inventar.json — FAQAT maxfiy bo'lmagan maydonlar (type, host, description). Login/parol hech qachon.
  3. Shu kompyuter — jonli inventar (localsys).
  4. xotira/tuzilma.json — qo'lda biriktirish: {"devices": {"NOM": {"organization", "object", "department"}}}.

Tuzilma AD DN dan: domen -> tashkilot, birinchi OU -> obyekt, ikkinchi OU -> bo'lim ("Компьютеры" kabi umumiy
konteynerlar tashlab yuboriladi).
"""
from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..inventory import Inventory, normalize_type

_GENERIC_OU = {"компьютеры", "computers", "workstations", "рабочие станции", "компьютерлар", "kompyuterlar"}
_HOST_RE = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63})*$")
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_NON_DEVICE_TYPES = {"http", "api", "account", ""}


@dataclass
class Source:
    kind: str  # ad | inventory | local | tuzilma
    label: str
    path: str
    exists: bool
    updated: str | None = None
    records: int = 0
    error: str | None = None


def _mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


def _key(name: str) -> str:
    return (name or "").strip().split(".")[0].upper()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", (name or "").strip().lower()).strip("-") or "device"


def parse_dn(dn: str) -> dict:
    """'CN=PC,OU=Компьютеры,OU=Бухгалтерия,OU=Xon Saroy,DC=xonsaroy,DC=local' ->
    {'organization': 'xonsaroy.local', 'object': 'Xon Saroy', 'department': 'Бухгалтерия', 'ou_path': [...]}"""
    parts = [p.strip() for p in re.split(r"(?<!\\),", dn or "") if "=" in p]
    ous, dcs = [], []
    for p in parts:
        k, _, v = p.partition("=")
        v = v.replace("\\,", ",").strip()
        if k.strip().upper() == "OU":
            ous.append(v)
        elif k.strip().upper() == "DC":
            dcs.append(v)
    ou_path = list(reversed(ous))
    meaningful = [o for o in ou_path if o.strip().lower() not in _GENERIC_OU]
    return {
        "organization": ".".join(dcs).lower() or None,
        "object": meaningful[0] if meaningful else None,
        "department": meaningful[1] if len(meaningful) > 1 else None,
        "ou_path": ou_path,
    }


def _parse_logon(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d", "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _col(row: dict, *names: str) -> str:
    lower = {(k or "").strip().lower(): v for k, v in row.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def read_ad_export(path: Path) -> list[dict]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        name = _col(row, "Name", "ComputerName", "DNSHostName", "CN")
        if not name:
            continue
        disabled = _col(row, "Disabled").lower() == "true" or _col(row, "Enabled").lower() == "false"
        out.append({
            "name": name.split(".")[0].upper(),
            "os": _col(row, "OS", "OperatingSystem") or None,
            "os_version": _col(row, "OperatingSystemVersion", "OSVersion") or None,
            "last_logon": _parse_logon(_col(row, "LastLogon", "LastLogonDate", "LastLogonTimestamp")),
            "disabled": disabled,
            "dn": _col(row, "DN", "DistinguishedName") or None,
            "ip": _col(row, "IPv4Address", "IP") or None,
            "description": _col(row, "Description") or None,
        })
    return out


class DeviceCatalog:
    def __init__(self, home: Path, inventory: Inventory, ad_exports: list[str], local: Any, stale_days: int = 30):
        self.home = Path(home)
        self.inventory = inventory
        self.ad_exports = ad_exports
        self.local = local  # LocalInventory | None
        self.stale_days = stale_days

    @property
    def tuzilma_path(self) -> Path:
        return self.home / "xotira" / "tuzilma.json"

    def _resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else self.home / p

    # ------------------------------------------------------------------ yig'ish
    def build(self) -> tuple[list[dict], list[Source]]:
        devices: dict[str, dict] = {}
        sources: list[Source] = []
        now = datetime.now()

        for rel in self.ad_exports:
            path = self._resolve(rel)
            src = Source("ad", f"AD export: {path.name}", str(path), path.is_file(), _mtime(path))
            sources.append(src)
            if not src.exists:
                continue
            try:
                rows = read_ad_export(path)
            except (OSError, csv.Error) as exc:
                src.error = f"{type(exc).__name__}: {exc}"[:200]
                continue
            src.records = len(rows)
            for r in rows:
                self._merge_ad(devices, r, src, now)

        inv_src = Source("inventory", "Agent inventory (type, host, description only)", str(self.inventory.path),
                         self.inventory.path.is_file(), _mtime(self.inventory.path))
        sources.append(inv_src)
        if inv_src.exists:
            try:
                inv_src.records = self._merge_inventory(devices)
            except (OSError, ValueError) as exc:
                inv_src.error = f"{type(exc).__name__}"

        if self.local is not None:
            data = self.local.get()
            sources.append(Source("local", "This computer (psutil + Windows registry)", "local", True,
                                  data.get("collected_at"), 1))
            self._merge_local(devices, data)

        tz_src = Source("tuzilma", "Manual hierarchy assignments", str(self.tuzilma_path), self.tuzilma_path.is_file(),
                        _mtime(self.tuzilma_path))
        sources.append(tz_src)
        if tz_src.exists:
            try:
                tz_src.records = self._apply_tuzilma(devices)
            except (OSError, ValueError) as exc:
                tz_src.error = f"{type(exc).__name__}: {exc}"[:200]

        out = sorted(devices.values(), key=lambda d: (not d["is_local"], d["name"].lower()))
        ids: set[str] = set()
        for d in out:
            base = _slug(d["name"])
            d["id"], n = base, 1
            while d["id"] in ids:
                n += 1
                d["id"] = f"{base}-{n}"
            ids.add(d["id"])
        return out, sources

    @staticmethod
    def _blank(name: str) -> dict:
        return {"id": "", "name": name, "type": None, "host": None, "ipv4": [], "description": None,
                "os": None, "os_version": None, "cpu": None, "ram_total": None, "disks": None,
                "status": "unknown", "status_detail": None, "last_seen": None,
                "organization": None, "object": None, "department": None, "ou_path": [], "hierarchy_source": None,
                "last_inventory_update": None, "sources": [], "inventory_names": [], "is_local": False,
                "domain": None, "system": None, "software_count": None}

    def _merge_ad(self, devices: dict, r: dict, src: Source, now: datetime) -> None:
        d = devices.setdefault(_key(r["name"]), self._blank(r["name"]))
        newer = r["last_logon"] and (not d["last_seen"] or r["last_logon"].isoformat() > d["last_seen"])
        if newer or d["os"] is None:
            d["os"] = r["os"] or d["os"]
            d["os_version"] = r["os_version"] or d["os_version"]
        if newer:
            d["last_seen"] = r["last_logon"].isoformat(timespec="seconds")
        d["type"] = d["type"] or "windows"
        d["description"] = d["description"] or r["description"]
        if r["ip"] and r["ip"] not in d["ipv4"]:
            d["ipv4"].append(r["ip"])
        if r["dn"] and not d["ou_path"]:
            h = parse_dn(r["dn"])
            d.update({k: h[k] for k in ("organization", "object", "department", "ou_path")})
            d["hierarchy_source"] = "AD distinguished name"
        if not d["is_local"]:
            if r["disabled"]:
                d["status"], d["status_detail"] = "disabled", "Computer account is disabled in AD"
            elif d["last_seen"]:
                days = (now - datetime.fromisoformat(d["last_seen"])).days
                stale = days > self.stale_days
                d["status"] = "stale" if stale else "active"
                d["status_detail"] = f"Last AD logon {days} day(s) ago"
            d["last_inventory_update"] = max(filter(None, [d["last_inventory_update"], src.updated]), default=None)
        d["sources"].append(src.label)

    def _merge_inventory(self, devices: dict) -> int:
        count = 0
        for name, entry in self.inventory.public_view().items():
            typ = normalize_type(str(entry.get("type") or ""))
            host = str(entry.get("host") or "").strip()
            if typ in _NON_DEVICE_TYPES or not host or not (_IP_RE.match(host) or _HOST_RE.match(host)):
                continue  # hisob/servis yozuvi yoki noto'g'ri host — qurilma emas
            is_ip = bool(_IP_RE.match(host))
            key = _key(name) if is_ip else _key(host)
            match = next((k for k in (key, _key(name)) if k in devices), None)
            d = devices.setdefault(match or key, self._blank(name if is_ip else host.split(".")[0].upper()))
            d["type"] = typ or d["type"]
            d["host"] = d["host"] or host
            if is_ip and host not in d["ipv4"]:
                d["ipv4"].append(host)
            desc = entry.get("description")
            if isinstance(desc, str) and desc.strip() and desc != "***":
                d["description"] = d["description"] or desc.strip()[:300]
            d["inventory_names"].append(name)
            if "Agent inventory" not in d["sources"]:
                d["sources"].append("Agent inventory")
            count += 1
        return count

    def _merge_local(self, devices: dict, data: dict) -> None:
        name = data.get("computer_name") or "THIS-PC"
        d = devices.setdefault(_key(name), self._blank(name))
        win = data.get("windows") or {}
        d.update({
            "is_local": True, "type": "windows", "os": win.get("label") or d["os"], "os_version": win.get("build"),
            "cpu": data.get("cpu"), "ram_total": data.get("ram_total"), "disks": data.get("disks"),
            "status": "online", "status_detail": "This computer — live data", "domain": data.get("domain"),
            "system": data.get("system"), "software_count": data.get("software_count"),
            "last_inventory_update": data.get("collected_at"), "last_seen": datetime.now().isoformat(timespec="seconds"),
        })
        d["ipv4"] = [a["address"] for a in data.get("ipv4") or []] or d["ipv4"]
        if not d["organization"] and data.get("domain"):
            d["organization"] = data["domain"]
            d["hierarchy_source"] = "Windows domain membership"
        d["sources"].append("This computer")

    def _apply_tuzilma(self, devices: dict) -> int:
        raw = self.tuzilma_path.read_text(encoding="utf-8-sig").strip()
        data = json.loads(raw) if raw else {}
        count = 0
        for name, fields in (data.get("devices") or {}).items():
            d = devices.get(_key(name))
            if d is None or not isinstance(fields, dict):
                continue
            for k in ("organization", "object", "department"):
                if isinstance(fields.get(k), str) and fields[k].strip():
                    d[k] = fields[k].strip()
            d["hierarchy_source"] = "xotira/tuzilma.json"
            count += 1
        return count


def hierarchy(devices: list[dict]) -> list[dict]:
    """ORGANIZATION -> OBJECT -> DEPARTMENT -> qurilmalar soni (None — "Unknown")."""
    orgs: dict = {}
    for d in devices:
        o = orgs.setdefault(d["organization"], {"name": d["organization"], "objects": {}, "count": 0})
        ob = o["objects"].setdefault(d["object"], {"name": d["object"], "departments": {}, "count": 0})
        dep = ob["departments"].setdefault(d["department"], {"name": d["department"], "count": 0, "status": {},
                                                              "devices": []})
        for node in (o, ob, dep):
            node["count"] += 1
        dep["status"][d["status"]] = dep["status"].get(d["status"], 0) + 1
        dep["devices"].append({"id": d["id"], "name": d["name"], "status": d["status"], "os": d["os"]})

    def order(items):  # nomlilar alfavit bo'yicha, "Unknown" oxirida
        return sorted(items, key=lambda x: (x["name"] is None, (x["name"] or "").lower()))

    out = []
    for o in order(orgs.values()):
        objects = []
        for ob in order(o["objects"].values()):
            objects.append({"name": ob["name"], "count": ob["count"], "departments": order(ob["departments"].values())})
        out.append({"name": o["name"], "count": o["count"], "objects": objects})
    return out
