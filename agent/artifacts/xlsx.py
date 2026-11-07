"""Excel (.xlsx/.xlsm): kesh qiymatlar, tuzilma, versiyalar farqi, ИТОГО qatori.

KESH QIYMAT MUAMMOSI: openpyxl formulani natijasiz yozadi. Excel ochganda qayta hisoblaydi, lekin Telegram
ko'rgichi, telefon va boshqa ko'rgichlar faqat saqlangan natijani ko'rsatadi — jami katagi BO'SH ko'rinadi.
`write_cached_values` formulalarni o'zimiz hisoblab, natijani XML ga `<v>` qilib yozadi (formula joyida qoladi)
va Excel ochilganda qayta hisoblasin deb `fullCalcOnLoad` qo'yadi. Faqat formula kataklarining qiymat qismi va
calcPr o'zgaradi — qolgan hamma narsa (uslub, grafik, makros) bayt-baytigacha saqlanadi.
"""
from __future__ import annotations

import os
import re
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import openpyxl
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import column_index_from_string, get_column_letter

from .formula import Unsupported, XLError, evaluate_all

TOTAL_RE = re.compile(r"итог|итого|жами|jami|всего|total|umumiy|умумий|yakuniy|якуний|к\s+оплате", re.I)
AMOUNT_HEADER_RE = re.compile(r"сумма|summa|сумма|итог|jami|жами|стоимость|qiymat|amount|total|всего", re.I)
PRICE_HEADER_RE = re.compile(r"цена|narx|нарх|price|стоим", re.I)
_RISKY_PARTS = ("xl/charts/", "xl/pivotTables/", "xl/pivotCache/", "xl/drawings/", "xl/media/", "xl/vbaProject.bin",
                "xl/slicers/", "xl/timelines/")

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "pr": "http://schemas.openxmlformats.org/package/2006/relationships"}

_C_RE = re.compile(r"<(?P<tag>(?:[A-Za-z_][\w.-]*:)?c)(?=[\s/>])(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</(?P=tag)>)", re.S)
_F_RE = re.compile(r"<(?P<p>(?:[A-Za-z_][\w.-]*:)?)f(?=[\s/>])[^>]*?(?:/>|>.*?</(?P=p)f>)", re.S)
_V_RE = re.compile(r"<(?P<p>(?:[A-Za-z_][\w.-]*:)?)(?:v|is)(?=[\s/>])[^>]*?(?:/>|>.*?</(?P=p)(?:v|is)>)", re.S)
_R_ATTR = re.compile(r'\sr="([A-Za-z]+\d+)"')
_T_ATTR = re.compile(r'\st="[^"]*"')


def normalize(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("ё", "е").split())


def fmt_num(v: Any) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    if float(v).is_integer():
        return f"{int(v):,}".replace(",", " ")
    return f"{v:,.2f}".replace(",", " ")


# ---------------------------------------------------------------------------------------------------- zip qismlari
def zip_parts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as z:
        return z.namelist()


def risky_parts(path: Path) -> dict[str, int]:
    """openpyxl qayta saqlaganda yo'qolishi mumkin bo'lgan qismlar (grafik, pivot, rasm, makros) soni."""
    out: dict[str, int] = {}
    for name in zip_parts(path):
        for prefix in _RISKY_PARTS:
            if name.startswith(prefix) and not name.endswith(".rels"):
                key = prefix.rstrip("/").split("/")[-1]
                out[key] = out.get(key, 0) + 1
    return out


def _sheet_parts(z: zipfile.ZipFile) -> dict[str, str]:
    """varaq nomi -> 'xl/worksheets/sheet1.xml'."""
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.findall("pr:Relationship", _NS)}
    out = {}
    for s in wb.findall("m:sheets/m:sheet", _NS):
        rid = s.get(f"{{{_NS['r']}}}id")
        target = targets.get(rid, "")
        if not target:
            continue
        target = target.lstrip("/")
        out[s.get("name")] = target if target.startswith("xl/") else "xl/" + target
    return out


