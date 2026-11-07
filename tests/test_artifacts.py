"""V15 — Task Intelligence & Quality Control: faol ish konteksti, Excel formulalari, artefakt tekshiruvi, holat.

Regressiya testlari A–F (06.11 dagi smeta voqeasi asosida):
  A — Excel smeta formulalar bilan yaratiladi; tekshirilmasa SUCCESS emas, tekshirilsa SUCCESS.
  B — "ИТОГО суммасини чиқар": AYNAN o'sha fayl o'zgaradi, ko'rinadigan ИТОГО qatori (SUM formula) qo'shiladi;
      faqat chatda javob berilsa — PARTIAL.
  C — "Тайёр файл қилиб бер": oxirgi tasdiqlangan versiya yuboriladi, formulalar yo'qolmaydi, jami ko'rinadi.
  D — Kichik o'zgarish: boshqa hech narsa o'zgarmaydi; formulani songa almashtirish aniqlanadi.
  E — Hisob/tekshiruv xatosi: SUCCESS berilmaydi, fayl yuborilmaydi.
  F — Qisqa follow-up faol faylga bog'lanadi; keraksiz savol berilmaydi; noaniqlikda savol ruxsat.
Testlar Telegram va Claude'ga ulanmaydi: agentning tool chaqiruvlari ToolExecutor orqali, natija esa AgentRunner'ning
haqiqiy _prepare_artifacts / _wrapup_reminder / _finalize kodi bilan tekshiriladi.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import openpyxl
import pytest

from agent.artifacts import intent, sha256, validate, xlsx
from agent.artifacts.formula import Evaluator, Unsupported, XLError, parse
from agent.artifacts.store import ActiveTaskStore
from agent.config import Config
from agent.inventory import Inventory
from agent.journal import Journal
from agent.loop import AgentRunner, TaskRequest, TaskStatus
from agent.redact import Redactor
from agent.tools import ToolContext, ToolExecutor
from agent.verification import Facts, decide
from agent.workspace import ensure_workspace

ITEMS = [("Intel Core i7-14700KF", 400), ("Gigabyte Z790", 275), ("Cooler L360", 125), ("DDR5 32GB 5600", 625),
         ("ASUS RTX 5060 (1)", 638), ("ASUS RTX 5060 (2)", 638), ("PSU 750W", 63), ("Case 4 fan", 100),
         ("SSD Samsung 1TB", 245)]  # 1 ПК = 3109 $


# ------------------------------------------------------------------------------------------------ yordamchilar
class FakeChannel:
    def __init__(self):
        self.files: list[tuple[Path, str, str]] = []
        self.texts: list[str] = []
        self.questions: list[str] = []

    async def send(self, text: str) -> None:
        self.texts.append(text)

    async def send_file(self, path: Path, caption: str = "") -> None:
        self.files.append((Path(path), caption, sha256(path)))

    async def send_video(self, path, caption="", buttons=None) -> None:
        pass

    async def request_approval(self, text: str) -> bool:
        return False

    async def ask(self, question: str) -> str | None:
        self.questions.append(question)
        return "birinchisi"

    async def request_secret(self, prompt: str) -> str | None:
        return None


class Agent:
    """Bitta agent: har topshiriq — yangi ToolContext, lekin bir xil AGENT_HOME (faol ish konteksti saqlanadi)."""

    def __init__(self, home: Path):
        self.cfg = Config(agent_home=home)
        self.paths = ensure_workspace(home)
        self.inventory = Inventory(self.paths.inventory_json)
        self.redactor = Redactor(self.inventory.secret_values)
        self.journal = Journal(self.paths.jurnal, self.redactor)
        self.runner = AgentRunner(self.cfg, self.paths, ToolExecutor(), self.inventory, self.redactor, self.journal)
        self.n = 0

    def task(self, text: str, notes: list[str] | None = None):
        self.n += 1
        req = TaskRequest(id=f"T-TEST-{self.n:02d}", text=text, notes=list(notes or []))
        ctx = ToolContext(task_id=req.id, cfg=self.cfg, paths=self.paths, inventory=self.inventory,
                          redactor=self.redactor, journal=self.journal, channel=FakeChannel())
        prompt = self.runner._prepare_artifacts(req, ctx)  # noqa: SLF001
        return req, ctx, prompt

    def tool(self, ctx: ToolContext, name: str, args: dict) -> tuple[str, bool]:
        return asyncio.run(self.runner.executor.execute(ctx, name, args))

    def finish(self, req, ctx, text: str = "Holat: SUCCESS\nTayyor."):
        return self.runner._finalize(req, ctx, TaskStatus(), text, "ok")  # noqa: SLF001


@pytest.fixture()
def agent(tmp_path, monkeypatch):
    # Kuzatuv haqiqiy Desktop/Documents ga tegmasin.
    monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: tmp_path / "user"))
    return Agent(tmp_path / "home")


def build_estimate(path: Path, rate: float = 12100) -> Path:
    """Agent skripti yasaydigan smeta: komponentlar, 1 ПК jami, soni, 2 ПК jami, kurs, yakuniy so'm, НДС holati."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Смета"
    ws["A1"] = "Смета: ПК йиғиш"
    ws["A3"], ws["B3"] = "Курс (сўм)", rate
    ws["A4"], ws["B4"] = "ПК сони", 2
    for i, h in enumerate(["№", "Номи", "Нарх, $ (1 ПК)"], 1):
        ws.cell(row=6, column=i, value=h)
    for n, (name, price) in enumerate(ITEMS, 1):
        ws.cell(row=6 + n, column=1, value=n)
        ws.cell(row=6 + n, column=2, value=name)
        ws.cell(row=6 + n, column=3, value=price).number_format = "#,##0"
    rows = [("1 ПК жами, $", "=SUM(C7:C15)"), ("ПК сони", "=B4"), ("2 ПК жами, $", "=C16*C17"),
            ("Курс, сўм", "=B3"), ("ИТОГО, сўм (НДС сиз)", "=C18*C19")]
    for k, (label, formula) in enumerate(rows):
        ws.cell(row=16 + k, column=2, value=label)
        ws.cell(row=16 + k, column=3, value=formula).number_format = "#,##0"
    ws["B21"] = "НДС: ҳисобланмаган (НДС сиз)"
    ws["B21"].font = openpyxl.styles.Font(italic=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def build_items_without_total(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Нархлар"
    for i, h in enumerate(["№", "Номи", "Нарх", "Сони", "Сумма"], 1):
        ws.cell(row=1, column=i, value=h)
    data = [("Монитор", 150, 2), ("Клавиатура", 20, 5), ("Сичқонча", 10, 5), ("Кабель", 3.5, 10)]
    for r, (name, price, qty) in enumerate(data, start=2):
        ws.cell(row=r, column=1, value=r - 1)
        ws.cell(row=r, column=2, value=name)
        ws.cell(row=r, column=3, value=price)
        ws.cell(row=r, column=4, value=qty)
        ws.cell(row=r, column=5, value=f"=C{r}*D{r}").number_format = "#,##0.00"
    ws["G1"] = "Изоҳ: нархлар $ да"
    ws.column_dimensions["B"].width = 30
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


EXPECT = [{"label": "1 ПК жами", "value": 3109}, {"label": "2 ПК жами", "value": 6218},
          {"label": "ИТОГО, сўм", "value": 75237800}]


def status_line(outcome) -> str:
    return outcome.text.splitlines()[0]


# ------------------------------------------------------------------------------------------------ formula hisoblagichi
def _eval(formula: str, cells: dict | None = None, sheets: tuple = ("S",)):
    wb = openpyxl.Workbook()
    wb.active.title = sheets[0]
    for extra in sheets[1:]:
        wb.create_sheet(extra)
    for ref, v in (cells or {}).items():
        sheet, coord = ref.split("!") if "!" in ref else (sheets[0], ref)
        wb[sheet][coord] = v
    wb[sheets[0]]["Z99"] = formula
    return Evaluator(wb).cell(sheets[0], 99, 26)


def test_formula_engine_arithmetic_and_functions():
    assert _eval("=2+3*4") == 14
    assert _eval("=-2^2") == 4  # Excel: inkor darajadan oldin
    assert _eval("=50%") == 0.5
    assert _eval('="a"&1&TRUE') == "a1TRUE"
    assert _eval("=SUM(A1:A4)", {"A1": 1, "A2": "matn", "A3": None, "A4": 2.5}) == 3.5
    assert _eval("=ROUND(2.5,0)") == 3 and _eval("=ROUND(-2.5,0)") == -3 and _eval("=ROUND(1234.567,-2)") == 1200
    assert _eval("=IF(A1>1,\"katta\",\"kichik\")", {"A1": 5}) == "katta"
    assert _eval("=1/0") == XLError("#DIV/0!")
    assert _eval("=IFERROR(1/0,7)") == 7
    assert _eval("=SUMIF(A1:A3,\">1\",B1:B3)", {"A1": 1, "A2": 2, "A3": 3, "B1": 10, "B2": 20, "B3": 30}) == 50
    assert _eval("='Курс варақ'!B3*2", {"Курс варақ!B3": 12100}, sheets=("S", "Курс варақ")) == 24200
    assert _eval("=SUMPRODUCT(A1:A2,B1:B2)", {"A1": 2, "A2": 3, "B1": 4, "B2": 5}) == 23


def test_formula_engine_refuses_what_it_cannot_prove():
    with pytest.raises(Unsupported):
        _eval("=VLOOKUP(1,A1:B2,2,FALSE)")
    with pytest.raises(Unsupported):
        _eval("=Z99+1")  # aylanma havola
    with pytest.raises(Unsupported):
        parse("={1,2,3}")


# ------------------------------------------------------------------------------------------------ kesh qiymatlar
def test_cached_values_keep_formulas_styles_and_open_cleanly(tmp_path):
    p = build_estimate(tmp_path / "s.xlsx")
    assert openpyxl.load_workbook(p, data_only=True).active["C20"].value is None  # openpyxl: natija yo'q (muammo)
    rep = xlsx.write_cached_values(p)
    assert rep.formulas == 5 and rep.written == 5 and not rep.unsupported and not rep.errors
    vals = openpyxl.load_workbook(p, data_only=True).active
    forms = openpyxl.load_workbook(p).active
    assert vals["C20"].value == 75237800 and vals["C18"].value == 6218 and vals["C16"].value == 3109
    assert forms["C20"].value == "=C18*C19" and forms["C16"].value == "=SUM(C7:C15)"  # formula joyida
    assert forms["B21"].font.italic and forms["C20"].number_format == "#,##0"
    assert 'fullCalcOnLoad="1"' in zipfile.ZipFile(p).read("xl/workbook.xml").decode()
    assert xlsx.missing_cache(p) == []
    before = sha256(p)
    assert xlsx.write_cached_values(p).changed is False and sha256(p) == before  # takroriy chaqiruv faylga tegmaydi
    assert openpyxl.load_workbook(p).active["C20"].value == "=C18*C19"


def _excel_available() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID").Close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _excel_available(), reason="Microsoft Excel o'rnatilmagan")
def test_real_excel_opens_cached_file_and_agrees(tmp_path):
    """Mustaqil hisoblash dvigateli sifatida haqiqiy Excel: fayl ta'mirsiz ochiladi va qiymatlar bir xil."""
    p = build_estimate(tmp_path / "excel_check.xlsx")
    xlsx.write_cached_values(p)
    vbs = tmp_path / "check.vbs"
    vbs.write_text(
        'Set xl = CreateObject("Excel.Application")\nxl.Visible = False\nxl.DisplayAlerts = False\n'
        'On Error Resume Next\nSet wb = xl.Workbooks.Open(WScript.Arguments(0), 0, True)\n'
        'If Err.Number <> 0 Then\n WScript.Echo "ERR " & Err.Description\nElse\n Set ws = wb.Worksheets(1)\n'
        ' WScript.Echo ws.Range("C16").Value2 & "|" & ws.Range("C18").Value2 & "|" & ws.Range("C20").Value2 & "|" & '
        'ws.Range("C20").Formula\n wb.Close False\nEnd If\nxl.Quit\n', encoding="ascii")
    out = subprocess.run(["cscript", "//nologo", str(vbs), str(p)], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip() == "3109|6218|75237800|=C18*C19", out.stdout + out.stderr


# ------------------------------------------------------------------------------------------------ A
def test_A_estimate_created_with_formulas_needs_validation_for_success(agent):
    req, ctx, prompt = agent.task("Excel smeta tayyorla: i7 14700kf 400$, ... 2 ta PK, kurs 12100")
    assert ctx.resolution is not None and not ctx.resolution.followup
    path = build_estimate(agent.paths.ish / "smeta_2_pc.xlsx")  # agent skripti
    agent.tool(ctx, "write_file", {"path": f"ish/{req.id}/skript.py", "content": "# smeta skripti"})  # kuzatuv ishga tushadi
    assert str(path.resolve()) in ctx.tracker.changed

    unverified = agent.finish(req, ctx)
    assert "PARTIAL" in status_line(unverified) and "fayl tekshirilmagan: smeta_2_pc.xlsx" in status_line(unverified)

    req, ctx, _ = agent.task("Excel smeta tayyorla (qayta)")
    build_estimate(path)
    text, is_err = agent.tool(ctx, "verify_artifact", {"path": str(path), "expect": EXPECT, "require_labels": ["НДС"]})
    assert not is_err and "PASS ✅" in text and "75 237 800" in text
    assert openpyxl.load_workbook(path, data_only=True).active["C20"].value == 75237800  # endi ko'rinadi
    assert openpyxl.load_workbook(path).active["C20"].value == "=C18*C19"
    out = agent.finish(req, ctx)
    assert status_line(out).startswith("✅ Holat: SUCCESS")
    store = ActiveTaskStore(agent.paths.ish)
    assert store.active_file() == path.resolve()
    assert store.latest_verified(path)["sha"] == sha256(path)


# ------------------------------------------------------------------------------------------------ B
def _items_task(agent) -> Path:
    req, ctx, _ = agent.task("Нархлар жадвалини Excel қилиб бер")
    path = build_items_without_total(agent.paths.ish / "narxlar.xlsx")
    agent.tool(ctx, "verify_artifact", {"path": str(path)})
    agent.tool(ctx, "notify_owner", {"text": "Тайёр", "file_path": str(path)})
    assert status_line(agent.finish(req, ctx)).startswith("✅ Holat: SUCCESS")
    return path


def test_B_itogo_followup_answered_only_in_chat_is_not_success(agent):
    path = _items_task(agent)
    req, ctx, prompt = agent.task("ИТОГО суммасини чиқазиб бер буни")
    assert ctx.resolution.followup and ctx.resolution.modify and ctx.resolution.file == path.resolve()
    assert "FAOL ISHNING DAVOMI" in prompt and str(path.resolve()) in prompt and "AYNAN shu faylga" in prompt
    assert any("faol ishga tegishli" in n for n in req.notes)
    reminder = agent.runner._wrapup_reminder(ctx, matched_skill=True)  # noqa: SLF001
    assert reminder and "O'ZGARMADI" in reminder
    out = agent.finish(req, ctx, "Holat: SUCCESS\nУмумий сумма: 485 $")
    assert "PARTIAL" in status_line(out) and "faylga kiritilmadi" in status_line(out)
    assert ActiveTaskStore(agent.paths.ish).active["pending"]  # keyingi xabarda ham eslanadi


def test_B_itogo_followup_modifies_same_workbook_with_visible_total(agent):
    path = _items_task(agent)
    files_before = sorted(p.name for p in agent.paths.ish.glob("*.xlsx"))
    req, ctx, _ = agent.task("ИТОГО суммасини чиқар")
    text, is_err = agent.tool(ctx, "excel_total", {"currency": "USD"})  # path yo'q — faol fayl
    assert not is_err, text
    assert sorted(p.name for p in agent.paths.ish.glob("*.xlsx")) == files_before  # yangi fayl yaratilmadi
    ws = openpyxl.load_workbook(path).active
    assert ws["B6"].value == "ИТОГО" and ws["E6"].value == "=SUM(E2:E5)"
    assert ws["E6"].font.b and ws["E6"].fill.fgColor.rgb.endswith("FFE699") and "$" in ws["E6"].number_format
    assert openpyxl.load_workbook(path, data_only=True).active["E6"].value == 485  # 300+100+50+35, ko'rinadi
    assert ws["E2"].value == "=C2*D2" and ws["G1"].value == "Изоҳ: нархлар $ да"  # qolgan narsa joyida
    snapshots = list((agent.paths.ish / "versiyalar").rglob("*.xlsx"))
    assert snapshots and any(openpyxl.load_workbook(s).active["E6"].value is None for s in snapshots)  # eski versiya bor
    text, _ = agent.tool(ctx, "notify_owner", {"text": "ИТОГО қўшилди", "file_path": str(path)})
    assert "Fayl yuborildi" in text
    out = agent.finish(req, ctx, "Holat: SUCCESS\nИТОГО: 485 $")
    assert status_line(out).startswith("✅ Holat: SUCCESS") and "📎 narxlar.xlsx ✅" in out.text


def test_B_existing_totals_are_not_duplicated(agent, tmp_path):
    p = build_estimate(tmp_path / "e.xlsx")
    res = xlsx.add_total_row(p, amount_columns=["C"])
    assert res.ok and res.existed and res.row == 16
    assert openpyxl.load_workbook(p).active["B22"].value is None  # ikkinchi ИТОГО qo'shilmadi


# ------------------------------------------------------------------------------------------------ C
def test_C_ready_file_delivers_latest_verified_version_without_losing_formulas(agent):
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    path = build_estimate(agent.paths.ish / "smeta_2_pc.xlsx")
    agent.tool(ctx, "verify_artifact", {"path": str(path), "expect": EXPECT})
    agent.finish(req, ctx)

    req, ctx, prompt = agent.task("хоп тайор файл килиб бер")
    assert ctx.resolution.followup and ctx.resolution.deliver_only and "Faylni qaytadan YARATMA" in prompt
    text, is_err = agent.tool(ctx, "notify_owner", {"text": "Тайёр смета", "file_path": str(path)})
    assert not is_err and "oxirgi TASDIQLANGAN versiya" in text
    sent_path, _caption, sent_sha = ctx.channel.files[-1]
    assert sent_path == path and sent_sha == ActiveTaskStore(agent.paths.ish).latest_verified(path)["sha"]
    assert openpyxl.load_workbook(sent_path).active["C20"].value == "=C18*C19"
    assert openpyxl.load_workbook(sent_path, data_only=True).active["C20"].value == 75237800
    out = agent.finish(req, ctx)
    assert status_line(out).startswith("✅ Holat: SUCCESS")


def test_C_delivery_fixes_blank_totals_automatically(agent):
    """06.11 voqeasi: formulali fayl natijasiz yuborilgan va Telegram'da ИТОГО bo'sh ko'ringan."""
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    assert xlsx.missing_cache(path)
    text, is_err = agent.tool(ctx, "notify_owner", {"text": "Смета", "file_path": str(path)})
    assert not is_err and "kesh qiymat" in text
    assert openpyxl.load_workbook(ctx.channel.files[-1][0], data_only=True).active["C20"].value == 75237800


# ------------------------------------------------------------------------------------------------ D
def test_D_minor_change_preserves_unrelated_content(agent):
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    agent.tool(ctx, "verify_artifact", {"path": str(path), "expect": EXPECT})
    agent.finish(req, ctx)

    req, ctx, _ = agent.task("курсни 12200 га ўзгартир")
    assert ctx.resolution.file == path.resolve()
    wb = openpyxl.load_workbook(path)  # agent skripti: faqat bitta katak
    wb.active["B3"] = 12200
    wb.save(path)
    text, is_err = agent.tool(ctx, "verify_artifact", {"expect": [{"label": "ИТОГО, сўм", "value": 6218 * 12200}]})
    assert not is_err and "PASS ✅" in text
    d = xlsx.diff(ActiveTaskStore(agent.paths.ish).latest_snapshot(path, exclude_sha=sha256(path)), path)
    assert d["cells_changed"] == ["Смета!B3"] and not d["formulas_removed"] and not d["formulas_to_constants"]
    assert not d["cells_cleared"] and not d["sheets_removed"]
    assert status_line(agent.finish(req, ctx)).startswith("✅ Holat: SUCCESS")


def test_D_replacing_formulas_with_numbers_is_detected(agent):
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    agent.tool(ctx, "verify_artifact", {"path": str(path)})
    agent.finish(req, ctx)

    req, ctx, _ = agent.task("Итого суммаларини ёз")
    vals = {"C16": 3109, "C17": 2, "C18": 6218, "C19": 12100, "C20": 75237800}
    wb = openpyxl.load_workbook(path)  # 06.11 dagi xato: formulalar o'rniga tayyor raqam
    for coord, v in vals.items():
        wb.active[coord] = v
    wb.save(path)
    text, is_err = agent.tool(ctx, "verify_artifact", {})
    assert is_err and "formula o'chgan yoki songa almashgan" in text
    out = agent.finish(req, ctx)
    assert "FAILED" in status_line(out) and "SUCCESS" not in status_line(out)


# ------------------------------------------------------------------------------------------------ E
def test_E_calculation_error_blocks_delivery_and_success(agent):
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    wb = openpyxl.load_workbook(path)
    wb.active["C19"] = "=B3/B5"  # B5 bo'sh -> #DIV/0!
    wb.save(path)
    text, is_err = agent.tool(ctx, "notify_owner", {"text": "Смета", "file_path": str(path)})
    assert is_err and "YUBORILMADI" in text and "#DIV/0!" in text
    assert ctx.channel.files == []
    out = agent.finish(req, ctx)
    assert "FAILED" in status_line(out)


def test_E_wrong_expected_total_is_failure(agent):
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    path = build_estimate(agent.paths.ish / "smeta.xlsx", rate=1210)  # kursda xato
    text, is_err = agent.tool(ctx, "verify_artifact", {"path": str(path), "expect": EXPECT})
    assert is_err and "kutilgan 75 237 800" in text
    out = agent.finish(req, ctx, "Holat: SUCCESS\nТайёр.")
    assert "FAILED" in status_line(out)


def test_E_unprovable_formula_is_partial_not_success(agent):
    req, ctx, _ = agent.task("Excel jadval tayyorla")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    wb = openpyxl.load_workbook(path)
    wb.active["D7"] = "=VLOOKUP(B7,B7:C15,2,FALSE)"
    wb.save(path)
    text, is_err = agent.tool(ctx, "verify_artifact", {"path": str(path)})
    assert not is_err and "qisman" in text
    assert "PARTIAL" in status_line(agent.finish(req, ctx))


def test_status_rules_for_artifacts():
    base = dict(mutated=False, verified=True, verify_failed=False, run_code="ok")
    assert decide("SUCCESS", Facts(**base)) == ("SUCCESS", None)
    assert decide("SUCCESS", Facts(**base, artifacts_unverified=("a.xlsx",)))[0] == "PARTIAL"
    assert decide("SUCCESS", Facts(**base, artifacts_failed=("a.xlsx",)))[0] == "FAILED"
    assert decide(None, Facts(**base, followup_unapplied=True))[0] == "PARTIAL"
    assert decide("NEEDS_AUTH", Facts(**base, artifacts_unverified=("a.xlsx",))) == ("NEEDS_AUTH", None)


# ------------------------------------------------------------------------------------------------ F
def test_F_short_followup_resolves_active_artifact_without_asking(agent):
    _items_task(agent)
    for text in ("шуни ўзгартир", "тўғрилаб бер", "ИТОГО қўш", "Тайёр файлни юбор"):
        req, ctx, _ = agent.task(text)
        assert ctx.resolution.followup and ctx.resolution.file.name == "narxlar.xlsx", text
        out, _ = agent.tool(ctx, "ask_owner", {"question": "Қайси файлни ўзгартирай?"})
        assert "so'ralmadi" in out and ctx.channel.questions == [], text


def test_F_kind_mismatch_picks_matching_recent_file(agent):
    req, ctx, _ = agent.task("Excel smeta tayyorla")
    smeta = build_estimate(agent.paths.ish / "smeta.xlsx")
    agent.tool(ctx, "verify_artifact", {"path": str(smeta)})
    agent.finish(req, ctx)
    req, ctx, _ = agent.task("Telekomga xat yozib ber (Word)")
    import docx

    letter = agent.paths.ish / "xat.docx"
    d = docx.Document()
    d.add_paragraph("Hurmatli rahbar!")
    d.save(letter)
    agent.tool(ctx, "notify_owner", {"text": "Xat", "file_path": str(letter)})
    agent.finish(req, ctx)
    assert ActiveTaskStore(agent.paths.ish).active_file() == letter.resolve()
    req, ctx, _ = agent.task("сметадаги курсни тўғрилаб бер")
    assert ctx.resolution.followup and ctx.resolution.file == smeta.resolve()


def test_F_ambiguous_followup_allows_one_question(agent):
    for name in ("smeta_a.xlsx", "smeta_b.xlsx"):
        req, ctx, _ = agent.task(f"{name} Excel smeta tayyorla")
        p = build_estimate(agent.paths.ish / name)
        agent.tool(ctx, "verify_artifact", {"path": str(p)})
        agent.finish(req, ctx)
    store = ActiveTaskStore(agent.paths.ish)
    store.data["active"]["file"] = None  # faol fayl noma'lum, ikkita mos fayl
    store.save()
    req, ctx, prompt = agent.task("сметани тўғрилаб бер")
    assert ctx.resolution.ambiguous and "BITTA qisqa savol" in prompt
    out, _ = agent.tool(ctx, "ask_owner", {"question": "Qaysi smetani?"})
    assert "Jamshid javobi" in out and ctx.channel.questions


def test_F_unrelated_message_is_not_a_followup(agent):
    _items_task(agent)
    req, ctx, prompt = agent.task("bu kompyuterda C diskda qancha joy bor?")
    assert not ctx.resolution.followup and "FAOL ISHNING DAVOMI" not in prompt
    assert "Oldingi ishchi fayl" in prompt and "narxlar.xlsx" in prompt  # kontekstda bor, lekin majburlanmaydi
    agent.finish(req, ctx, "C: 17 GB bo'sh")
    req, ctx, prompt = agent.task("ИТОГО қўш")  # oraliq savoldan keyin ham oldingi faylga bog'lanadi
    assert ctx.resolution.followup and ctx.resolution.file.name == "narxlar.xlsx"


def test_F_attached_file_becomes_active(agent):
    inbox = agent.paths.ish / "inbox"
    p = build_items_without_total(inbox / "20261106_narx.xlsx")
    note = f"[Fayl biriktirildi: {p} ({p.stat().st_size} bayt, application/vnd.ms-excel) — read_file bilan o'qing]"
    req, ctx, prompt = agent.task("шунга итого қўшиб бер", notes=[note])
    assert ctx.resolution.file == p and "Jamshid fayl yubordi" in prompt
    text, is_err = agent.tool(ctx, "excel_total", {})
    assert not is_err and openpyxl.load_workbook(p).active["E6"].value == "=SUM(E2:E5)"


# ------------------------------------------------------------------------------------------------ boshqa
def test_read_file_shows_computed_totals_instead_of_blanks(agent):
    req, ctx, _ = agent.task("smetani o'qi")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    text, is_err = agent.tool(ctx, "read_file", {"path": str(path)})
    assert not is_err and "75237800" in text and "kod hisoblab" in text


def test_inspect_artifact_reports_structure(agent):
    req, ctx, _ = agent.task("smetani ko'r")
    path = build_estimate(agent.paths.ish / "smeta.xlsx")
    text, is_err = agent.tool(ctx, "inspect_artifact", {"path": str(path)})
    assert not is_err and "C20==C18*C19 → 75 237 800" in text and "Jami qatorlari" in text


def test_store_keeps_versions_and_recovers(agent, tmp_path):
    store = ActiveTaskStore(agent.paths.ish)
    p = build_estimate(tmp_path / "v.xlsx")
    store.start_task("T1", "smeta", followup=False, file=p)
    first = store.record_version(p, "T1", verified=True, summary="ok")
    build_estimate(p, rate=13000)
    second = store.record_version(p, "T2")
    assert first["sha"] != second["sha"] and Path(first["snapshot"]).is_file()
    assert store.latest_verified(p)["sha"] == first["sha"]
    restored = tmp_path / "restored.xlsx"
    shutil.copy2(first["snapshot"], restored)
    assert openpyxl.load_workbook(restored).active["B3"].value == 12100
    store.save()
    assert json.loads((agent.paths.ish / "aktiv_ish.json").read_text(encoding="utf-8"))["active"]["task_id"] == "T1"


def test_validate_reports_lost_chart_parts(tmp_path):
    from openpyxl.chart import BarChart, Reference

    p = build_items_without_total(tmp_path / "chart.xlsx")
    wb = openpyxl.load_workbook(p)
    ch = BarChart()
    ch.add_data(Reference(wb.active, min_col=3, min_row=1, max_row=5), titles_from_data=True)
    wb.active.add_chart(ch, "I2")
    wb.save(p)
    assert xlsx.risky_parts(p).get("charts") == 1
    res = xlsx.add_total_row(p)
    assert not res.ok and "charts" in res.message  # grafikni yo'qotib qo'ymaslik uchun o'zgartirilmadi
    plain = build_items_without_total(tmp_path / "plain.xlsx")
    rep = validate.validate(plain, previous=p)
    assert not rep.ok and any("grafik" in c.name and not c.ok for c in rep.checks)


def test_intent_signals():
    store_dir = Path(__file__).parent  # faqat API tekshiruvi: store bo'sh bo'lsa follow-up yo'q
    del store_dir
    assert intent.MODIFY.search(intent.normalize("Итого суммаларини йооз"))
    assert intent.DELIVER.search(intent.normalize("хоп тайор файл килиб бер"))
    assert not intent.MODIFY.search(intent.normalize("хоп тайор файл килиб бер"))
    assert intent.DEICTIC.search(intent.normalize("буни тўғрила")) and not intent.DEICTIC.search("bu kompyuter")


def test_header_with_total_word_is_not_an_empty_total_row(tmp_path):
    """Jonli sinovda topilgan: "Жами 2 ПК, $" ustun sarlavhasi bo'sh jami qatori deb FAIL berilgan edi."""
    wb = openpyxl.Workbook()
    ws = wb.active
    for i, h in enumerate(["№", "Номи", "Нарх 1 ПК, $", "Жами 2 ПК, $"], 1):
        ws.cell(row=1, column=i, value=h)
    ws["A2"], ws["B2"], ws["C2"], ws["D2"] = 1, "CPU", 400, "=C2*2"
    ws["B3"], ws["D3"] = "ИТОГО", "=SUM(D2:D2)"
    p = tmp_path / "h.xlsx"
    wb.save(p)
    xlsx.write_cached_values(p)
    rep = validate.validate(p, expect=[{"label": "ИТОГО", "value": 800}])
    assert rep.verified, rep.summary()
    assert [t["row"] for t in rep.totals] == [3]
