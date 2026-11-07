"""SENTINAL CONTROL CENTER (agent/dashboard): qurilmalar, faoliyat, xavfsizlik va mahalliy monitoring."""
from __future__ import annotations

import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent.config import Config
from agent.dashboard import activity
from agent.dashboard.devices import DeviceCatalog, hierarchy, parse_dn
from agent.dashboard.server import DashboardApp, make_server
from agent.dashboard.settings import DashboardSettings
from agent.inventory import Inventory
from agent.workspace import ensure_workspace

SECRET = "S3cr3t-Pa55w0rd!"


class FakeLocal:
    def __init__(self, name="TEST-PC"):
        self.data = {"computer_name": name, "domain": "corp.local", "collected_at": "2026-11-05T10:00:00",
                     "windows": {"label": "Windows 11 Pro 24H2 (build 26100.1)", "build": "26100.1"},
                     "cpu": {"name": "Test CPU", "cores": 4, "threads": 8, "mhz": 2400}, "ram_total": 8 * 2**30,
                     "disks": [], "ipv4": [{"interface": "eth", "address": "10.0.0.5"}], "software": [],
                     "software_count": 0, "system": {}}

    def get(self):
        return self.data

    def refresh(self):
        return self.data


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    paths = ensure_workspace(home)
    recent = (datetime.now() - timedelta(days=2)).strftime("%d.%m.%Y %H:%M:%S")
    (paths.ish / "Active.csv").write_text(
        '﻿"Name","Sam","OS","LastLogon","Disabled"\n'
        f'"PC-ONE","PC-ONE$","Windows 11 Pro","{recent}","False"\n'
        f'"NB-TEX02","NB-TEX02$","Windows 10 Pro","{recent}","False"\n'
        f'"TEST-PC","TEST-PC$","Windows 10 Pro","{recent}","False"\n', encoding="utf-8")
    (paths.ish / "Stale.csv").write_text(
        '﻿"Name","OS","LastLogon","Disabled","DN"\n'
        '"OLD-PC","Windows 10 Pro","2024-04-08","False","CN=OLD-PC,OU=Компьютеры,OU=Бухгалтерия,OU=Xon Saroy,'
        'DC=corp,DC=local"\n'
        '"GONE-PC","Windows 7","2023-01-01","True","CN=GONE-PC,CN=Computers,DC=corp,DC=local"\n', encoding="utf-8")
    paths.inventory_json.write_text(json.dumps({"hosts": {
        "srv-file": {"type": "windows", "host": "192.168.5.5", "username": "ADMIN\\root", "password": SECRET},
        "nb-tex02": {"type": "windows", "host": "NB-TEX02.corp.local", "description": "Ikkinchi noutbuk"},
        "zabbix": {"type": "http", "host": "- garbage text"},
        "tg-code": {"code": "5 93 46"},
        "mail": {"type": "http", "url": "https://mail.example", "password": SECRET},
    }, "generated": {"x": {"value": "GeneratedSecret123"}}}), encoding="utf-8")
    return home


def _catalog(home: Path, local=None) -> DeviceCatalog:
    return DeviceCatalog(home, Inventory(home / "maxfiy" / "inventar.json"), ["ish/Active.csv", "ish/Stale.csv"],
                         local or FakeLocal())


# ------------------------------------------------------------------------------------------------ qurilmalar
def test_parse_dn_maps_domain_object_department():
    h = parse_dn("CN=PC,OU=Компьютеры,OU=Бухгалтерия,OU=Xon Saroy,DC=xonsaroy,DC=local")
    assert h == {"organization": "xonsaroy.local", "object": "Xon Saroy", "department": "Бухгалтерия",
                 "ou_path": ["Xon Saroy", "Бухгалтерия", "Компьютеры"]}
    assert parse_dn("CN=PC,CN=Computers,DC=corp,DC=local")["object"] is None
    assert parse_dn(r"CN=A\, B,OU=Sales\, East,DC=x")["object"] == "Sales, East"


def test_catalog_merges_sources_without_secrets(tmp_path):
    devices, sources = _catalog(_home(tmp_path)).build()
    by = {d["name"]: d for d in devices}
    assert set(by) == {"PC-ONE", "NB-TEX02", "TEST-PC", "OLD-PC", "GONE-PC", "srv-file"}  # http/hisob yozuvlari yo'q
    assert by["NB-TEX02"]["inventory_names"] == ["nb-tex02"] and by["NB-TEX02"]["status"] == "active"
    assert by["TEST-PC"]["is_local"] and by["TEST-PC"]["status"] == "online"
    assert by["TEST-PC"]["os"].startswith("Windows 11")  # jonli ma'lumot AD dagidan ustun
    assert by["OLD-PC"]["status"] == "stale" and by["OLD-PC"]["department"] == "Бухгалтерия"
    assert by["GONE-PC"]["status"] == "disabled"
    assert by["srv-file"]["os"] is None and by["srv-file"]["status"] == "unknown"  # o'ylab topilmaydi
    blob = json.dumps(devices, ensure_ascii=False)
    for bad in (SECRET, "ADMIN\\\\root", "GeneratedSecret123", "5 93 46", "garbage"):
        assert bad not in blob
    assert {s.kind for s in sources} == {"ad", "inventory", "local", "tuzilma"}


