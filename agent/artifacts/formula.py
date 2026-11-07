"""Excel formulalarini mustaqil hisoblash (openpyxl o'zi hisoblamaydi).

Smeta, hisobot va jadvallarda uchraydigan qism: arifmetika (+ - * / ^ % &, taqqoslash), katak va diapazon
havolalari (boshqa varaq, $ belgisi, butun ustun/qator, nomlangan diapazon), SUM, PRODUCT, MIN, MAX, AVERAGE,
COUNT, COUNTA, ROUND/ROUNDUP/ROUNDDOWN, INT, ABS, MOD, POWER, SQRT, IF, IFERROR, AND, OR, NOT, SUMPRODUCT, SUMIF,
COUNTIF, CONCATENATE/CONCAT, LEN, UPPER, LOWER, TRIM.
Qo'llab-quvvatlanmaydigan narsa (massiv formula, tashqi fayl, noma'lum funksiya) — `Unsupported`: bunday katak
"hisoblanmadi" deb ochiq aytiladi va tekshiruv uni TASDIQLANGAN deb hisoblamaydi.
"""
from __future__ import annotations

import fnmatch
import math
import re
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any

from openpyxl.formula.tokenizer import Token, Tokenizer
from openpyxl.utils import column_index_from_string

MAX_FORMULAS = 60000


class Unsupported(Exception):
    """Formulani bu hisoblagich bilan ishonchli hisoblab bo'lmaydi."""


@dataclass(frozen=True)
class XLError:
    code: str

    def __str__(self) -> str:
        return self.code


DIV0, VALUE, REF, NAME, NA, NUM = (XLError(c) for c in ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#N/A", "#NUM!"))


@dataclass
class Range:
    rows: list[list[Any]]

    def flat(self) -> list[Any]:
        return [v for row in self.rows for v in row]


# ---------------------------------------------------------------------------------------------------- parser
_BP = {"=": 10, "<": 10, ">": 10, "<=": 10, ">=": 10, "<>": 10, "&": 20, "+": 30, "-": 30, "*": 40, "/": 40, "^": 50}
_PREFIX_BP = 60
_PERCENT_BP = 70


class _Parser:
    def __init__(self, formula: str):
        text = formula if formula.startswith("=") else "=" + formula
        try:
            items = Tokenizer(text).items
        except Exception as exc:  # noqa: BLE001 — openpyxl tokenizatori turli xato beradi
            raise Unsupported(f"formula o'qilmadi: {exc}") from None
        self.toks = [t for t in items if t.type != Token.WSPACE]
        self.i = 0

    def peek(self) -> Token | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> Token:
        tok = self.peek()
        if tok is None:
            raise Unsupported("formula kutilmaganda tugadi")
        self.i += 1
        return tok

    def parse(self):
        node = self.expr(0)
        if self.peek() is not None:
            raise Unsupported(f"kutilmagan belgi: {self.peek().value}")
        return node

    def expr(self, rbp: int):
        left = self.nud(self.next())
        while True:
            tok = self.peek()
            if tok is None:
                return left
            if tok.type == Token.OP_POST and tok.value == "%":
                if _PERCENT_BP <= rbp:
                    return left
                self.next()
                left = ("pct", left)
                continue
            if tok.type != Token.OP_IN:
                return left
            op = tok.value
            if op not in _BP:
                raise Unsupported(f"operator '{op}' qo'llab-quvvatlanmaydi")
            bp = _BP[op]
            if bp <= rbp:
                return left
            self.next()
            left = ("bin", op, left, self.expr(bp))

    def nud(self, tok: Token):
        if tok.type == Token.OPERAND:
            if tok.subtype == Token.NUMBER:
                return ("num", float(tok.value))
            if tok.subtype == Token.TEXT:
                return ("str", tok.value[1:-1].replace('""', '"'))
            if tok.subtype == Token.LOGICAL:
                return ("bool", tok.value.upper() == "TRUE")
            if tok.subtype == Token.ERROR:
                return ("err", XLError(tok.value.upper()))
            return ("ref", tok.value)
        if tok.type == Token.OP_PRE:
            operand = self.expr(_PREFIX_BP)
            return ("neg", operand) if tok.value == "-" else operand
        if tok.type == Token.PAREN and tok.subtype == Token.OPEN:
            node = self.expr(0)
            close = self.next()
            if close.type != Token.PAREN:
                raise Unsupported("qavs yopilmagan")
            return node
        if tok.type == Token.FUNC and tok.subtype == Token.OPEN:
            name = tok.value[:-1].upper()
            if name.startswith("_XLFN."):
                name = name[6:]
            args: list = []
            if self.peek() is not None and self.peek().type == Token.FUNC and self.peek().subtype == Token.CLOSE:
                self.next()
                return ("call", name, args)
            while True:
                nxt = self.peek()
                if nxt is not None and (nxt.type == Token.SEP or (nxt.type == Token.FUNC and nxt.subtype == Token.CLOSE)):
                    args.append(("missing",))
                else:
                    args.append(self.expr(0))
                sep = self.next()
                if sep.type == Token.FUNC and sep.subtype == Token.CLOSE:
                    return ("call", name, args)
                if not (sep.type == Token.SEP and sep.subtype == Token.ARG):
                    raise Unsupported(f"funksiya argumentida kutilmagan belgi: {sep.value}")
        if tok.type == Token.ARRAY:
            raise Unsupported("massiv konstantasi")
        raise Unsupported(f"kutilmagan belgi: {tok.value}")


_PARSE_CACHE: dict[str, Any] = {}


def parse(formula: str):
    node = _PARSE_CACHE.get(formula)
    if node is None:
        node = _Parser(formula).parse()
        if len(_PARSE_CACHE) < 20000:
            _PARSE_CACHE[formula] = node
    return node


# ---------------------------------------------------------------------------------------------------- havolalar
_REF_RE = re.compile(
    r"^(?:(?P<sheet>'(?:[^']|'')+'|[^'!:]+)!)?"
    r"(?P<a>\$?[A-Za-z]{1,3}\$?\d+|\$?[A-Za-z]{1,3}|\$?\d+)"
    r"(?::(?P<b>\$?[A-Za-z]{1,3}\$?\d+|\$?[A-Za-z]{1,3}|\$?\d+))?$")
_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})?\$?(\d+)?$")


