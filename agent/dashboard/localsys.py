"""Shu kompyuterning o'zi: CPU/RAM/disk yuklamasi, Windows versiyasi, apparat va o'rnatilgan dasturlar.

Faqat o'qish: psutil va Windows registry (winreg). Subprocess, PowerShell, tarmoq so'rovi YO'Q.
"""
from __future__ import annotations

import ipaddress
import json
import os
import platform
import socket
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

try:
    import winreg
except ImportError:  # Windows bo'lmagan muhit (testlar) — registry qiymatlari "Unknown" bo'ladi
    winreg = None  # type: ignore[assignment]

_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_SKIP_RELEASE = {"update", "hotfix", "security update", "service pack"}


# ------------------------------------------------------------------------------------------------ registry
def _reg_values(root: Any, path: str, names: tuple[str, ...], view: int = 0) -> dict:
    out: dict = {}
    if winreg is None:
        return out
    try:
        with winreg.OpenKey(root, path, 0, winreg.KEY_READ | view) as key:
            for name in names:
                try:
                    out[name] = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    pass
    except OSError:
        pass
    return out


def _hklm() -> Any:
    return winreg.HKEY_LOCAL_MACHINE if winreg else None


# ------------------------------------------------------------------------------------------------ statik ma'lumot
def windows_version() -> dict:
    v = _reg_values(_hklm(), r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                    ("ProductName", "EditionID", "DisplayVersion", "ReleaseId", "CurrentBuild", "CurrentBuildNumber",
                     "UBR", "InstallDate"))
    build = str(v.get("CurrentBuild") or v.get("CurrentBuildNumber") or "")
    product = str(v.get("ProductName") or "")
    # Windows 11 registry'da ham "Windows 10 ..." deb yoziladi — build 22000+ bo'lsa bu Windows 11.
    if product.startswith("Windows 10") and build.isdigit() and int(build) >= 22000:
        product = "Windows 11" + product[len("Windows 10"):]
    release = str(v.get("DisplayVersion") or v.get("ReleaseId") or "")
    ubr = v.get("UBR")
    full_build = f"{build}.{ubr}" if build and ubr is not None else build
    installed = None
    if isinstance(v.get("InstallDate"), int) and v["InstallDate"] > 0:
        installed = datetime.fromtimestamp(v["InstallDate"]).isoformat(timespec="seconds")
    if not product:  # registry o'qilmadi — platform modulidan
        product = f"{platform.system()} {platform.release()}".strip()
        full_build = full_build or platform.version()
    label = " ".join(x for x in (product, release) if x)
    if full_build:
        label += f" (build {full_build})"
    return {"product": product or None, "edition": v.get("EditionID"), "release": release or None,
            "build": full_build or None, "installed": installed, "architecture": platform.machine() or None,
            "label": label or None}


def cpu_info() -> dict:
    v = _reg_values(_hklm(), r"HARDWARE\DESCRIPTION\System\CentralProcessor\0", ("ProcessorNameString", "~MHz"))
    name = " ".join(str(v.get("ProcessorNameString") or platform.processor() or "").split())
    freq = None
    try:
        f = psutil.cpu_freq()
        freq = round(f.max or f.current) if f else None
    except (OSError, NotImplementedError, AttributeError):
        pass
    return {"name": name or None, "cores": psutil.cpu_count(logical=False), "threads": psutil.cpu_count(logical=True),
            "mhz": freq or v.get("~MHz")}


def system_info() -> dict:
    v = _reg_values(_hklm(), r"HARDWARE\DESCRIPTION\System\BIOS",
                    ("SystemManufacturer", "SystemProductName", "BIOSVersion", "BIOSReleaseDate", "BaseBoardProduct"))
    clean = {k: (" ".join(str(x).split()) or None) for k, x in v.items()}
    return {"manufacturer": clean.get("SystemManufacturer"), "model": clean.get("SystemProductName"),
            "bios": clean.get("BIOSVersion"), "bios_date": clean.get("BIOSReleaseDate"),
            "board": clean.get("BaseBoardProduct")}