def missing_cache(path: Path) -> list[str]:
    """Kesh qiymati yo'q formula kataklari ('Varaq!E7') — ko'rgichlarda bo'sh ko'rinadi."""
    out = []
    with zipfile.ZipFile(path) as z:
        for sheet, part in _sheet_parts(z).items():
            try:
                xml = z.read(part).decode("utf-8")
            except KeyError:
                continue
            for m in _C_RE.finditer(xml):
                body = m.group("body") or ""
                if not _F_RE.search(body):
                    continue
                v = re.search(r"<(?:[A-Za-z_][\w.-]*:)?v>([^<]*)</(?:[A-Za-z_][\w.-]*:)?v>", body)
                if v is None or v.group(1) == "":
                    r = _R_ATTR.search(m.group("attrs") or "")
                    out.append(f"{sheet}!{r.group(1) if r else '?'}")
    return out


# ---------------------------------------------------------------------------------------------------- kesh qiymatlar
@dataclass
class CacheReport:
    formulas: int = 0
    computed: int = 0
    written: int = 0
    unsupported: list[tuple[str, str]] = field(default_factory=list)  # ('Varaq!E7', sabab)
    errors: list[tuple[str, str]] = field(default_factory=list)  # ('Varaq!E7', '#DIV/0!')
    values: dict[str, Any] = field(default_factory=dict)  # 'Varaq!E7' -> qiymat
    changed: bool = False


def compute(path: Path) -> CacheReport:
    """Faylni o'zgartirmasdan barcha formulalarni hisoblaydi."""
    wb = openpyxl.load_workbook(path, data_only=False)
    try:
        _ev, results = evaluate_all(wb)
    finally:
        wb.close()
    rep = CacheReport(formulas=len(results))
    for (sheet, coord), value in results.items():
        key = f"{sheet}!{coord}"
        if isinstance(value, Unsupported):
            rep.unsupported.append((key, str(value)))
            continue
        rep.computed += 1
        rep.values[key] = value
        if isinstance(value, XLError):
            rep.errors.append((key, value.code))
    return rep


def _cell_xml(m: re.Match, values: dict[str, Any], counter: list[int]) -> str:
    attrs = m.group("attrs") or ""
    body = m.group("body")
    if not body:
        return m.group(0)
    fm = _F_RE.search(body)
    r = _R_ATTR.search(attrs)
    if fm is None or r is None or r.group(1) not in values:
        return m.group(0)
    value = values[r.group(1)]
    prefix = fm.group("p")
    attrs = _T_ATTR.sub("", attrs)
    if isinstance(value, XLError):
        t, text = "e", value.code
    elif isinstance(value, bool):
        t, text = "b", "1" if value else "0"
    elif isinstance(value, (int, float)):
        t, text = None, (str(int(value)) if float(value).is_integer() and abs(value) < 1e15 else repr(float(value)))
    elif value is None:
        t, text = None, "0"
    else:
        t, text = "str", escape(str(value))
    if t:
        attrs = f'{attrs} t="{t}"'
    rest = _V_RE.sub("", body[:fm.start()] + body[fm.end():])
    counter[0] += 1
    tag = m.group("tag")
    return f"<{tag}{attrs}>{fm.group(0)}<{prefix}v>{text}</{prefix}v>{rest}</{tag}>"


def _with_full_calc(xml: str) -> str:
    calc = re.search(r"<(?P<p>(?:[A-Za-z_][\w.-]*:)?)calcPr\b[^>]*?/?>", xml)
    if calc:
        tag = calc.group(0)
        if "fullCalcOnLoad=" in tag:
            new = re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', tag)
        else:
            new = tag[:-2] + ' fullCalcOnLoad="1"/>' if tag.endswith("/>") else tag[:-1] + ' fullCalcOnLoad="1">'
        return xml.replace(tag, new, 1)
    prefix = re.search(r"<((?:[A-Za-z_][\w.-]*:)?)workbook\b", xml)
    p = prefix.group(1) if prefix else ""
    # CT_Workbook tartibi: sheets, functionGroups, externalReferences, definedNames, calcPr ...
    for anchor in (f"</{p}definedNames>", f"</{p}externalReferences>", f"</{p}functionGroups>", f"</{p}sheets>"):
        idx = xml.rfind(anchor)
        if idx != -1:
            idx += len(anchor)
            return xml[:idx] + f'<{p}calcPr calcId="191029" fullCalcOnLoad="1"/>' + xml[idx:]
    return xml


