"""Jarayon hayot sikli: bitta nusxa qulfi, ishga tushish/to'xtash holati va oldingi ish qanday tugaganini aniqlash.

Fayllar AGENT_HOME/ish ichida (GitHubga tushmaydi):
  agent.lock  — qulflangan fayl. Jarayon har qanday sabab bilan o'lsa, Windows qulfni o'zi bo'shatadi, shuning
                uchun "o'lik PID" muammosi yo'q. Ikkinchi nusxa qulfni ololmaydi va darhol chiqadi.
  agent.state — joriy/oxirgi ish: pid, versiya, boshlangan vaqt, har daqiqadagi "tirik" belgisi, toza tugadimi.
  agent.stop  — egasi agentctl.ps1 stop/restart qilgani. stop'dan keyin ("allow": false) agent o'zi ishga tushmaydi
                (Windows'ga kirganda ham); agentctl.ps1 start uni "allow" qiladi.
  agent.starts — oxirgi ishga tushish urinishlari (crash-loop himoyasi; agentctl start uni tozalaydi).
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from . import __version__
from .config import PROJECT_ROOT

HEARTBEAT_SEC = 60
# 15 daqiqada 5 tadan ortiq ishga tushish — demak har safar yiqilyapti: avtomatik qayta ko'tarish to'xtatiladi.
STORM_WINDOW = timedelta(minutes=15)
STORM_LIMIT = 5


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def agent_version() -> str:
    """'1.0.0+abc1234' — commit .git papkasidan o'qiladi (git dasturi shart emas)."""
    git = PROJECT_ROOT / ".git"
    sha = ""
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            sha = head
        elif (git / head[5:]).is_file():
            sha = (git / head[5:]).read_text(encoding="utf-8").strip()
        else:
            packed = (git / "packed-refs").read_text(encoding="utf-8").splitlines()
            sha = next((ln.split()[0] for ln in packed if ln.endswith(" " + head[5:])), "")
    except OSError:
        pass
    return f"{__version__}+{sha[:7]}" if sha else __version__


def hide_child_consoles() -> None:
    """pythonw.exe (oynasiz) da konsol yo'q, shuning uchun Windows har bir konsol dasturiga (claude.exe, ffmpeg)
    yangi oyna ochadi. Bunday holatda bola jarayonlar standart bo'yicha CREATE_NO_WINDOW bilan yaratiladi."""
    if sys.platform != "win32" or ctypes.windll.kernel32.GetConsoleWindow():
        return
    original = subprocess.Popen.__init__

    def init(self, *args, creationflags: int = 0, **kwargs):
        if not creationflags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
            creationflags |= subprocess.CREATE_NO_WINDOW
        original(self, *args, creationflags=creationflags, **kwargs)

    subprocess.Popen.__init__ = init


def boot_time() -> datetime | None:
    """Windows oxirgi marta qachon yuklangan (qayta yuklashni crash'dan ajratish uchun)."""
    if sys.platform != "win32":
        return None
    ticks = ctypes.windll.kernel32.GetTickCount64
    ticks.restype = ctypes.c_ulonglong
    return _now() - timedelta(milliseconds=ticks())


class InstanceLock:
    """Bitta AGENT_HOME uchun bitta agent: ikkinchi nusxa Telegram'ni talashmasin, jurnalga parallel yozmasin."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def acquire(self, wait: float = 0) -> bool:
        """wait — qulf bo'shashini necha soniya kutish: qayta ishga tushirishda Task Scheduler eski nusxani
        to'xtatib ulgurmasdan yangisi ochilishi mumkin."""
        deadline = time.monotonic() + wait
        while not self._try():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.5)
        return True

    def _try(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115 — qulf jarayon oxirigacha ochiq turadi
        try:
            fh.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        with suppress(OSError):
            self._fh.seek(0)
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        self._fh.close()
        self._fh = None


class Lifecycle:
    def __init__(self, ish: Path):
        self.lock = InstanceLock(ish / "agent.lock")
        self.state_path = ish / "agent.state"
        self.stop_path = ish / "agent.stop"
        self.starts_path = ish / "agent.starts"
        self.state: dict = {}
        self.previous: dict | None = None

    def record_start(self) -> int:
        """Ishga tushish urinishini yozadi va oxirgi STORM_WINDOW ichidagi urinishlar sonini qaytaradi."""
        now = _now()
        try:
            times = [datetime.fromisoformat(t) for t in json.loads(self.starts_path.read_text(encoding="utf-8"))]
        except (OSError, ValueError, TypeError):
            times = []
        times = [t for t in times if timedelta(0) <= now - t < STORM_WINDOW] + [now]
        self.starts_path.parent.mkdir(parents=True, exist_ok=True)
        self.starts_path.write_text(json.dumps([t.isoformat() for t in times]), encoding="utf-8")
        return len(times)

    def _read(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def running_pid(self) -> int | None:
        """Qulfni ushlab turgan nusxaning PID'i (agent.state dan)."""
        return (self._read(self.state_path) or {}).get("pid")

    def owner_stop(self) -> dict | None:
        """Egasi ataylab to'xtatgan bo'lsa — {"ts", "by", "allow"}; allow=False bo'lsa agent ishga tushmasligi kerak."""
        if not self.stop_path.exists():
            return None
        return self._read(self.stop_path) or {"allow": False}

    def begin(self) -> dict | None:
        """Yangi ishni boshlaydi va oldingisi qanday tugaganini qaytaradi (qulf olingandan KEYIN chaqiriladi).
        kind: clean | owner | reboot | unexpected."""
        prev = self._read(self.state_path)
        stop = self.owner_stop()
        with suppress(OSError):
            self.stop_path.unlink()
        now = _now()
        self.state = {"pid": os.getpid(), "version": agent_version(), "started": now.isoformat(),
                      "last_alive": now.isoformat(), "clean": False}
        self._save()
        self.previous = _classify(prev, stop) if prev else None
        return self.previous

    def alive(self) -> None:
        self.state["last_alive"] = _now().isoformat()
        self._save()

    def end(self) -> None:
        self.state.update(last_alive=_now().isoformat(), clean=True)
        self._save()
        self.lock.release()

    def uptime(self) -> str:
        try:
            seconds = int((_now() - datetime.fromisoformat(self.state["started"])).total_seconds())
        except (KeyError, ValueError):
            return "?"
        return f"{seconds // 3600}s {seconds % 3600 // 60}d"

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.state_path)


def _classify(prev: dict, stop: dict | None) -> dict:
    if prev.get("clean"):
        kind, how = "clean", "toza to'xtagan"
    elif stop:
        action = "qayta ishga tushirgan" if stop.get("action") == "restart" else "to'xtatgan"
        kind, how = "owner", f"egasi {action} ({stop.get('ts', '?')})"
    else:
        boot = boot_time()
        try:
            alive = datetime.fromisoformat(str(prev.get("last_alive")))
        except ValueError:
            alive = None
        if boot and alive and alive < boot:
            kind, how = "reboot", "Windows qayta yuklangan yoki o'chirilgan"
        else:
            kind, how = "unexpected", "kutilmaganda to'xtagan (crash, Windows'dan chiqish yoki majburiy to'xtatish)"
    return {"kind": kind, "how": how, "pid": prev.get("pid"), "version": prev.get("version"),
            "started": prev.get("started"), "last_alive": prev.get("last_alive")}
