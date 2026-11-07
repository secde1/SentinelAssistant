"""Artefakt tekshiruvi (validation): fayl haqiqatan to'g'ri va foydalanishga yaroqlimi.

Natija uch xil:
  ok=False         — QATTIQ xato: fayl ochilmaydi, formula xato beradi (#REF!, #DIV/0!...), kutilgan qiymat mos emas,
                     oldingi versiyadagi formula/varaq/grafik yo'qolgan, jami ko'rinmaydi. Bunday fayl YUBORILMAYDI;
  ok=True, verified=False — xato yo'q, lekin hammasi isbotlanmadi (masalan, ba'zi formulalarni hisoblagich
                     qo'llab-quvvatlamaydi) — holat SUCCESS bo'la olmaydi, PARTIAL;
  ok=True, verified=True  — tasdiqlangan versiya.
"""
from __future__ import annotations

import csv
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import EXCEL_EXT, sha256
from . import xlsx


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    hard: bool = True  # False — faqat ogohlantirish (verified ni tushiradi, yuborishni to'xtatmaydi)


@dataclass
class Report:
    path: str
    sha: str = ""
    checks: list[Check] = field(default_factory=list)
    totals: list[dict] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks if c.hard)

    @property
    def verified(self) -> bool:
        return self.ok and all(c.ok for c in self.checks)

    @property
    def problems(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def add(self, name: str, ok: bool, detail: str = "", hard: bool = True) -> None:
        self.checks.append(Check(name, ok, detail, hard))

    def summary(self) -> str:
        verdict = "PASS ✅" if self.verified else ("PASS (qisman) ⚠️" if self.ok else "FAIL ❌")
        lines = [f"ARTEFAKT TEKSHIRUVI {verdict}: {Path(self.path).name} (sha {self.sha[:10]})"]
        for c in self.checks:
            mark = "✓" if c.ok else ("✗" if c.hard else "!")
            lines.append(f"  {mark} {c.name}{': ' + c.detail if c.detail else ''}")
        if self.totals:
            lines.append("  Jami qatorlari (fayl ichida ko'rinadi):")
            for t in self.totals[:8]:
                nums = ", ".join(f"{n['cell']}={xlsx.fmt_num(n['value']) if n['value'] is not None else '?'}"
                                 for n in t["numbers"])
                lines.append(f"    {t['sheet']}!{t['row']} '{t['label']}': {nums}")
        return "\n".join(lines)


def _expect_match(totals_rows: list[dict], all_rows: list[dict], exp: dict) -> tuple[bool, str]:
    label = xlsx.normalize(exp.get("label", ""))
    value = exp.get("value")
    tol = exp.get("tolerance")
    if not label or not isinstance(value, (int, float)):
        return False, f"noto'g'ri expect: {exp}"
    tol = float(tol) if isinstance(tol, (int, float)) else max(0.01, abs(float(value)) * 1e-9)
    sheet = exp.get("sheet")
    found = []
    for row in all_rows:
        if sheet and row["sheet"] != sheet:
            continue
        if label not in xlsx.normalize(row["label"]):
            continue
        for n in row["numbers"]:
            v = n["value"]
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                found.append(f"{row['sheet']}!{n['cell']}={xlsx.fmt_num(v)}")
                if abs(float(v) - float(value)) <= tol:
                    return True, f"'{exp['label']}' = {xlsx.fmt_num(v)} ({row['sheet']}!{n['cell']})"
    if not found:
        return False, f"'{exp['label']}' yozuvli qator yoki uning yonida raqam topilmadi"
    return False, f"'{exp['label']}': kutilgan {xlsx.fmt_num(value)}, faylda {', '.join(found[:4])}"


def _rows_with_labels(path: Path, values: dict[str, Any]) -> list[dict]:
    """Har qator: birinchi matnli katak — yorliq, formulali/sonli kataklar — raqamlar (expect uchun)."""
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=False)
    try:
        out = []
        for ws in wb.worksheets:
            rows: dict[int, list] = {}
            for (r, _c), cell in sorted(ws._cells.items()):  # noqa: SLF001
                rows.setdefault(r, []).append(cell)
            for r, cells in rows.items():
                texts = [c.value for c in cells if isinstance(c.value, str) and not xlsx._is_formula(c.value)]  # noqa: SLF001
                if not texts:
                    continue
                nums = []
                for c in cells:
                    if xlsx._is_formula(c.value):  # noqa: SLF001
                        nums.append({"cell": c.coordinate, "value": values.get(f"{ws.title}!{c.coordinate}")})
                    elif isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                        nums.append({"cell": c.coordinate, "value": float(c.value)})
                out.append({"sheet": ws.title, "row": r, "label": " ".join(texts), "numbers": nums})
        return out
    finally:
        wb.close()