def write_cached_values(path: Path) -> CacheReport:
    """Formulalarni hisoblab natijani kesh qiymat sifatida yozadi (formula saqlanadi). Atomik almashtirish."""
    path = Path(path)
    rep = compute(path)
    by_sheet: dict[str, dict[str, Any]] = {}
    for key, value in rep.values.items():
        sheet, coord = key.rsplit("!", 1)
        by_sheet.setdefault(sheet, {})[coord] = value
    counter = [0]
    with zipfile.ZipFile(path) as zin:
        parts = _sheet_parts(zin)
        replaced: dict[str, bytes] = {}
        for sheet, values in by_sheet.items():
            part = parts.get(sheet)
            if not part:
                continue
            xml = zin.read(part).decode("utf-8")
            new = _C_RE.sub(lambda m, v=values: _cell_xml(m, v, counter), xml)
            if new != xml:
                replaced[part] = new.encode("utf-8")
        wb_xml = zin.read("xl/workbook.xml").decode("utf-8")
        wb_new = _with_full_calc(wb_xml) if rep.formulas else wb_xml
        if wb_new != wb_xml:
            replaced["xl/workbook.xml"] = wb_new.encode("utf-8")
        if not replaced:
            return rep
        fd, tmp = tempfile.mkstemp(suffix=path.suffix, dir=str(path.parent))
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as zout:
                for info in zin.infolist():
                    data = replaced.get(info.filename)
                    if data is None:
                        data = zin.read(info.filename)
                    zout.writestr(info, data, compress_type=info.compress_type or zipfile.ZIP_DEFLATED)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise
    try:
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise
    rep.written = counter[0]
    rep.changed = True
    return rep


# ---------------------------------------------------------------------------------------------------- tuzilma
def _cells(ws):
    return sorted(ws._cells.items())  # noqa: SLF001


def _is_formula(v: Any) -> bool:
    return (isinstance(v, str) and v.startswith("=") and len(v) > 1) or type(v).__name__ in ("ArrayFormula",
                                                                                             "DataTableFormula")


def snapshot_cells(path: Path) -> dict[str, dict[str, tuple[str, Any, str]]]:
    """{varaq: {'E7': (tur, qiymat/formula, raqam formati)}} — tur: 'f' formula, 'v' qiymat."""
    wb = openpyxl.load_workbook(path, data_only=False)
    try:
        out: dict[str, dict[str, tuple[str, Any, str]]] = {}
        for ws in wb.worksheets:
            cells = {}
            for (_r, _c), cell in _cells(ws):
                v = cell.value
                if v is None or v == "":
                    continue
                kind = "f" if _is_formula(v) else "v"
                cells[cell.coordinate] = (kind, v if kind == "v" or isinstance(v, str) else str(v), cell.number_format)
            out[ws.title] = cells
        return out
    finally:
        wb.close()


def label_rows(path: Path, values: dict[str, Any] | None = None) -> list[dict]:
    """Jami (ИТОГО/Жами/Total) yozuvli qatorlar va ulardagi raqamlar (hisoblangan)."""
    values = values if values is not None else compute(path).values
    wb = openpyxl.load_workbook(path, data_only=False)
    try:
        out = []
        for ws in wb.worksheets:
            rows: dict[int, list] = {}
            for (r, _c), cell in _cells(ws):
                rows.setdefault(r, []).append(cell)
            for r, cells in rows.items():
                # Qisqa yorliq — jami qatori; uzun gap ichidagi "жами" so'zi (izoh matni) — emas.
                labels = [c for c in cells if isinstance(c.value, str) and not _is_formula(c.value)
                          and len(c.value.strip()) <= 60 and TOTAL_RE.search(c.value)]
                if not labels:
                    continue
                nums = []
                for c in cells:
                    key = f"{ws.title}!{c.coordinate}"
                    if _is_formula(c.value):
                        nums.append({"cell": c.coordinate, "formula": str(c.value), "value": values.get(key)})
                    elif isinstance(c.value, (int, float)) and not isinstance(c.value, bool):
                        nums.append({"cell": c.coordinate, "formula": None, "value": float(c.value)})
                if not nums:
                    continue  # raqamsiz qator — ustun sarlavhasi yoki izoh ("Жами 2 ПК, $" sarlavhasi), jami emas
                out.append({"sheet": ws.title, "row": r, "label": labels[0].value.strip(), "numbers": nums})
        return out
    finally:
        wb.close()