def _part(text: str) -> tuple[int | None, int | None]:
    m = _CELL_RE.match(text)
    if not m:
        raise Unsupported(f"havola o'qilmadi: {text}")
    col = column_index_from_string(m.group(1).upper()) if m.group(1) else None
    row = int(m.group(2)) if m.group(2) else None
    return row, col


# ---------------------------------------------------------------------------------------------------- qiymatlar
def to_number(v: Any) -> float | XLError:
    if isinstance(v, XLError):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(" ", "").replace(" ", "")
        if not s:
            return 0.0
        try:
            return float(s.replace(",", ".")) if s.count(",") == 1 and "." not in s else float(s)
        except ValueError:
            return VALUE
    raise Unsupported(f"{type(v).__name__} turidagi qiymat (sana/vaqt) bilan arifmetika")


def to_text(v: Any) -> str | XLError:
    if isinstance(v, XLError):
        return v
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v)


def to_bool(v: Any) -> bool | XLError:
    if isinstance(v, XLError):
        return v
    if isinstance(v, str):
        if v.upper() in ("TRUE", "FALSE"):
            return v.upper() == "TRUE"
        return VALUE
    n = to_number(v)
    return n if isinstance(n, XLError) else n != 0


def _excel_round(x: float, digits: float, mode) -> float:
    d = int(digits)
    q = Decimal(1).scaleb(-d)
    sign = -1 if x < 0 else 1
    val = Decimal(repr(abs(x))).quantize(q, rounding=mode) if d >= 0 else \
        (Decimal(repr(abs(x))) / Decimal(10) ** (-d)).quantize(Decimal(1), rounding=mode) * Decimal(10) ** (-d)
    return sign * float(val)


def _compare(op: str, a: Any, b: Any) -> bool:
    def rank(v):
        if isinstance(v, bool):
            return 2
        if isinstance(v, str):
            return 1
        return 0
    a = 0.0 if a is None and not isinstance(b, str) else ("" if a is None else a)
    b = 0.0 if b is None and not isinstance(a, str) else ("" if b is None else b)
    ra, rb = rank(a), rank(b)
    if ra != rb:
        ka, kb = ra, rb
    elif ra == 1:
        ka, kb = a.lower(), b.lower()
    else:
        ka, kb = float(a), float(b)
    return {"=": ka == kb, "<>": ka != kb, "<": ka < kb, ">": ka > kb, "<=": ka <= kb, ">=": ka >= kb}[op]