def validate_xlsx(path: Path, *, expect: list[dict] | None = None, require_sheets: list[str] | None = None,
                  require_labels: list[str] | None = None, previous: Path | None = None,
                  allow_formula_removal: bool = False) -> Report:
    rep = Report(str(path))
    if not path.is_file() or path.stat().st_size == 0:
        rep.add("fayl mavjud", False, "fayl yo'q yoki bo'sh")
        return rep
    rep.sha = sha256(path)
    try:
        with zipfile.ZipFile(path) as z:
            bad = z.testzip()
        if bad:
            rep.add("fayl butun", False, f"buzilgan qism: {bad}")
            return rep
        import openpyxl

        wb = openpyxl.load_workbook(path, data_only=False)
        sheets = wb.sheetnames
        wb.close()
    except Exception as exc:  # noqa: BLE001 — har qanday ochilmaslik = buzilgan fayl
        rep.add("fayl ochiladi", False, f"{type(exc).__name__}: {exc}")
        return rep
    rep.add("fayl ochiladi", True, f"varaqlar: {', '.join(sheets)}")
    if require_sheets:
        missing = [s for s in require_sheets if s not in sheets]
        rep.add("kerakli varaqlar", not missing, "yo'q: " + ", ".join(missing) if missing else ", ".join(require_sheets))

    calc = xlsx.compute(path)
    rep.values = calc.values
    rep.add("formulalar xatosiz", not calc.errors,
            f"{calc.formulas} ta formula" + (": " + ", ".join(f"{k}={c}" for k, c in calc.errors[:6]) if calc.errors else ""))
    if calc.unsupported:
        rep.add("formulalar mustaqil hisoblandi", False,
                f"{len(calc.unsupported)} tasi hisoblanmadi (natija tasdiqlanmagan): "
                + "; ".join(f"{k} ({why})" for k, why in calc.unsupported[:4]), hard=False)
    elif calc.formulas:
        rep.add("formulalar mustaqil hisoblandi", True, f"{calc.computed}/{calc.formulas}")

    unsupported = {k for k, _why in calc.unsupported}
    missing_all = xlsx.missing_cache(path)
    missing_cache = [k for k in missing_all if k not in unsupported]
    rep.add("natijalar faylda ko'rinadi (kesh qiymat)", not missing_cache,
            (f"{len(missing_cache)} ta formula katagida saqlangan natija yo'q — Telegram/telefonda BO'SH ko'rinadi: "
             + ", ".join(missing_cache[:5])) if missing_cache else "")
    blind = [k for k in missing_all if k in unsupported]
    if blind:
        rep.add("hisoblanmagan kataklar ko'rgichda", False,
                f"{len(blind)} ta katak faqat Excel ochganda hisoblanadi, telefonda bo'sh ko'rinishi mumkin: "
                + ", ".join(blind[:4]), hard=False)

    rows = _rows_with_labels(path, calc.values)
    rep.totals = xlsx.label_rows(path, calc.values)
    empty_totals = [f"{t['sheet']}!{t['row']} '{t['label']}'" for t in rep.totals
                    if not any(n["value"] not in (None, "") for n in t["numbers"])]
    if rep.totals:
        rep.add("jami qatorlarida qiymat bor", not empty_totals, "bo'sh: " + ", ".join(empty_totals) if empty_totals
                else f"{len(rep.totals)} ta jami qatori")
    for label in require_labels or []:
        hit = any(xlsx.normalize(label) in xlsx.normalize(r["label"]) for r in rows)
        rep.add(f"'{label}' yozuvi bor", hit)
    for exp in expect or []:
        ok, detail = _expect_match(rep.totals, rows, exp)
        rep.add("kutilgan qiymat", ok, detail)

    if previous is not None and Path(previous).is_file():
        d = xlsx.diff(Path(previous), path)
        lost_formulas = d["formulas_to_constants"] + d["formulas_removed"]
        rep.add("oldingi versiyadagi formulalar saqlangan", allow_formula_removal or not lost_formulas,
                (f"{len(lost_formulas)} ta formula o'chgan yoki songa almashgan: {', '.join(lost_formulas[:6])}"
                 if lost_formulas else "") + (" (ruxsat berilgan)" if allow_formula_removal and lost_formulas else ""))
        rep.add("varaqlar saqlangan", not d["sheets_removed"], ", ".join(d["sheets_removed"]))
        rep.add("grafik/rasm/pivot saqlangan", not d["parts_lost"],
                ", ".join(f"{k} {a}→{b}" for k, (a, b) in d["parts_lost"].items()))
        rep.add("o'zgarishlar", True, xlsx.diff_summary(d), hard=False)
    return rep