def domain_name() -> str | None:
    v = _reg_values(_hklm(), r"SYSTEM\CurrentControlSet\Services\Tcpip\Parameters", ("Domain", "NV Domain"))
    dom = str(v.get("Domain") or v.get("NV Domain") or "").strip()
    if dom:
        return dom.lower()
    fqdn = socket.getfqdn()
    return fqdn.split(".", 1)[1].lower() if "." in fqdn else None


def ipv4_addresses() -> list[dict]:
    out = []
    try:
        stats = psutil.net_if_stats()
        for nic, addrs in psutil.net_if_addrs().items():
            if nic in stats and not stats[nic].isup:
                continue
            for a in addrs:
                if a.family != socket.AF_INET:
                    continue
                ip = ipaddress.ip_address(a.address)
                if ip.is_loopback or ip.is_link_local:
                    continue
                out.append({"interface": nic, "address": a.address})
    except OSError:
        pass
    return out


def disks() -> list[dict]:
    out = []
    for p in psutil.disk_partitions(all=False):
        opts = (p.opts or "").lower()
        if "cdrom" in opts or not p.fstype:
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append({"device": p.device, "mount": p.mountpoint, "fstype": p.fstype,
                    "kind": "removable" if "removable" in opts else "fixed",
                    "total": u.total, "used": u.used, "free": u.free, "percent": round(u.percent, 1)})
    return out