def _criteria(crit: Any):
    """SUMIF/COUNTIF sharti -> predicate."""
    if isinstance(crit, (int, float)) and not isinstance(crit, bool):
        return lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) == float(crit)
    s = to_text(crit)
    if isinstance(s, XLError):
        raise Unsupported("shart xato qiymat")
    m = re.match(r"^(<=|>=|<>|<|>|=)?(.*)$", s, re.S)
    op, target = m.group(1) or "=", m.group(2)
    num = to_number(target) if target.strip() else None
    if isinstance(num, float) and target.strip():
        def pred(v, op=op, num=num):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                return op == "<>"
            return _compare(op, float(v), num)
        return pred
    if op in ("=", "<>") and any(c in target for c in "*?"):
        pattern = fnmatch.translate(target.lower())
        rx = re.compile(pattern, re.S)
        return lambda v: (rx.match(str(v or "").lower()) is not None) == (op == "=")
    return lambda v: _compare(op, "" if v is None else (v if isinstance(v, str) else to_text(v)), target)


# ---------------------------------------------------------------------------------------------------- hisoblagich
class Evaluator:
    def __init__(self, wb):
        self.wb = wb
        self.cache: dict[tuple[str, int, int], Any] = {}
        self._stack: set[tuple[str, int, int]] = set()

    # --- kataklar ---------------------------------------------------------------------------------------
    def _sheet(self, name: str):
        if name in self.wb.sheetnames:
            return self.wb[name]
        low = {s.lower(): s for s in self.wb.sheetnames}
        if name.lower() in low:
            return self.wb[low[name.lower()]]
        return None

    def cell(self, sheet: str, row: int, col: int) -> Any:
        key = (sheet, row, col)
        if key in self.cache:
            return self.cache[key]
        ws = self._sheet(sheet)
        if ws is None:
            return REF
        cell = ws._cells.get((row, col))  # noqa: SLF001 — mavjud bo'lmagan katakni yaratib yubormaslik uchun
        raw = cell.value if cell is not None else None
        if isinstance(raw, str) and raw.startswith("=") and len(raw) > 1:
            if key in self._stack:
                raise Unsupported(f"aylanma havola ({ws.title}!{cell.coordinate})")
            self._stack.add(key)
            try:
                value = self.eval(parse(raw), ws.title)
            finally:
                self._stack.discard(key)
            if isinstance(value, Range):
                raise Unsupported("formula diapazon qaytaradi (spill)")
        elif raw is not None and type(raw).__name__ in ("ArrayFormula", "DataTableFormula"):
            raise Unsupported("massiv/jadval formulasi")
        else:
            value = raw
        if isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        self.cache[key] = value
        return value


    def ref(self, text: str, sheet: str):
        m = _REF_RE.match(text)
        if not m:
            return self._name(text, sheet)
        target = sheet
        if m.group("sheet"):
            s = m.group("sheet")
            if s.startswith("["):
                raise Unsupported("tashqi faylga havola")
            target = s[1:-1].replace("''", "'") if s.startswith("'") else s
            if target.startswith("["):
                raise Unsupported("tashqi faylga havola")
        ws = self._sheet(target)
        if ws is None:
            return REF
        r1, c1 = _part(m.group("a"))
        if m.group("b") is None:
            if r1 is None or c1 is None:
                return self._name(text, sheet)
            return self.cell(ws.title, r1, c1)
        r2, c2 = _part(m.group("b"))
        max_row, max_col = ws.max_row, ws.max_column
        if c1 is None and c2 is None:  # 1:3 — butun qatorlar
            c1, c2 = 1, max_col
        if r1 is None and r2 is None:  # A:A — butun ustun
            r1, r2 = 1, max_row
        if None in (r1, c1, r2, c2):
            raise Unsupported(f"diapazon o'qilmadi: {text}")
        r1, r2 = sorted((r1, r2))
        c1, c2 = sorted((c1, c2))
        r2 = min(r2, max(max_row, r1))  # ma'lumotdan pastdagi bo'sh qatorlarni aylanib o'tirmaymiz
        c2 = min(c2, max(max_col, c1))
        if (r2 - r1 + 1) * (c2 - c1 + 1) > 500000:
            raise Unsupported("diapazon juda katta")
        return Range([[self.cell(ws.title, r, c) for c in range(c1, c2 + 1)] for r in range(r1, r2 + 1)])

    def _name(self, name: str, sheet: str):
        dn = None
        ws = self._sheet(sheet)
        try:
            if ws is not None and getattr(ws, "defined_names", None) and name in ws.defined_names:
                dn = ws.defined_names[name]
            elif name in self.wb.defined_names:
                dn = self.wb.defined_names[name]
        except (TypeError, KeyError, AttributeError):
            dn = None
        if dn is None or not getattr(dn, "attr_text", None):
            return NAME
        return self.eval(parse("=" + dn.attr_text), sheet)

    # --- ifodalar ---------------------------------------------------------------------------------------
    def eval(self, node, sheet: str):
        kind = node[0]
        if kind in ("num", "str", "bool", "err"):
            return node[1]
        if kind == "missing":
            return None
        if kind == "ref":
            return self.ref(node[1], sheet)
        if kind == "neg":
            v = self._scalar(self.eval(node[1], sheet))
            n = to_number(v)
            return n if isinstance(n, XLError) else -n
        if kind == "pct":
            n = to_number(self._scalar(self.eval(node[1], sheet)))
            return n if isinstance(n, XLError) else n / 100
        if kind == "bin":
            return self._binary(node[1], self._scalar(self.eval(node[2], sheet)), self._scalar(self.eval(node[3], sheet)))
        if kind == "call":
            return self._call(node[1], node[2], sheet)
        raise Unsupported(f"tugun turi: {kind}")

    @staticmethod
    def _scalar(v: Any) -> Any:
        if isinstance(v, Range):
            if len(v.rows) == 1 and len(v.rows[0]) == 1:
                return v.rows[0][0]
            raise Unsupported("diapazon skalyar o'rnida (implicit intersection)")
        return v

    @staticmethod
    def _binary(op: str, a: Any, b: Any) -> Any:
        if isinstance(a, XLError):
            return a
        if isinstance(b, XLError):
            return b
        if op == "&":
            ta, tb = to_text(a), to_text(b)
            return ta + tb
        if op in ("=", "<>", "<", ">", "<=", ">="):
            return _compare(op, a, b)
        x, y = to_number(a), to_number(b)
        if isinstance(x, XLError):
            return x
        if isinstance(y, XLError):
            return y
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            return DIV0 if y == 0 else x / y
        if op == "^":
            if x == 0 and y < 0:
                return DIV0
            try:
                r = x ** y
            except (OverflowError, ValueError):
                return NUM
            return NUM if isinstance(r, complex) else r
        raise Unsupported(f"operator {op}")

    # --- funksiyalar ------------------------------------------------------------------------------------
    def _values(self, args, sheet) -> list[Any]:
        return [self.eval(a, sheet) for a in args]

    @staticmethod
    def _numbers(values: list[Any]) -> list[float] | XLError:
        """SUM qoidasi: diapazondagi matn/mantiq/bo'sh e'tiborsiz; to'g'ridan-to'g'ri argument — majburan son."""
        out: list[float] = []
        for v in values:
            if isinstance(v, Range):
                for x in v.flat():
                    if isinstance(x, XLError):
                        return x
                    if isinstance(x, (int, float)) and not isinstance(x, bool):
                        out.append(float(x))
            elif v is None:
                continue
            else:
                n = to_number(v)
                if isinstance(n, XLError):
                    return n
                out.append(n)
        return out

    def _call(self, name: str, args: list, sheet: str) -> Any:  # noqa: C901 — funksiyalar jadvali
        if name == "IF":
            if not 1 <= len(args) <= 3:
                return VALUE
            cond = to_bool(self._scalar(self.eval(args[0], sheet)))
            if isinstance(cond, XLError):
                return cond
            if cond:
                return self._scalar(self.eval(args[1], sheet)) if len(args) > 1 else True
            return self._scalar(self.eval(args[2], sheet)) if len(args) > 2 else False
        if name == "IFERROR":
            v = self._scalar(self.eval(args[0], sheet))
            return self._scalar(self.eval(args[1], sheet)) if isinstance(v, XLError) else v
        vals = self._values(args, sheet)
        if name in ("SUM", "PRODUCT", "MIN", "MAX", "AVERAGE", "COUNT"):
            if name == "COUNT":
                return float(sum(1 for v in vals for x in (v.flat() if isinstance(v, Range) else [v])
                                 if isinstance(x, (int, float)) and not isinstance(x, bool)))
            nums = self._numbers(vals)
            if isinstance(nums, XLError):
                return nums
            if name == "SUM":
                return math.fsum(nums)
            if name == "PRODUCT":
                return math.prod(nums) if nums else 0.0
            if name == "MIN":
                return min(nums) if nums else 0.0
            if name == "MAX":
                return max(nums) if nums else 0.0
            return DIV0 if not nums else math.fsum(nums) / len(nums)
        if name == "COUNTA":
            return float(sum(1 for v in vals for x in (v.flat() if isinstance(v, Range) else [v]) if x not in (None, "")))
        scal = [self._scalar(v) for v in vals] if name not in ("SUMPRODUCT", "SUMIF", "COUNTIF") else vals
        if name in ("ROUND", "ROUNDUP", "ROUNDDOWN"):
            if len(scal) not in (1, 2):
                return VALUE
            x = to_number(scal[0])
            d = to_number(scal[1]) if len(scal) > 1 else 0.0
            if isinstance(x, XLError):
                return x
            if isinstance(d, XLError):
                return d
            mode = {"ROUND": ROUND_HALF_UP, "ROUNDUP": ROUND_UP, "ROUNDDOWN": ROUND_DOWN}[name]
            return _excel_round(x, d, mode)
        if name in ("INT", "ABS", "SQRT"):
            x = to_number(scal[0]) if scal else VALUE
            if isinstance(x, XLError):
                return x
            if name == "INT":
                return float(math.floor(x))
            if name == "ABS":
                return abs(x)
            return NUM if x < 0 else math.sqrt(x)
        if name in ("MOD", "POWER"):
            if len(scal) != 2:
                return VALUE
            x, y = to_number(scal[0]), to_number(scal[1])
            if isinstance(x, XLError):
                return x
            if isinstance(y, XLError):
                return y
            if name == "MOD":
                return DIV0 if y == 0 else x - y * math.floor(x / y)
            return self._binary("^", x, y)
        if name in ("AND", "OR", "NOT", "TRUE", "FALSE"):
            if name == "TRUE":
                return True
            if name == "FALSE":
                return False
            flags = []
            for v in vals:
                for x in (v.flat() if isinstance(v, Range) else [v]):
                    if isinstance(v, Range) and not isinstance(x, (bool, int, float)):
                        continue
                    b = to_bool(x)
                    if isinstance(b, XLError):
                        return b
                    flags.append(b)
            if name == "NOT":
                return not flags[0] if len(flags) == 1 else VALUE
            return all(flags) if name == "AND" else any(flags)
        if name in ("CONCATENATE", "CONCAT"):
            out = ""
            for v in vals:
                for x in (v.flat() if isinstance(v, Range) else [v]):
                    t = to_text(x)
                    if isinstance(t, XLError):
                        return t
                    out += t
            return out
        if name in ("LEN", "UPPER", "LOWER", "TRIM"):
            t = to_text(scal[0]) if scal else VALUE
            if isinstance(t, XLError):
                return t
            return {"LEN": lambda s: float(len(s)), "UPPER": str.upper, "LOWER": str.lower,
                    "TRIM": lambda s: " ".join(s.split())}[name](t)
        if name == "SUMPRODUCT":
            arrays = [v.flat() if isinstance(v, Range) else [v] for v in vals]
            if not arrays or len({len(a) for a in arrays}) != 1:
                return VALUE
            total = 0.0
            for items in zip(*arrays):
                prod = 1.0
                for x in items:
                    if isinstance(x, XLError):
                        return x
                    prod *= float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0.0
                total += prod
            return total
        if name in ("SUMIF", "COUNTIF"):
            if not isinstance(vals[0], Range):
                return VALUE
            pred = _criteria(self._scalar(vals[1]))
            cells = vals[0].flat()
            if name == "COUNTIF":
                return float(sum(1 for x in cells if pred(x)))
            target = vals[2].flat() if len(vals) > 2 and isinstance(vals[2], Range) else cells
            if len(target) != len(cells):
                raise Unsupported("SUMIF diapazonlari o'lchami har xil")
            return math.fsum(float(t) for x, t in zip(cells, target)
                             if pred(x) and isinstance(t, (int, float)) and not isinstance(t, bool))
        raise Unsupported(f"{name} funksiyasi qo'llab-quvvatlanmaydi")


def evaluate_all(wb) -> tuple[Evaluator, dict[tuple[str, str], Any]]:
    """Barcha formula kataklari: {(varaq, 'E7'): qiymat | Unsupported}. Qatorma-qator (bog'liqlik zanjiri sayoz)."""
    ev = Evaluator(wb)
    results: dict[tuple[str, str], Any] = {}
    count = 0
    for ws in wb.worksheets:
        for (row, col), cell in sorted(ws._cells.items()):  # noqa: SLF001
            v = cell.value
            is_formula = (isinstance(v, str) and v.startswith("=") and len(v) > 1) or \
                type(v).__name__ in ("ArrayFormula", "DataTableFormula")
            if not is_formula:
                continue
            count += 1
            if count > MAX_FORMULAS:
                results[(ws.title, cell.coordinate)] = Unsupported("fayl juda katta — formula soni chegaradan oshdi")
                continue
            try:
                results[(ws.title, cell.coordinate)] = ev.cell(ws.title, row, col)
            except Unsupported as exc:
                results[(ws.title, cell.coordinate)] = exc
            except RecursionError:
                results[(ws.title, cell.coordinate)] = Unsupported("bog'liqlik zanjiri juda chuqur")
    return ev, results