def test_tuzilma_overrides_hierarchy(tmp_path):
    home = _home(tmp_path)
    (home / "xotira" / "tuzilma.json").write_text(json.dumps(
        {"devices": {"pc-one": {"organization": "Xon Saroy", "object": "Bosh ofis", "department": "IT"}}}),
        encoding="utf-8")
    devices, _ = _catalog(home).build()
    pc = next(d for d in devices if d["name"] == "PC-ONE")
    assert (pc["organization"], pc["object"], pc["department"]) == ("Xon Saroy", "Bosh ofis", "IT")
    tree = hierarchy(devices)
    assert tree[-1]["name"] is None  # "Unknown" oxirida
    assert sum(o["count"] for o in tree) == len(devices)


# ------------------------------------------------------------------------------------------------ faoliyat
def _records(now: datetime) -> list[dict]:
    ts = now.isoformat(timespec="seconds")
    old = (now - timedelta(hours=5)).isoformat(timespec="seconds")
    return [
        {"ts": ts, "type": "task_start", "task": "T1", "text": "Disklarni tekshir", "model": "m"},
        {"ts": ts, "type": "action", "task": "T1", "host": "srv-file01", "tool": "run_powershell", "success": True,
         "result": "ok", "params": {"command": "Get-PSDrive"}},
        {"ts": ts, "type": "action", "task": "T1", "host": "srv-file01", "tool": "verify", "success": False,
         "result": "FAIL: disk 95%"},
        {"ts": ts, "type": "task", "task": "T1", "status": "ok", "steps": 2, "mutated": False},
        {"ts": ts, "type": "task_start", "task": "T2", "text": "Xato ish"},
        {"ts": ts, "type": "task_error", "task": "T2", "error": "RuntimeError: boom"},
        {"ts": old, "type": "task_start", "task": "T3", "text": "Yarim qolgan"},
        {"ts": ts, "type": "business"},
        {"ts": ts, "type": "agent_start", "pid": 1},
    ]


def test_build_tasks_and_report(tmp_path):
    now = (datetime.now() - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)  # yarim tun chegarasidan mustaqil
    jurnal = tmp_path / "jurnal"
    jurnal.mkdir()
    (jurnal / f"{now:%Y-%m-%d}.jsonl").write_text("\n".join(json.dumps(r) for r in _records(now)) + "\nnot json\n",
                                                   encoding="utf-8")
    recs = activity.load_records(jurnal, now.date(), now.date())
    assert all(r.get("type") != "business" for r in recs)
    tasks = {t["id"]: t for t in activity.build_tasks(recs, {"T1": {"reply": "Disk C 95% to'lgan"}})}
    assert tasks["T1"]["status"] == "ok" and tasks["T1"]["devices"] == ["srv-file01"]
    assert tasks["T1"]["failed_actions"] == 1 and tasks["T1"]["result"].startswith("Disk C")
    assert tasks["T2"]["status"] == "error" and "boom" in tasks["T2"]["error"]
    assert tasks["T3"]["status"] == "incomplete"
    rep = activity.report(recs, {}, now.date(), now.date())
    assert rep["tasks_total"] == 3 and rep["tasks_ok"] == 1 and rep["actions_failed"] == 1
    assert rep["agent_restarts"] == 1 and rep["per_day"][0]["day"] == f"{now:%Y-%m-%d}"
    events = activity.build_events(recs)
    assert [e["type"] for e in events] == ["agent_start"]


def test_parse_range_is_bounded():
    s, e = activity.parse_range("2020-01-01", "2026-01-01")
    assert (e - s).days == activity.MAX_DAYS - 1
    s, e = activity.parse_range("bad", None)
    assert (e - s).days == 6


