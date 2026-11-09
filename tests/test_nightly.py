"""V26 tungi tadqiqot: tun kaliti va faza vaqtlari, jadval (o'tkazib yuborish, kechikish, limit), topilma/reja bazasi,
Excel va Word fayllari, shaxsiy chatga yuborish, tool'lar va /tun buyrug'i. Soxta Claude va Telegram bilan."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from test_mt5 import _ctx

from agent import nightly as nt
from agent.tools import ideas

TZ = timezone(timedelta(hours=5))


def local(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).astimezone(timezone.utc)


def run(c):
    return asyncio.run(c)


class Fake:
    def __init__(self):
        self.prompts, self.active, self.blocked, self.texts, self.files, self.send_ok = [], set(), None, [], [], True

    async def submit(self, prompt):
        self.prompts.append(prompt)
        tid = f"T{len(self.prompts)}"
        self.active.add(tid)
        return tid

    async def send_text(self, t):
        self.texts.append(t)

    async def send_file(self, path, caption):
        self.files.append((path.name, caption))
        return self.send_ok


def make(tmp_path, installed=local(2026, 11, 1, 12)):
    f = Fake()
    n = nt.NightIdeas(tmp_path / "tadqiqot", f.submit, lambda tid: tid in f.active, lambda: f.blocked, f.send_text,
                      f.send_file, clock=lambda: installed)  # o'rnatilgan vaqt: testlarda ancha oldin
    return n, f


def seed(n, night, plans=2, finds=3):
    for i in range(finds):
        n.store.add_finding(night, {"kind": ["github", "internet", "youtube"][i % 3], "url": f"https://example.com/{i}",
                                    "title": f"Manba {i}", "summary": "xulosa", "relevance": 4, "idea": "g'oya",
                                    "safety": "faqat README o'qildi"})
    for i in range(plans):
        n.store.add_plan(night, {"title": f"Funksiya {i}", "benefit": "foyda", "description": "qadamlar", "effort": "M",
                                 "risk": "past", "security": "maxfiylik", "tests": "pytest", "priority": i + 1,
                                 "sources": ["https://example.com/0"]})


# ------------------------------------------------------------------------------------------------ vaqt
def test_night_key_and_phase_times():
    assert nt.night_of(local(2026, 11, 8, 21, 30), TZ) == "2026-11-08"
    assert nt.night_of(local(2026, 11, 9, 0, 30), TZ) == "2026-11-08"  # yarim tundan keyin ham o'sha tun
    assert nt.night_of(local(2026, 11, 9, 5, 0), TZ) == "2026-11-08"
    assert nt.night_of(local(2026, 11, 9, 11, 59), TZ) == "2026-11-08"
    assert nt.night_of(local(2026, 11, 9, 12, 0), TZ) == "2026-11-09"  # tush — yangi tun
    assert nt.at("2026-11-08", "21:00", TZ) == local(2026, 11, 8, 21)
    assert nt.at("2026-11-08", "00:30", TZ) == local(2026, 11, 9, 0, 30)
    assert nt.at("2026-11-08", "05:00", TZ) == local(2026, 11, 9, 5)
    assert nt.at("2026-11-08", "12:00", TZ) == local(2026, 11, 9, 12)


def test_phases_order(tmp_path):
    n, _ = make(tmp_path)
    ph = n.phases("2026-11-08")
    assert [p.name for p in ph] == ["github", "internet", "youtube", "plan", "deliver"]
    assert [p.when for p in ph] == sorted(p.when for p in ph)
    assert ph[2].deadline == ph[3].when  # topilma fazasi reja boshlangunga qadar


# ------------------------------------------------------------------------------------------------ baza
def test_store_dedupes_findings_and_plans(tmp_path):
    n, _ = make(tmp_path)
    f = {"kind": "github", "url": "https://github.com/x/y", "title": "t", "summary": "s"}
    assert n.store.add_finding("2026-11-08", f) and not n.store.add_finding("2026-11-08", f)
    assert n.store.add_finding("2026-11-09", f)  # boshqa tun — yana yoziladi
    assert n.store.add_plan("2026-11-08", {"title": "A"}) and not n.store.add_plan("2026-11-08", {"title": "A"})
    assert n.store.plan("2026-11-08")[0]["sources"] == []


# ------------------------------------------------------------------------------------------------ jadval
def test_discovery_phases_run_in_order_and_never_overlap(tmp_path):
    n, f = make(tmp_path)
    assert run(n.tick(local(2026, 11, 8, 20, 59))) == []  # hali vaqti emas
    assert run(n.tick(local(2026, 11, 8, 21, 0))) == ["started:2026-11-08:github"]
    assert "GitHub" in f.prompts[0] and "ideas_source" in f.prompts[0] and "ishonchsiz" in f.prompts[0]
    assert run(n.tick(local(2026, 11, 8, 22, 5))) == []  # github hali ishlayapti — internet kutadi
    f.active.clear()
    acts = run(n.tick(local(2026, 11, 8, 22, 10)))
    assert acts == ["done:2026-11-08:github", "started:2026-11-08:internet"]
    assert "Internet" in f.prompts[1]
    f.active.clear()
    run(n.tick(local(2026, 11, 8, 23, 0)))
    assert "YouTube" in f.prompts[2] and "KO'RILMAYDI" in f.prompts[2]


def test_plan_waits_for_discovery_then_runs(tmp_path):
    n, f = make(tmp_path)
    for t in ((21, 0), (22, 0), (23, 0)):
        run(n.tick(local(2026, 11, 8, *t)))
        f.active.clear()
    run(n.tick(local(2026, 11, 8, 23, 30)))
    acts = run(n.tick(local(2026, 11, 9, 0, 30)))
    assert "started:2026-11-08:plan" in acts and "REJA" in f.prompts[-1] and "ideas_plan" in f.prompts[-1]
    assert "tasdig'i bilan" in f.prompts[-1]


def test_missed_discovery_and_late_plan_after_agent_was_off(tmp_path):
    n, f = make(tmp_path)
    acts = run(n.tick(local(2026, 11, 9, 3, 0)))  # agent 03:00 da ishga tushdi
    assert {"missed:2026-11-08:github", "missed:2026-11-08:internet", "missed:2026-11-08:youtube",
            "started:2026-11-08:plan"} <= set(acts)
    assert n.job("2026-11-08:plan")["late"] == 1
    assert "o'tib ketdi" in n.job("2026-11-08:github")["note"]
    f.active.clear()
    run(n.tick(local(2026, 11, 9, 3, 30)))
    assert n.job("2026-11-08:plan")["status"] == "done"


def test_plan_missed_after_deadline(tmp_path):
    n, f = make(tmp_path)
    f.blocked = "Claude limiti tugagan"
    assert "blocked:2026-11-08:plan" in run(n.tick(local(2026, 11, 9, 1, 0)))  # limit — kutadi, topshiriq yuborilmaydi
    assert f.prompts == []
    run(n.tick(local(2026, 11, 9, 12, 30)))
    assert n.job("2026-11-08:plan")["status"] == "missed"


def test_disabled_does_nothing(tmp_path):
    n, f = make(tmp_path)
    n.set_enabled(False)
    assert run(n.tick(local(2026, 11, 8, 21, 0))) == [] and f.prompts == []
    assert "O‘CHIQ" in n.status_text(local(2026, 11, 8, 21, 0))
    n2, _ = make(tmp_path)  # sozlama faylda saqlanadi
    assert n2.cfg["enabled"] is False


# ------------------------------------------------------------------------------------------------ yuborish
def test_deliver_at_five_sends_excel_and_word_once(tmp_path):
    n, f = make(tmp_path)
    night = "2026-11-08"
    seed(n, night)
    n.job(f"{night}:plan")
    n._set(f"{night}:plan", status="done")
    for k in ("github", "internet", "youtube"):
        n._set(f"{night}:{k}", status="done") if n.job(f"{night}:{k}") else None
    assert "delivered:2026-11-08" not in run(n.tick(local(2026, 11, 9, 4, 59)))
    assert run(n.tick(local(2026, 11, 9, 5, 0))) == ["delivered:2026-11-08"]
    assert [x[0] for x in f.files] == ["SENTINEL_NIGHT_PLAN_2026-11-08.xlsx", "SENTINEL_NIGHT_PLAN_2026-11-08.docx"]
    assert "3 topilma, 2 ta yangi funksiya" in f.files[0][1] and "tasdiq" in f.files[0][1]
    assert run(n.tick(local(2026, 11, 9, 5, 5))) == []  # takror yuborilmaydi
    assert len(f.files) == 2


def test_deliver_waits_for_plan_until_noon_then_reports_honestly(tmp_path):
    n, f = make(tmp_path)
    night = "2026-11-08"
    n.job(f"{night}:plan")  # pending (reja hali bajarilmagan, masalan limit)
    f.blocked = "limit"
    run(n.tick(local(2026, 11, 9, 5, 0)))
    assert f.files == []  # 12:00 gacha kutadi
    run(n.tick(local(2026, 11, 9, 12, 5)))  # reja muddati o'tdi -> missed, hisobot "reja yo'q" deb yuboriladi
    assert len(f.files) == 2 and "reja fazasi holati" in n.job(f"{night}:deliver")["note"]


def test_failed_send_retries_then_gives_up(tmp_path):
    n, f = make(tmp_path)
    night = "2026-11-08"
    seed(n, night)
    n.job(f"{night}:plan")
    n._set(f"{night}:plan", status="done")
    f.send_ok = False
    for k in range(4):
        run(n.tick(local(2026, 11, 9, 5, k)))
    assert n.job(f"{night}:deliver")["status"] == "failed" and n.job(f"{night}:deliver")["attempts"] == 3
    assert len(f.files) == 6  # har urinishda 2 ta fayl


def test_rendered_files_are_valid_excel_and_word(tmp_path):
    from docx import Document
    from openpyxl import load_workbook
    n, _ = make(tmp_path)
    seed(n, "2026-11-08", plans=3, finds=4)
    x, d = nt.render_files(n.store, "2026-11-08", tmp_path / "out", "kechikkan: test")
    wb = load_workbook(x)
    assert wb.sheetnames == ["Rejalar", "Manbalar", "Xulosa"]
    rows = list(wb["Rejalar"].iter_rows(values_only=True))
    assert rows[0][2] == "Funksiya" and rows[1][2] == "Funksiya 0" and rows[1][-1] == "TASDIQ KUTILMOQDA" and len(rows) == 4
    assert [r[1] for r in rows[1:]] == [1, 2, 3]  # muhimlik bo'yicha
    assert len(list(wb["Manbalar"].iter_rows(values_only=True))) == 5
    assert any("kechikkan: test" in str(c) for r in wb["Xulosa"].iter_rows(values_only=True) for c in r)
    doc = Document(d)
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "tungi tadqiqot rejasi (2026-11-08)" in text and "Funksiya 2" in text and "TAKLIF" in text
    assert "YouTube videolari ko'rilmagan" in text and len(doc.tables[0].rows) == 5


def test_empty_night_report_is_honest(tmp_path):
    from docx import Document
    n, _ = make(tmp_path)
    _, d = nt.render_files(n.store, "2026-11-08", tmp_path / "out")
    assert "yetarli dalilli taklif tuzilmadi" in "\n".join(p.text for p in Document(d).paragraphs)


# ------------------------------------------------------------------------------------------------ tool'lar va buyruq
def test_ideas_tools_write_to_store_and_reject_bad_input(tmp_path):
    ctx = _ctx(tmp_path)
    r = run(ideas.ideas_source(ctx, {"kind": "github", "url": "https://github.com/a/b", "title": "t", "summary": "s",
                                     "relevance": 5}))
    assert r.ok and "saqlandi" in r.output
    assert "allaqachon" in run(ideas.ideas_source(ctx, {"kind": "github", "url": "https://github.com/a/b", "title": "t",
                                                         "summary": "s"})).output
    assert not run(ideas.ideas_source(ctx, {"kind": "web", "url": "javascript:alert(1)", "title": "t", "summary": "s"})).ok
    assert run(ideas.ideas_plan(ctx, {"title": "Yangi funksiya", "benefit": "b", "description": "d"})).ok
    assert not run(ideas.ideas_plan(ctx, {"title": " ", "benefit": "b", "description": "d"})).ok
    assert "https://github.com/a/b" in run(ideas.ideas_list(ctx, {})).output


def test_ideas_tools_are_registered_internal_not_dangerous():
    from agent import gate
    from agent.tools import ToolExecutor
    ex = ToolExecutor()
    for name in ("ideas_source", "ideas_plan", "ideas_list"):
        spec = ex.lookup(name)
        assert spec is not None
        assert spec.classify(None, {}).level == gate.INTERNAL
        assert spec.counts_as_work is False


def test_tun_command_status_toggle_and_report(tmp_path):
    from agent.bot import TelegramBot
    n, f = make(tmp_path)
    sent, files = [], []

    class Journal:
        def event(self, *a, **k):
            pass
    bot = TelegramBot.__new__(TelegramBot)
    bot.nightly, bot.journal = n, Journal()

    async def send_text(t, *a, **k):
        sent.append(t)

    async def send_file(p, caption=""):
        files.append(p.name)
    bot.send_text, bot.send_file = send_text, send_file
    run(bot._night_command("/tun", ""))
    assert "Tungi tadqiqot: YOQILGAN" in sent[-1] and "/tun on|off" in sent[-1]
    run(bot._night_command("/tun", "off"))
    assert "O‘CHIQ" in sent[-1] and n.cfg["enabled"] is False
    run(bot._night_command("/tun", "on"))
    seed(n, n.night_now())
    run(bot._night_command("/tun_hisobot", ""))
    assert len(files) == 2 and files[0].endswith(".xlsx") and files[1].endswith(".docx")
    bot.nightly = None
    run(bot._night_command("/tun", ""))
    assert "ishga tushmagan" in sent[-1]


def test_nightly_module_has_no_trading_or_order_code():
    import inspect
    src = inspect.getsource(nt) + inspect.getsource(ideas)
    for bad in ("order_send", "MetaTrader5", "subprocess", "os.system", "bot_env", "token"):
        assert bad not in src, bad


def test_night_started_before_installation_is_skipped_without_empty_report(tmp_path):
    n, f = make(tmp_path, installed=local(2026, 11, 9, 0, 10))  # agent yarim tundan keyin birinchi marta ishga tushdi
    acts = run(n.tick(local(2026, 11, 9, 5, 0)))
    assert f.prompts == [] and f.files == [] and "started:2026-11-08:plan" not in acts
    assert n.job("2026-11-08:deliver")["status"] == "skipped"
    assert "skipped" not in str(run(n.tick(local(2026, 11, 9, 21, 0))))  # keyingi tun odatdagidek boshlanadi
    assert run(n.tick(local(2026, 11, 9, 21, 0))) == [] and len(f.prompts) == 1 and "GitHub" in f.prompts[0]


def test_first_run_at_evening_does_not_report_previous_night(tmp_path):
    n, f = make(tmp_path, installed=local(2026, 11, 8, 20, 0))
    acts = run(n.tick(local(2026, 11, 8, 21, 0)))
    assert acts == ["started:2026-11-08:github"] and f.files == []


def test_per_night_override_shifts_phases_and_prevents_skip(tmp_path):
    n, f = make(tmp_path, installed=local(2026, 11, 9, 0, 25))
    n.cfg["overrides"] = {"2026-11-08": {"discovery": [["github", "00:30"], ["internet", "01:00"], ["youtube", "01:30"]],
                                          "plan_at": "02:00"}}
    ph = n.phases("2026-11-08")
    assert [p.when for p in ph[:4]] == [local(2026, 11, 9, 0, 30), local(2026, 11, 9, 1, 0), local(2026, 11, 9, 1, 30),
                                        local(2026, 11, 9, 2, 0)]
    assert run(n.tick(local(2026, 11, 9, 0, 30))) == ["started:2026-11-08:github"]  # o'rnatishdan keyin — o'tkazib yuborilmaydi
    assert n.phases("2026-11-09")[0].when == local(2026, 11, 9, 21)  # boshqa tunlar o'zgarmaydi