def inspect(path: Path) -> str:
    """Model uchun qisqa tuzilma: varaqlar, sarlavha, ustunlar, formulalar, jami qatorlari, kesh holati."""
    rep = compute(path)
    missing = missing_cache(path)
    risky = risky_parts(path)
    wb = openpyxl.load_workbook(path, data_only=False)
    lines = [f"Fayl: {path} ({path.stat().st_size} bayt)",
             f"Formulalar: {rep.formulas}, hisoblandi: {rep.computed}, hisoblanmadi: {len(rep.unsupported)}, "
             f"xato natija: {len(rep.errors)}, kesh qiymati yo'q: {len(missing)}"]
    if risky:
        lines.append("Maxsus qismlar: " + ", ".join(f"{k}={v}" for k, v in risky.items())
                     + " (openpyxl bilan qayta saqlash ularni yo'qotishi mumkin)")
    try:
        for ws in wb.worksheets:
            lines.append(f"\n=== Varaq '{ws.title}': {ws.dimensions}, {ws.max_row} qator × {ws.max_column} ustun ===")
            shown = 0
            for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 60)):
                parts = []
                for c in row:
                    if c.value is None:
                        continue
                    if _is_formula(c.value):
                        val = rep.values.get(f"{ws.title}!{c.coordinate}")
                        shown_val = fmt_num(val) if val is not None else "?"
                        parts.append(f"{c.coordinate}={c.value} → {shown_val}")
                    else:
                        parts.append(f"{c.coordinate}: {str(c.value)[:60]}")
                if parts:
                    lines.append("  " + " | ".join(parts))
                    shown += 1
            if ws.max_row > 60:
                lines.append(f"  (... yana {ws.max_row - 60} qator)")
    finally:
        wb.close()
    totals = label_rows(path, rep.values)
    if totals:
        lines.append("\nJami qatorlari:")
        for t in totals:
            nums = ", ".join(f"{n['cell']}={fmt_num(n['value']) if n['value'] is not None else '?'}"
                             + (" (formula)" if n["formula"] else " (qo'lda yozilgan son)") for n in t["numbers"])
            lines.append(f"  {t['sheet']}!{t['row']}: '{t['label']}' → {nums or 'raqam yoq'}")
    if rep.unsupported:
        lines.append("Hisoblanmagan: " + "; ".join(f"{k} ({why})" for k, why in rep.unsupported[:10]))
    if rep.errors:
        lines.append("Xato natijalar: " + "; ".join(f"{k}={code}" for k, code in rep.errors[:10]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------- farq
def diff(old: Path, new: Path) -> dict:
    """Oldingi va yangi versiya farqi (eng kam o'zgarish tamoyilini tekshirish uchun)."""
    a, b = snapshot_cells(old), snapshot_cells(new)
    out: dict[str, Any] = {"sheets_removed": [s for s in a if s not in b], "sheets_added": [s for s in b if s not in a],
                           "formulas_removed": [], "formulas_to_constants": [], "cells_cleared": [],
                           "cells_changed": [], "cells_added": [], "formats_changed": []}
    for sheet, cells in a.items():
        if sheet not in b:
            continue
        nb = b[sheet]
        for coord, (kind, val, nf) in cells.items():
            key = f"{sheet}!{coord}"
            if coord not in nb:
                out["cells_cleared"].append(key)
                if kind == "f":
                    out["formulas_removed"].append(key)
                continue
            kind2, val2, nf2 = nb[coord]
            if kind == "f" and kind2 != "f":
                out["formulas_to_constants"].append(key)
            elif val != val2:
                out["cells_changed"].append(key)
            if nf != nf2:
                out["formats_changed"].append(key)
        out["cells_added"] += [f"{sheet}!{c}" for c in nb if c not in cells]
    ra, rb = risky_parts(old), risky_parts(new)
    out["parts_lost"] = {k: (v, rb.get(k, 0)) for k, v in ra.items() if rb.get(k, 0) < v}
    return out


def diff_summary(d: dict, limit: int = 6) -> str:
    parts = []
    for key, label in (("sheets_removed", "varaq o'chgan"), ("formulas_to_constants", "formula songa almashgan"),
                       ("formulas_removed", "formula o'chgan"), ("cells_cleared", "katak tozalangan"),
                       ("cells_changed", "katak o'zgargan"), ("cells_added", "katak qo'shilgan"),
                       ("formats_changed", "format o'zgargan")):
        items = d.get(key) or []
        if items:
            parts.append(f"{label}: {len(items)} ({', '.join(items[:limit])}{'…' if len(items) > limit else ''})")
    if d.get("parts_lost"):
        parts.append("yo'qolgan qismlar: " + ", ".join(f"{k} {a}→{b}" for k, (a, b) in d["parts_lost"].items()))
    return "; ".join(parts) or "farq yo'q"


# ---------------------------------------------------------------------------------------------------- ИТОГО qatori
CURRENCY_FORMATS = {"UZS": '#,##0 "сўм"', "USD": '#,##0.00 "$"', "EUR": '#,##0.00 "€"', "RUB": '#,##0.00 "₽"'}


@dataclass
class TotalResult:
    ok: bool
    message: str
    sheet: str = ""
    row: int = 0
    cells: list[str] = field(default_factory=list)
    existed: bool = False


def _header_row(ws) -> int | None:
    for r in range(1, min(ws.max_row, 40) + 1):
        texts = [c for c in ws[r] if isinstance(c.value, str) and c.value.strip() and not _is_formula(c.value)]
        if len(texts) < 2:
            continue
        nxt = [c for c in ws[r + 1] if c.value is not None] if r < ws.max_row else []
        if any(isinstance(c.value, (int, float)) or _is_formula(c.value) for c in nxt):
            return r
    return None


def _pick_amount_column(ws, header: int | None, wanted: str | None) -> int | None:
    if wanted:
        w = wanted.strip()
        if re.fullmatch(r"[A-Za-z]{1,3}", w):
            return column_index_from_string(w.upper())
        if header:
            for c in ws[header]:
                if isinstance(c.value, str) and normalize(w) in normalize(c.value):
                    return c.column
        return None
    if header:
        heads = [(c.column, str(c.value)) for c in ws[header] if isinstance(c.value, str)]
        amount = [col for col, text in heads if AMOUNT_HEADER_RE.search(text) and not PRICE_HEADER_RE.search(text)]
        if amount:
            return amount[-1]
        price = [col for col, text in heads if PRICE_HEADER_RE.search(text) or AMOUNT_HEADER_RE.search(text)]
        if price:
            return price[-1]
    numeric_cols = {}
    for (_r, c), cell in _cells(ws):
        if isinstance(cell.value, (int, float)) and not isinstance(cell.value, bool) or _is_formula(cell.value):
            numeric_cols[c] = numeric_cols.get(c, 0) + 1
    return max(numeric_cols) if numeric_cols else None


def add_total_row(path: Path, *, sheet: str | None = None, amount_columns: list[str] | None = None,
                  label: str = "ИТОГО", first_row: int | None = None, last_row: int | None = None,
                  currency: str = "keep", highlight: bool = True) -> TotalResult:
    """Ko'rinadigan ИТОГО qatorini SUM formulasi bilan qo'shadi; mavjud jami qatori bo'lsa — takrorlamaydi, faqat
    ko'rinadigan qiladi. Qatorlarni surmaydi (openpyxl surilganda formulalarni yangilamaydi)."""
    path = Path(path)
    risky = {k: v for k, v in risky_parts(path).items() if k != "vbaProject.bin"}
    if risky:
        return TotalResult(False, "Faylda " + ", ".join(risky) + " bor: openpyxl ularni saqlay olmaydi, shuning uchun "
                                  "fayl o'zgartirilmadi. Excel'da qo'lda yoki boshqa usulda qo'shish kerak.")
    keep_vba = path.suffix.lower() == ".xlsm"
    wb = openpyxl.load_workbook(path, keep_vba=keep_vba)
    try:
        ws = wb[sheet] if sheet else wb.active
        header = _header_row(ws)
        cols = [_pick_amount_column(ws, header, w) for w in (amount_columns or [None])]
        cols = [c for c in cols if c]
        if not cols:
            return TotalResult(False, "Summa ustuni topilmadi — amount_columns ga ustun harfini bering (masalan E).")
        start = first_row or ((header + 1) if header else 1)
        label_col = None
        if header:
            text_cols = [c.column for c in ws[header] if isinstance(c.value, str) and c.column not in cols]
            for col in text_cols:
                sample = ws.cell(row=start, column=col).value
                if isinstance(sample, str) and not sample.strip().isdigit():
                    label_col = col
                    break
            label_col = label_col or (text_cols[0] if text_cols else None)
        label_col = label_col or max(1, min(cols) - 1)
        end = last_row
        existing = None
        if end is None:
            end = start - 1
            for r in range(start, ws.max_row + 1):
                row_text = " ".join(str(c.value) for c in ws[r] if isinstance(c.value, str) and not _is_formula(c.value))
                if TOTAL_RE.search(row_text):
                    existing = existing or r
                    break
                amounts = [ws.cell(row=r, column=c).value for c in cols]
                if all(v is None for v in amounts):
                    if any(ws.cell(row=r, column=c).value is not None for c in range(1, ws.max_column + 1)):
                        continue
                    break
                end = r
        if end < start:
            return TotalResult(False, f"'{ws.title}' varag'ida summa qatorlari topilmadi (boshlanish {start}).")
        for r in range(existing or 0, (min(existing + 6, ws.max_row) + 1) if existing else 0):
            row_text = " ".join(str(c.value) for c in ws[r] if isinstance(c.value, str) and not _is_formula(c.value))
            if not TOTAL_RE.search(row_text) or any(ws.cell(row=r, column=c).value is None for c in cols):
                continue
            # Shu summa ustuni uchun jami qatori allaqachon bor — ikkinchisini qo'shmaymiz, faqat ko'rinadigan qilamiz.
            refs = [f"{get_column_letter(c)}{r}" for c in cols]
            _style_row(ws, r, cols, label_col, currency, highlight)
            wb.save(path)
            return TotalResult(True, f"Jami qatori allaqachon bor ({ws.title}!{r}: '{row_text.strip()[:60]}') — "
                                     "takrorlanmadi, ko'rinadigan qilib belgilandi.", ws.title, r, refs, existed=True)
        target = end + 1
        while any(ws.cell(row=target, column=c).value is not None for c in range(1, max(ws.max_column, 1) + 1)):
            target += 1
        ws.cell(row=target, column=label_col, value=label)
        refs = []
        for c in cols:
            letter = get_column_letter(c)
            ws.cell(row=target, column=c, value=f"=SUM({letter}{start}:{letter}{end})")
            refs.append(f"{letter}{target}")
        _style_row(ws, target, cols, label_col, currency, highlight)
        wb.save(path)
        return TotalResult(True, f"ИТОГО qatori qo'shildi: {ws.title}!{target}, " + ", ".join(
            f"{ref}=SUM({ref[:len(ref) - len(str(target))]}{start}:{ref[:len(ref) - len(str(target))]}{end})"
            for ref in refs), ws.title, target, refs)
    finally:
        wb.close()


def _style_row(ws, row: int, cols: list[int], label_col: int, currency: str, highlight: bool) -> None:
    fill = PatternFill("solid", fgColor="FFE699")
    thin = Side(style="thin", color="7F7F7F")
    double = Side(style="double", color="000000")
    last = max(cols + [label_col])
    first = min(cols + [label_col])
    for col in range(first, last + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = Font(bold=True, size=max(12, int(cell.font.size or 11)))
        if highlight:
            cell.fill = fill
            cell.border = Border(top=thin, bottom=double, left=thin, right=thin)
    for col in cols:
        cell = ws.cell(row=row, column=col)
        if currency and currency.upper() in CURRENCY_FORMATS:
            cell.number_format = CURRENCY_FORMATS[currency.upper()]
        else:
            above = ws.cell(row=row - 1, column=col).number_format
            cell.number_format = above if above and above != "General" else "#,##0"