def installed_software() -> list[dict]:
    """Windows "Programs and Features" bilan bir xil manba: Uninstall kalitlari (64/32-bit, mashina va foydalanuvchi)."""
    if winreg is None:
        return []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "machine", "x64"),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "machine", "x86"),
        (winreg.HKEY_CURRENT_USER, 0, "user", ""),
    ]
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []
    for root, view, scope, arch in roots:
        try:
            base = winreg.OpenKey(root, _UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with base:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                item = _software_entry(base, sub, scope, arch)
                if item is None:
                    continue
                key = (item["name"].lower(), (item["version"] or "").lower())
                if key in seen:
                    continue
                seen.add(key)
                out.append(item)
    out.sort(key=lambda x: x["name"].lower())
    return out


def _software_entry(base: Any, sub: str, scope: str, arch: str) -> dict | None:
    try:
        key = winreg.OpenKey(base, sub)
    except OSError:
        return None
    vals: dict = {}
    with key:
        for name in ("DisplayName", "DisplayVersion", "Publisher", "InstallDate", "EstimatedSize", "SystemComponent",
                     "ParentKeyName", "ReleaseType"):
            try:
                vals[name] = winreg.QueryValueEx(key, name)[0]
            except OSError:
                pass
    name = " ".join(str(vals.get("DisplayName") or "").split())
    if not name or vals.get("SystemComponent") == 1 or vals.get("ParentKeyName"):
        return None
    if str(vals.get("ReleaseType") or "").lower() in _SKIP_RELEASE:
        return None
    date = str(vals.get("InstallDate") or "")
    installed = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if len(date) == 8 and date.isdigit() else None
    size = vals.get("EstimatedSize")
    return {"name": name, "version": str(vals.get("DisplayVersion") or "").strip() or None,
            "publisher": " ".join(str(vals.get("Publisher") or "").split()) or None, "installed": installed,
            "size_mb": round(size / 1024, 1) if isinstance(size, int) and size > 0 else None,
            "scope": scope, "arch": arch or None}


def collect_inventory() -> dict:
    """To'liq mahalliy inventar (dasturlar ro'yxati bilan). Bir necha soniya olishi mumkin."""
    mem = psutil.virtual_memory()
    software = installed_software()
    return {
        "computer_name": (os.environ.get("COMPUTERNAME") or platform.node() or "").upper() or None,
        "domain": domain_name(),
        "windows": windows_version(),
        "cpu": cpu_info(),
        "system": system_info(),
        "ram_total": mem.total,
        "disks": disks(),
        "ipv4": ipv4_addresses(),
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(timespec="seconds"),
        "software": software,
        "software_count": len(software),
        "collected_at": datetime.now().isoformat(timespec="seconds"),
    }


class LocalInventory:
    """Oxirgi mahalliy inventar: xotirada + ish/dashboard/local_inventory.json da (oxirgi yangilanish vaqti saqlanadi)."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict | None = None

    def get(self) -> dict:
        with self._lock:
            if self._data is None:
                self._data = self._load_or_collect()
            return self._data

    def refresh(self) -> dict:
        data = collect_inventory()
        with self._lock:
            self._data = data
            self._save(data)
        return data

    def _load_or_collect(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("computer_name") == (os.environ.get("COMPUTERNAME") or "").upper():
                return data
        except (OSError, ValueError):
            pass
        data = collect_inventory()
        self._save(data)
        return data

    def _save(self, data: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            pass


# ------------------------------------------------------------------------------------------------ jonli yuklama
class Sampler:
    """Har `interval` soniyada CPU/RAM/disk o'lchovi; oxirgi `points` ta nuqta xotirada (grafik uchun)."""

    def __init__(self, interval: int = 5, points: int = 720):
        self.interval = interval
        self.history: deque = deque(maxlen=points)
        self.latest: dict = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._prev_io: tuple[float, Any] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        psutil.cpu_percent(None)  # birinchi chaqiruv — boshlang'ich nuqta (0.0 qaytaradi)
        psutil.cpu_percent(None, percpu=True)
        self._prev_io = (time.monotonic(), _disk_io())
        self._thread = threading.Thread(target=self._run, name="dashboard-sampler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        first = min(1.0, float(self.interval))
        while not self._stop.wait(first):
            first = float(self.interval)
            try:
                self.sample()
            except Exception:  # noqa: BLE001 — bitta o'lchov xatosi sikldan chiqarmasin
                pass

    def sample(self) -> dict:
        now = time.monotonic()
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        io = _disk_io()
        read_bps = write_bps = None
        if self._prev_io and io and self._prev_io[1]:
            dt = max(0.001, now - self._prev_io[0])
            read_bps = max(0.0, (io.read_bytes - self._prev_io[1].read_bytes) / dt)
            write_bps = max(0.0, (io.write_bytes - self._prev_io[1].write_bytes) / dt)
        self._prev_io = (now, io)
        parts = disks()
        system = next((d for d in parts if d["mount"].upper().startswith((os.environ.get("SystemDrive") or "C:").upper())),
                      parts[0] if parts else None)
        point = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "cpu": round(psutil.cpu_percent(None), 1),
            "cpu_per_core": [round(x, 1) for x in psutil.cpu_percent(None, percpu=True)],
            "ram": round(mem.percent, 1), "ram_used": mem.total - mem.available, "ram_total": mem.total,
            "swap": round(swap.percent, 1), "swap_used": swap.used, "swap_total": swap.total,
            "disk": system["percent"] if system else None, "disk_mount": system["mount"] if system else None,
            "disks": parts,
            "disk_read_bps": round(read_bps) if read_bps is not None else None,
            "disk_write_bps": round(write_bps) if write_bps is not None else None,
            "uptime_sec": int(time.time() - psutil.boot_time()),
        }
        with self._lock:
            self.latest = point
            self.history.append({k: point[k] for k in ("ts", "cpu", "ram", "disk", "disk_read_bps", "disk_write_bps")})
        return point

    def current(self) -> dict:
        with self._lock:
            latest = dict(self.latest)
        return latest or self.sample()

    def series(self) -> list[dict]:
        with self._lock:
            return list(self.history)


def _disk_io() -> Any:
    try:
        return psutil.disk_io_counters()
    except (OSError, RuntimeError):
        return None
