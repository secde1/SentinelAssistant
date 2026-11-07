"""Jarayon hayot sikli: bitta nusxa qulfi, oldingi ish qanday tugagani, crash-loop hisobi, Telegram'ni kutish."""
import asyncio
import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent import __version__, app
from agent.config import Config
from agent.lifecycle import STORM_LIMIT, InstanceLock, Lifecycle
from agent.telegram_api import TelegramError, TelegramNetworkError


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_second_lock_is_refused(tmp_path):
    first, second = InstanceLock(tmp_path / "agent.lock"), InstanceLock(tmp_path / "agent.lock")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_lock_waits_for_dying_instance(tmp_path):
    old, new = InstanceLock(tmp_path / "agent.lock"), InstanceLock(tmp_path / "agent.lock")
    assert old.acquire()
    assert not new.acquire(wait=0.6)
    threading.Timer(0.8, old.release).start()  # Task Scheduler eski nusxani biroz kechikib to'xtatadi
    assert new.acquire(wait=5)
    new.release()


def test_first_start_has_no_previous(tmp_path):
    life = Lifecycle(tmp_path)
    assert life.begin() is None
    state = json.loads((tmp_path / "agent.state").read_text(encoding="utf-8"))
    assert state["clean"] is False
    assert state["version"].startswith(__version__)


def test_clean_stop_is_recognised(tmp_path):
    life = Lifecycle(tmp_path)
    life.begin()
    life.end()
    assert Lifecycle(tmp_path).begin()["kind"] == "clean"


def test_process_death_is_unexpected(tmp_path):
    Lifecycle(tmp_path).begin()  # end() chaqirilmadi — jarayon o'ldi
    prev = Lifecycle(tmp_path).begin()
    assert prev["kind"] == "unexpected"
    assert prev["pid"]


def test_stop_before_last_boot_is_reboot(tmp_path):
    _write(tmp_path / "agent.state", {"pid": 1, "started": "2000-01-01T00:00:00",
                                      "last_alive": "2000-01-01T00:05:00", "clean": False})
    assert Lifecycle(tmp_path).begin()["kind"] == "reboot"


@pytest.mark.parametrize("action,word", [("stop", "to'xtatgan"), ("restart", "qayta ishga tushirgan")])
def test_owner_marker_is_read_once(tmp_path, action, word):
    Lifecycle(tmp_path).begin()
    marker = {"ts": "2026-11-03T20:00:00", "action": action, "allow": True}
    _write(tmp_path / "agent.stop", marker)
    life = Lifecycle(tmp_path)
    assert life.owner_stop() == marker
    prev = life.begin()
    assert prev["kind"] == "owner"
    assert word in prev["how"]
    assert not (tmp_path / "agent.stop").exists()


def test_broken_stop_marker_means_stopped(tmp_path):
    (tmp_path / "agent.stop").write_text("buzuq", encoding="utf-8")
    assert Lifecycle(tmp_path).owner_stop() == {"allow": False}


def test_record_start_counts_only_recent(tmp_path):
    old = (datetime.now() - timedelta(hours=1)).isoformat()
    _write(tmp_path / "agent.starts", [old, old])
    life = Lifecycle(tmp_path)
    assert [life.record_start() for _ in range(STORM_LIMIT + 1)] == list(range(1, STORM_LIMIT + 2))


def test_record_start_survives_garbage(tmp_path):
    (tmp_path / "agent.starts").write_text("{buzuq", encoding="utf-8")
    assert Lifecycle(tmp_path).record_start() == 1


class FakeApi:
    def __init__(self, errors):
        self.errors = list(errors)

    async def get_me(self):
        if self.errors:
            raise self.errors.pop(0)
        return {"username": "bot"}


def test_wait_for_telegram_backs_off_on_network_errors(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(app.asyncio, "sleep", fake_sleep)
    me = asyncio.run(app.wait_for_telegram(FakeApi([TelegramNetworkError("x")] * 4), first_delay=10, max_delay=40))
    assert me["username"] == "bot"
    assert sleeps == [10, 20, 40, 40]


def test_wait_for_telegram_stops_on_bad_token():
    with pytest.raises(app.StartupError):
        asyncio.run(app.wait_for_telegram(FakeApi([TelegramError("getMe: 401 Unauthorized")])))


def test_start_message_warns_about_unexpected_stop(tmp_path):
    cfg = Config(notify_on_start=False)
    auth = SimpleNamespace(ok=True, label="Pro")
    life = Lifecycle(tmp_path)
    Lifecycle(tmp_path).begin()
    life.begin()
    assert "kutilmaganda" in app._start_message(cfg, auth, life)
    clean = Lifecycle(tmp_path / "toza")
    clean.begin()
    clean.end()
    clean.begin()
    assert app._start_message(cfg, auth, clean) is None