def validate_generic(path: Path, *, expect_text: list[str] | None = None, previous: Path | None = None) -> Report:
    rep = Report(str(path))
    if not path.is_file() or path.stat().st_size == 0:
        rep.add("fayl mavjud", False, "fayl yo'q yoki bo'sh")
        return rep
    rep.sha = sha256(path)
    suffix = path.suffix.lower()
    text = ""
    try:
        if suffix == ".docx":
            import docx

            d = docx.Document(str(path))
            text = "\n".join(p.text for p in d.paragraphs)
            text += "\n" + "\n".join(c.text for t in d.tables for row in t.rows for c in row.cells)
            rep.add("fayl ochiladi", True, f"{len(d.paragraphs)} paragraf, {len(d.tables)} jadval")
        elif suffix == ".pdf":
            from pypdf import PdfReader

            r = PdfReader(str(path))
            text = "\n".join((p.extract_text() or "") for p in r.pages)
            rep.add("fayl ochiladi", len(r.pages) > 0, f"{len(r.pages)} sahifa")
        elif suffix == ".csv":
            raw = path.read_bytes()
            text = raw.decode("utf-8-sig", errors="replace")
            rows = list(csv.reader(text.splitlines()))
            rep.add("fayl ochiladi", bool(rows), f"{len(rows)} qator")
        else:
            with zipfile.ZipFile(path) as z:
                bad = z.testzip()
            rep.add("fayl butun", bad is None, f"buzilgan qism: {bad}" if bad else "")
    except Exception as exc:  # noqa: BLE001
        rep.add("fayl ochiladi", False, f"{type(exc).__name__}: {exc}")
        return rep
    low = xlsx.normalize(text)
    for t in expect_text or []:
        rep.add(f"'{t}' matni bor", xlsx.normalize(t) in low)
    if previous is not None and Path(previous).is_file() and suffix == ".docx" and text:
        old = validate_generic(Path(previous))
        old_len = sum(int(c.detail.split()[0]) for c in old.checks if c.name == "fayl ochiladi" and c.detail[:1].isdigit())
        new_len = sum(int(c.detail.split()[0]) for c in rep.checks if c.name == "fayl ochiladi" and c.detail[:1].isdigit())
        shrunk = old_len >= 5 and new_len < old_len * 0.7
        rep.add("oldingi mazmun saqlangan", not shrunk,
                f"paragraflar {old_len} → {new_len}" + (" (30% dan ko'p qisqargan)" if shrunk else ""), hard=False)
    return rep


def validate(path: Path | str, *, expect: list[dict] | None = None, require_sheets: list[str] | None = None,
             require_labels: list[str] | None = None, previous: Path | str | None = None,
             allow_formula_removal: bool = False) -> Report:
    path = Path(path)
    prev = Path(previous) if previous else None
    if path.suffix.lower() in EXCEL_EXT:
        return validate_xlsx(path, expect=expect, require_sheets=require_sheets, require_labels=require_labels,
                             previous=prev, allow_formula_removal=allow_formula_removal)
    texts = list(require_labels or []) + [str(e.get("label")) for e in expect or [] if e.get("label")]
    return validate_generic(path, expect_text=texts, previous=prev)
