"""V27 chiqish papkasi: ruxsat etilgan fayllar egasiga yuboriladi va 'yuborildi' ga ko'chadi; chegaralar va xatolar."""
from __future__ import annotations

import asyncio
import os
import time

from agent.outbox import MAX_ATTEMPTS, MAX_BYTES, SETTLE_SEC, Outbox


def run(c):
    return asyncio.run(c)


def make(tmp_path, ok=True):
    sent, notes = [], []

    async def send(path, caption):
        sent.append((path.name, caption))
        return ok

    async def notify(t):
        notes.append(t)
    return Outbox(tmp_path / "chiqish", send, notify), sent, notes


def put(box, name, data=b"x", age=60):
    p = box.root / name
    p.write_bytes(data)
    old = time.time() - age
    os.utime(p, (old, old))
    return p


def test_allowed_file_is_sent_once_and_moved(tmp_path):
    box, sent, _ = make(tmp_path)
    put(box, "hisobot.docx")
    assert run(box.tick()) == ["hisobot.docx"]
    assert sent == [("hisobot.docx", "📎 hisobot.docx")]
    assert (box.sent_dir / "hisobot.docx").exists() and not (box.root / "hisobot.docx").exists()
    assert run(box.tick()) == [] and len(sent) == 1  # takror yuborilmaydi


def test_skips_disallowed_hidden_large_empty_fresh_and_folders(tmp_path):
    box, sent, _ = make(tmp_path)
    put(box, "skript.ps1")
    put(box, "maxfiy.env")
    put(box, ".yashirin.docx")
    put(box, "bosh.docx", b"")
    put(box, "yangi.docx", age=SETTLE_SEC - 4)  # hali yozilayotgan bo'lishi mumkin
    big = put(box, "katta.pdf")
    with open(big, "r+b") as f:
        f.truncate(MAX_BYTES + 1)
    (box.root / "ichki").mkdir()
    put(box, "ok.XLSX")
    assert run(box.tick()) == ["ok.XLSX"] and [s[0] for s in sent] == ["ok.XLSX"]


def test_failed_send_keeps_file_retries_and_alerts_once(tmp_path):
    box, sent, notes = make(tmp_path, ok=False)
    put(box, "a.docx")
    for _ in range(MAX_ATTEMPTS + 2):
        assert run(box.tick()) == []
    assert (box.root / "a.docx").exists() and len(sent) == MAX_ATTEMPTS + 2
    assert len(notes) == 1 and "a.docx" in notes[0]  # bitta ogohlantirish


def test_send_exception_does_not_crash_loop_and_name_clash_is_handled(tmp_path):
    box, sent, _ = make(tmp_path)
    calls = {"n": 0}
    real = box.send_file

    async def flaky(path, caption):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("tarmoq")
        return await real(path, caption)
    box.send_file = flaky
    put(box, "b.csv")
    assert run(box.tick()) == [] and (box.root / "b.csv").exists()  # xato — fayl joyida
    assert run(box.tick()) == ["b.csv"]
    put(box, "b.csv")  # xuddi shu nom yana tashlandi
    assert run(box.tick()) == ["b.csv"] and len(list(box.sent_dir.iterdir())) == 2