# ------------------------------------------------------------------------------------------------ server
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def server(tmp_path):
    home = _home(tmp_path)
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>dash</html>", encoding="utf-8")
    (web / "404.html").write_text("<html>404</html>", encoding="utf-8")
    cfg = Config(agent_home=home, telegram_token="123456789:" + "A" * 35)
    settings = DashboardSettings(port=_free_port(), chat_enabled=False, ad_exports=["ish/Active.csv", "ish/Stale.csv"],
                                 web_dir=web)
    paths = ensure_workspace(home)
    now = datetime.now()
    (paths.jurnal / f"{now:%Y-%m-%d}.jsonl").write_text(json.dumps({
        "ts": now.isoformat(timespec="seconds"), "type": "action", "task": "T9", "host": "srv-file", "tool": "run_powershell",
        "success": True, "result": "Connected as ADMIN\\root", "params": {"command": "whoami"}}) + "\n",
        encoding="utf-8")
    app = DashboardApp(cfg, settings, paths, token="test-token-123")
    app.local = FakeLocal()
    app.catalog.local = app.local
    srv = make_server(app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield app, f"http://127.0.0.1:{settings.port}"
    srv.shutdown()
    srv.server_close()


def _req(url, method="GET", body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8")


def _login(base):
    status, headers, _ = _req(base + "/api/login", "POST", {"token": "test-token-123"},
                              {"X-Requested-With": "sentinal"})
    assert status == 200
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    return cookie.split(";")[0]


def test_api_requires_session_and_local_host(server):
    _, base = server
    assert _req(base + "/api/health")[0] == 200
    assert _req(base + "/api/devices")[0] == 401
    assert _req(base + "/api/devices", headers={"Host": "evil.example:80"})[0] == 403
    assert _req(base + "/api/login", "POST", {"token": "wrong"}, {"X-Requested-With": "sentinal"})[0] == 401
    # CSRF: maxsus sarlavhasiz yoki begona Origin bilan POST — rad
    assert _req(base + "/api/login", "POST", {"token": "test-token-123"})[0] == 403
    assert _req(base + "/api/login", "POST", {"token": "test-token-123"},
                {"X-Requested-With": "sentinal", "Origin": "http://evil.example"})[0] == 403
    assert _req(base + "/api/devices", "DELETE")[0] == 405


def test_api_with_session_returns_data_without_secrets(server):
    _, base = server
    cookie = _login(base)
    h = {"Cookie": cookie}
    status, headers, body = _req(base + "/api/devices", headers=h)
    assert status == 200 and headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in headers["Content-Security-Policy"] and headers["X-Frame-Options"] == "DENY"
    data = json.loads(body)
    assert len(data["devices"]) == 6
    assert SECRET not in body and "GeneratedSecret123" not in body
    for path in ("/api/overview", "/api/hierarchy", "/api/activity", "/api/activity?view=actions",
                 "/api/activity?view=events", "/api/reports", "/api/settings", "/api/monitoring/current",
                 "/api/monitoring/history", "/api/agent", "/api/devices/pc-one"):
        status, _, body = _req(base + path, headers=h)
        assert status == 200, path
        assert SECRET not in body and "123456789:AAAA" not in body and "test-token-123" not in body, path
    assert _req(base + "/api/devices/nope", headers=h)[0] == 404
    assert _req(base + "/api/chat", "POST", {"messages": []}, {**h, "X-Requested-With": "sentinal"})[0] == 503
    assert _req(base + "/api/logout", "POST", {}, {**h, "X-Requested-With": "sentinal"})[0] == 200
    assert _req(base + "/api/devices", headers=h)[0] == 401


def test_inventory_logins_are_masked_in_journal_output(server):
    _, base = server
    body = _req(base + "/api/activity?view=actions", headers={"Cookie": _login(base)})[2]
    assert "Connected as ***" in body and "root" not in body


def test_static_files_and_traversal(server):
    _, base = server
    assert _req(base + "/")[2] == "<html>dash</html>"
    status, _, body = _req(base + "/no-such-page/")
    assert status == 404 and "404" in body
    assert _req(base + "/..%2f..%2fmaxfiy%2finventar.json")[0] == 404
    assert _req(base + "/%2e%2e/home/maxfiy/inventar.json")[0] == 404


def test_settings_view_hides_secret_values(server):
    app, base = server
    body = json.loads(_req(base + "/api/settings", headers={"Cookie": _login(base)})[2])
    assert {"name": "TELEGRAM_BOT_TOKEN", "configured": True} in body["secrets_configured"]
    assert body["dashboard"]["login_origin"].startswith("generated")
    assert app.cfg.telegram_token not in json.dumps(body)


# ------------------------------------------------------------------------------------------------ mahalliy tizim
@pytest.mark.skipif(sys.platform != "win32", reason="Windows registry kerak")
def test_local_inventory_reads_real_values():
    import psutil

    from agent.dashboard import localsys
    win = localsys.windows_version()
    assert win["label"] and win["label"].startswith("Windows")
    cpu = localsys.cpu_info()
    assert cpu["threads"] == psutil.cpu_count() and cpu["name"]
    disks = localsys.disks()
    assert disks and all(0 <= d["percent"] <= 100 and d["total"] > 0 for d in disks)
    software = localsys.installed_software()
    assert isinstance(software, list) and all(s["name"] for s in software)
    sampler = localsys.Sampler(1, 5)
    sampler.start()
    point = sampler.sample()
    assert 0 <= point["cpu"] <= 100 and 0 < point["ram"] <= 100 and point["ram_total"] == psutil.virtual_memory().total
    sampler.stop()
