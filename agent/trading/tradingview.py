"""TradingView grafik annotatsiyasi (V17): Pine Script tayyorlash, statik tekshiruv, saqlash, clipboard, qurilma va
sessiya tekshiruvi, TradingView oynasini skrinshot + OCR bilan tekshirish.

Aniq yetishmaydigan imkoniyat: TradingView Desktop'da grafikka indikator/chizma qo'shadigan rasmiy API YO'Q (UI
Automation 0 element beradi; Charting Library — o'z saytiga joylash uchun; webhook — faqat chiquvchi alert). Shuning
uchun agent grafikni O'ZI o'zgartirmaydi: tekshirilgan Pine kod tayyorlanadi, egasi Pine Editor'ga qo'yadi, keyin kod
TradingView oynasini (faqat o'sha oyna, PrintWindow — fokus/holat o'zgarmaydi) OCR qilib haqiqiy holatni tekshiradi.

Holat qoidasi (verification.py da ham majburiy):
  SUCCESS     — annotatsiyalar to'g'ri grafikda ko'rindi (OCR dalili: ID, simulyatsiya yozuvi, barcha darajalar va
                indikatorning o'zi tasdiqlagan "Chart matches scenario" — instrument va taymfreym);
  PARTIAL     — Pine tayyor, lekin grafikda tasdiqlanmagan;
  FAILED      — Pine yaratilmadi yoki tekshiruvdan o'tmadi;
  NEEDS_SETUP — kerakli integratsiya yo'q (boshqa qurilma, interaktiv sessiya yo'q, ilova o'rnatilmagan).
Kompilyatsiya faqat TradingView'da tasdiqlanadi: indikator jadvali grafikda ko'ringan bo'lsa — kompilyatsiya o'tgan.

Asos: agent o'zi yozgan data/skript/tv_pine.py (PrintWindow + RapidOCR + jadvaldagi moslik belgisi g'oyasi).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

DISCLAIMER = "SIMULATED RESEARCH - NOT ADVICE"
MATCH_TEXT = "Chart matches scenario"
WRONG_TEXT = "WRONG CHART"
TF_CODES = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "1d": "D",
            "1w": "W"}
BANNED = [
    (r"\bstrategy\s*\(|\bstrategy\.\w+", "strategy()/buyurtma funksiyalari (faqat indicator ruxsat)"),
    (r"\brequest\.\w+|\bsecurity\s*\(", "request.*/security() — boshqa ma'lumot manbasi"),
    (r"\balert(?:condition)?\s*\(", "alert() — tashqi xabar"),
    (r"\bstudy\s*\(", "eski study() (v4 va undan oldin)"),
    (r"\blibrary\s*\(|\bimport\s+\w+/", "library/import — tekshirilmagan tashqi kod"),
    (r"\bplotshape\s*\(|\bplotchar\s*\(|\bplot\s*\(", "plot*() — har shamda takroriy belgi (annotatsiya dublikati)"),
]
ALLOWED_CALLS = {"indicator", "hline", "table.new", "table.cell", "color.new", "input.float", "input.int",
                 "input.string", "input.bool", "str.tostring"}
_LOWER = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z", "и": "i", "й": "y",
    "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "ў": "o'", "қ": "q", "ғ": "g'", "ҳ": "h", "ʻ": "'", "ʼ": "'", "‘": "'", "’": "'", "—": "-", "–": "-", "…": "...",
    "≥": ">=", "≤": "<=", "→": "->", "∓": "-/+", "±": "+/-"}
_TRANSLIT = str.maketrans({**_LOWER, **{k.upper(): v.capitalize() for k, v in _LOWER.items() if k.isalpha()}})


class ScenarioError(ValueError):
    pass


def ascii_text(text: str, limit: int = 110) -> str:
    """Pine qatoriga xavfsiz matn: kirill -> lotin, faqat ASCII, qo'shtirnoq/teskari slash yo'q."""
    t = str(text or "").translate(_TRANSLIT)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r'["\\\t\r\n]+', " ", t)
    t = " ".join(t.split())
    return t[:limit].rstrip()


def tv_ticker(symbol: str) -> str:
    """Tadqiqot belgisi -> TradingView syminfo.ticker (XAU/USD -> XAUUSD, BTCUSDT -> BTCUSDT)."""
    t = re.sub(r"[^A-Z0-9]", "", str(symbol).upper())
    if not re.fullmatch(r"[A-Z0-9]{3,20}", t):
        raise ScenarioError(f"instrument noto'g'ri: {symbol!r}")
    return t


def tf_code(timeframe: str) -> str:
    code = TF_CODES.get(str(timeframe).strip().lower())
    if code is None:
        raise ScenarioError(f"taymfreym noma'lum: {timeframe!r} (ruxsat: {', '.join(TF_CODES)})")
    return code


def _num(x: float) -> str:
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.8f}".rstrip("0").rstrip(".")


def _flt(x: float) -> str:
    t = _num(x)
    return t if "." in t else t + ".0"


@dataclass
class Scenario:
    id: str
    symbol: str  # tadqiqotdagi belgi (BTCUSDT, XAU/USD)
    ticker: str  # TradingView syminfo.ticker
    exchange: str  # tavsiya etiladigan birja prefiksi (BINANCE, OANDA...)
    timeframe: str  # 1h
    direction: str  # LONG | SHORT
    entry_type: str
    entry: float
    sl: float
    tps: list[float]
    strategy: str
    version: str
    created: str  # ISO, vaqt mintaqasi bilan
    invalidation: str
    source: str = "research-db"
    content_hash: str = ""

    @property
    def tf(self) -> str:
        return tf_code(self.timeframe)

    def levels(self) -> list[tuple[str, str, float]]:
        out = [("ENTRY", f"SIM ENTRY {_num(self.entry)}", float(self.entry)),
               ("SL", f"SIM SL {_num(self.sl)}", float(self.sl))]
        for i, t in enumerate(self.tps, 1):
            out.append((f"TP{i}", f"SIM TP{i} {_num(t)}", float(t)))
        return out

    def fingerprint(self) -> str:
        key = json.dumps([self.ticker, self.tf, self.direction, float(self.entry), float(self.sl),
                          [float(t) for t in self.tps], self.id])
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def chart_url(self) -> str:
        sym = f"{self.exchange}:{self.ticker}" if self.exchange else self.ticker
        return f"https://www.tradingview.com/chart/?symbol={sym}&interval={self.tf}"


def validate_scenario(sc: Scenario) -> None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", sc.id or ""):
        raise ScenarioError("ID faqat harf/raqam/_-. (3-40)")
    tv_ticker(sc.ticker)
    tf_code(sc.timeframe)
    if sc.direction not in ("LONG", "SHORT"):
        raise ScenarioError("yo'nalish LONG yoki SHORT")
    if not sc.tps:
        raise ScenarioError("kamida bitta TP kerak")
    nums = [sc.entry, sc.sl, *sc.tps]
    for n in nums:
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0:
            raise ScenarioError(f"daraja noto'g'ri: {n!r}")
    if sc.direction == "LONG":
        ok = sc.sl < sc.entry and all(t > sc.entry for t in sc.tps) and sc.tps == sorted(sc.tps)
    else:
        ok = sc.sl > sc.entry and all(t < sc.entry for t in sc.tps) and sc.tps == sorted(sc.tps, reverse=True)
    if not ok:
        raise ScenarioError(f"{sc.direction} uchun SL / kirish / TP tartibi mantiqsiz")
    if len({float(x) for x in nums}) != len(nums):
        raise ScenarioError("takroriy daraja (dublikat annotatsiya)")
    try:
        dt = datetime.fromisoformat(sc.created)
    except ValueError:
        raise ScenarioError("ssenariy vaqti ISO formatda emas") from None
    if dt.tzinfo is None:
        raise ScenarioError("ssenariy vaqtida vaqt mintaqasi yo'q")
    for name in ("strategy", "version", "invalidation"):
        if not getattr(sc, name) or ascii_text(getattr(sc, name)) != getattr(sc, name):
            raise ScenarioError(f"{name}: bo'sh yoki ASCII bo'lmagan matn")


def exchange_for(symbol: str, data_source: str = "") -> str:
    if "binance" in (data_source or "").lower() or symbol.upper().endswith("USDT"):
        return "BINANCE"
    if "/" in symbol:
        return "OANDA"
    return ""


def scenario_from_analysis(rec: dict) -> Scenario:
    """O'zgarmas tadqiqot yozuvidan (analyses.payload). Darajalar O'ZGARTIRILMAYDI."""
    if rec.get("kind") != "TRADE":
        raise ScenarioError(f"{rec.get('analysis_id')}: NO-TRADE tahlilda kirish/SL/TP yo'q — grafik annotatsiyasi "
                            "tayyorlanmaydi")
    inv = rec.get("invalidation") or {}
    sc = Scenario(
        id=rec["analysis_id"], symbol=rec["symbol"], ticker=tv_ticker(rec["symbol"]),
        exchange=exchange_for(rec["symbol"], rec.get("data_source", "")), timeframe=rec["timeframe"],
        direction=rec["direction"], entry_type=rec.get("entry_type") or "", entry=float(rec["entry"]),
        sl=float(rec["sl"]), tps=[float(rec["tp"])], strategy=ascii_text(rec.get("strategy_id") or "", 40),
        version=str(rec.get("strategy_version")), created=rec["created_at"],
        invalidation=ascii_text(f"{inv.get('text', '')} ({_num(inv['level'])})" if inv.get("level") is not None
                                else inv.get("text", "") or "-"),
        source="research-db", content_hash=rec.get("content_hash", ""))
    validate_scenario(sc)
    return sc


def scenario_manual(data: dict) -> Scenario:
    tps = data.get("tp")
    tps = [float(x) for x in (tps if isinstance(tps, list) else [tps])] if tps is not None else []
    sc = Scenario(
        id=str(data.get("id") or ""), symbol=str(data.get("symbol") or ""), ticker=tv_ticker(data.get("symbol") or ""),
        exchange=str(data.get("exchange") or exchange_for(str(data.get("symbol") or ""))).upper(),
        timeframe=str(data.get("timeframe") or ""), direction=str(data.get("direction") or "").upper(),
        entry_type=str(data.get("entry_type") or ""), entry=float(data.get("entry") or 0), sl=float(data.get("sl") or 0),
        tps=tps, strategy=ascii_text(data.get("strategy") or "Manual", 40), version=ascii_text(str(data.get("version") or "0"), 12),
        created=str(data.get("created") or ""), invalidation=ascii_text(data.get("invalidation") or ""),
        source="manual")
    validate_scenario(sc)
    return sc


# -------------------------------------------------------------------------------------------- Pine generatsiya
def generate(sc: Scenario) -> str:
    validate_scenario(sc)
    lv = sc.levels()
    colors = {"ENTRY": "color.blue", "SL": "color.red"}
    rows = [DISCLAIMER, f"ID {sc.id}", f"{sc.strategy} v{sc.version} {sc.direction}", f"Created {sc.created}"]
    rows += [title for _, title, _ in lv]
    rows.append(f"INVALID: {sc.invalidation}")
    n = len(rows) + 1
    out = ["//@version=5",
           "// SIMULATED RESEARCH ONLY - hypothetical paper-trading levels, not financial advice, not guaranteed.",
           f"// ID: {sc.id} | Strategy: {sc.strategy} v{sc.version} | Created: {sc.created} | FP: {sc.fingerprint()}",
           f"// Expected chart: {sc.exchange + ':' if sc.exchange else ''}{sc.ticker}, timeframe {sc.timeframe} ({sc.tf})",
           f'indicator("SENTINAL SIM {sc.id}", overlay=true)',
           f'EXPECT_TICKER = "{sc.ticker}"',
           f'EXPECT_TF = "{sc.tf}"']
    for kind, title, price in lv:
        out.append(f'hline({_flt(price)}, "{title}", color={colors.get(kind, "color.green")}, linewidth=2, '
                   "linestyle=hline.style_solid)")
    out.append(f"var table info = table.new(position.middle_left, 1, {n}, bgcolor=color.new(color.black, 25), "
               "border_width=1)")
    out.append("if barstate.islast")
    for i, r in enumerate(rows):
        out.append(f'    table.cell(info, 0, {i}, "{r}", text_color={"color.yellow" if i == 0 else "color.white"}, '
                   "text_size=size.normal)")
    out.append("    chartOk = syminfo.ticker == EXPECT_TICKER and timeframe.period == EXPECT_TF")
    out.append(f'    table.cell(info, 0, {n - 1}, chartOk ? "{MATCH_TEXT}" : "{WRONG_TEXT}: expected {sc.ticker} {sc.tf}", '
               "text_color=chartOk ? color.lime : color.red, text_size=size.normal)")
    return "\n".join(out) + "\n"


# -------------------------------------------------------------------------------------------- statik tekshiruv
def _code_only(code: str) -> str:
    no_str = re.sub(r'"[^"\n]*"', '""', code)
    return "\n".join(ln if ln.startswith("//@") else ln.split("//")[0] for ln in no_str.split("\n"))


@dataclass
class Validation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    compiled: str = "tasdiqlanmagan (faqat TradingView kompilyatsiya qiladi)"


def validate_pine(code: str, sc: Scenario) -> Validation:
    """Statik tekshiruv. TradingView kompilyatsiyasi O'RNINI BOSMAYDI."""
    err: list[str] = []
    lines = code.split("\n")
    m = re.match(r"//@version=(\d+)\s*$", lines[0] if lines else "")
    if not m:
        err.append("1-qatorda //@version=N yo'q")
    elif m.group(1) not in ("5", "6"):
        err.append(f"Pine v{m.group(1)} qo'llab-quvvatlanmaydi (5 yoki 6)")
    if "\t" in code:
        err.append("tab belgisi bor (Pine chekinishi bo'shliq bilan)")
    if any(ord(c) > 126 for c in code):
        err.append("ASCII bo'lmagan belgi bor")
    bare = _code_only(code)
    for pat, why in BANNED:
        if re.search(pat, bare):
            err.append(f"taqiqlangan: {why}")
    if code.count('"') % 2:
        err.append("qo'shtirnoqlar juft emas")
    for a, b in (("(", ")"), ("[", "]")):
        if bare.count(a) != bare.count(b):
            err.append(f"'{a}{b}' balansi buzuq")
    if len(re.findall(r"^indicator\(", bare, re.M)) != 1:
        err.append("indicator() aynan bitta bo'lishi kerak")
    calls = set(re.findall(r"\b([a-z_][\w]*(?:\.[a-z_]\w*)?)\s*\(", bare))
    unknown = sorted(c for c in calls if c not in ALLOWED_CALLS)
    if unknown:
        err.append("ruxsat ro'yxatida yo'q funksiya(lar): " + ", ".join(unknown))
    for i, ln in enumerate(lines, 1):
        if ln.strip() and not ln.startswith("//") and (len(ln) - len(ln.lstrip(" "))) % 4:
            err.append(f"{i}-qator: chekinish 4 ga karrali emas")
    hl = re.findall(r'^hline\(([0-9.]+),\s*"([^"]+)"', code, re.M)
    exp = sc.levels()
    if len(hl) != len(exp):
        err.append(f"hline soni {len(hl)}, kutilgan {len(exp)}")
    titles, prices = [t for _, t in hl], [float(p) for p, _ in hl]
    if len(set(titles)) != len(titles) or len(set(prices)) != len(prices):
        err.append("takroriy annotatsiya (dublikat hline)")
    for _, title, price in exp:
        if not any(abs(price - p) <= 1e-9 * max(1.0, price) and title == t for p, t in zip(prices, titles)):
            err.append(f"yo'q yoki asl ssenariydan farq qiladi: {title}")
    for need, label in ((DISCLAIMER, "simulyatsiya belgisi"), (f"ID {sc.id}", "analysis ID"),
                        (f"{sc.strategy} v{sc.version}", "strategiya nomi va versiyasi"), (sc.created, "ssenariy vaqti"),
                        (f"INVALID: {sc.invalidation}", "bekor qilish sharti"),
                        (f'EXPECT_TICKER = "{sc.ticker}"', "instrument"), (f'EXPECT_TF = "{sc.tf}"', "taymfreym"),
                        (MATCH_TEXT, "grafik moslik tekshiruvi")):
        if need not in code:
            err.append(f"yo'q: {label}")
    low = code.lower()
    if re.search(r"\bguarantee", low) and "not guaranteed" not in low:
        err.append("'guaranteed' — kafolat sifatida ko'rsatish taqiqlangan")
    return Validation(ok=not err, errors=err, warnings=["faqat statik tekshiruv"],
                      annotations=[t for _, t, _ in exp] + [DISCLAIMER, f"ID {sc.id}", MATCH_TEXT])


# -------------------------------------------------------------------------------------------- saqlash
class PineStore:
    """trading_memory/pine/: mavjud faylni HECH QACHON ustiga yozmaydi; bir xil ssenariy qayta saqlanmaydi."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.index_path = self.root / "index.json"

    def _index(self) -> dict:
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def save(self, sc: Scenario, code: str, validation: Validation) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        idx = self._index()
        fp = sc.fingerprint()
        digest = hashlib.sha256(code.encode()).hexdigest()
        if fp in idx and Path(idx[fp]["file"]).is_file():
            same = hashlib.sha256(Path(idx[fp]["file"]).read_bytes()).hexdigest() == digest
            return {"status": "duplicate" if same else "exists", "file": idx[fp]["file"], "fingerprint": fp}
        base = self.root / f"{sc.ticker}_{sc.tf}_{sc.id}"
        path, n = base.with_suffix(".pine"), 1
        while path.exists():  # boshqa tarkibli fayl — yangi versiya nomi, eskisi tegilmaydi
            n += 1
            path = base.parent / f"{base.name}_v{n}.pine"
        with open(path, "x", encoding="ascii", newline="\n") as fh:
            fh.write(code)
        idx[fp] = {"id": sc.id, "file": str(path), "sha256": digest, "created": datetime.now().astimezone().isoformat(
            timespec="seconds"), "scenario": asdict(sc), "annotations": validation.annotations}
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.index_path)
        return {"status": "saved", "file": str(path), "fingerprint": fp}

    def find(self, scenario_id: str) -> dict | None:
        matches = [v for v in self._index().values() if v["id"] == scenario_id]
        return matches[-1] if matches else None  # indeks qo'shilish tartibida — oxirgisi eng yangi


def install_steps(sc: Scenario, path: str, clipboard: bool) -> str:
    return "\n".join([
        f"1. TradingView'da {sc.exchange + ':' if sc.exchange else ''}{sc.ticker} grafigini oching, taymfreym {sc.timeframe} "
        f"(kod: {sc.tf}). Brauzerda: {sc.chart_url()}",
        "2. Pastdagi Pine Editor -> barcha matnni tanlang -> " + ("clipboarddagi kodni qo'ying" if clipboard else
                                                                  f"{path} fayl tarkibini qo'ying") + " -> Add to chart.",
        "3. Kompilyatsiya xatosi chiqsa — xato matnini yuboring (kod TradingView'da tasdiqlanmagan).",
        f"4. Grafikda chap tomondagi jadvalda '{MATCH_TEXT}' yozuvi chiqishi kerak; 'WRONG CHART' chiqsa — instrument yoki "
        "taymfreym boshqa.",
        "5. Shundan keyin agentga 'tekshir' deng: TradingView oynasi skrinshot + OCR bilan tekshiriladi.",
        "Darajalar — simulyatsiya (paper trading) tadqiqoti, kafolatlangan savdo imkoniyati emas.",
    ])


# -------------------------------------------------------------------------------------------- clipboard
def copy_to_clipboard(text: str) -> bool:
    """Windows clipboard (CF_UNICODETEXT) + qayta o'qib solishtirish."""
    try:
        import win32clipboard
        import win32con
    except ImportError:
        return False
    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        win32clipboard.OpenClipboard()
        try:
            back = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return back.replace("\r\n", "\n").rstrip() == text.replace("\r\n", "\n").rstrip()
    except Exception:  # noqa: BLE001 — clipboard boshqa dastur tomonidan band bo'lishi mumkin
        return False


# -------------------------------------------------------------------------------------------- qurilma va sessiya
LOCAL_ALIASES = {"", "local", "localhost", "this", "shu", "main", "asosiy"}


def resolve_device(device: str, computer: str | None = None, known_remote: set[str] | None = None) -> tuple[str, str]:
    """-> (turi, nomi): ('local', 'XS-NB-AUP06') | ('remote', 'nb-xs-tex02') | ('ambiguous', sabab)."""
    computer = (computer or os.environ.get("COMPUTERNAME", "")).upper()
    d = (device or "").strip()
    if d.lower() in LOCAL_ALIASES or d.upper() == computer:
        return "local", computer
    remote = {r.lower() for r in (known_remote or set())}
    if d.lower() in remote or d.split(".")[0].lower() in remote:
        return "remote", d
    if not d:
        return "ambiguous", "qurilma ko'rsatilmagan"
    return "ambiguous", f"'{d}' na shu kompyuter ({computer}), na inventardagi qurilma"


def interactive_session() -> tuple[bool, str]:
    """Agent jarayoni foydalanuvchining faol (konsol) sessiyasida va ish stoli qulflanmagan bo'lsa — GUI mavjud."""
    if os.name != "nt":
        return False, "Windows emas"
    import ctypes
    from ctypes import wintypes
    k32, u32 = ctypes.windll.kernel32, ctypes.windll.user32
    sid = wintypes.DWORD()
    k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    console = k32.WTSGetActiveConsoleSessionId()
    if sid.value == 0:
        return False, "agent 0-sessiyada (xizmat) — foydalanuvchi ish stoli yo'q"
    if sid.value != console:
        return False, f"agent sessiyasi ({sid.value}) faol konsol sessiyasi ({console}) emas (masalan RDP yoki fon)"
    desk = u32.OpenInputDesktop(0, False, 0x0100)  # DESKTOP_SWITCHDESKTOP
    if not desk:
        return False, "ish stoli qulflangan (Win+L) yoki ekran saqlovchi yoqilgan"
    u32.CloseDesktop(desk)
    return True, f"interaktiv sessiya {sid.value}"


def tradingview_installed() -> tuple[bool, str]:
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-AppxPackage -Name TradingView.Desktop | Select-Object -First 1 -ExpandProperty Version"],
                           capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        ver = (r.stdout or "").strip()
        if ver:
            return True, f"TradingView Desktop {ver}"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False, "TradingView Desktop (MSIX) topilmadi"


BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "browser.exe"}
TARGETS = ("auto", "desktop", "browser")
NO_WINDOW = {
    "desktop": "TradingView Desktop oynasi topilmadi (ilova yopiq yoki yashirin)",
    "browser": "brauzerda faol TradingView yorlig'i topilmadi (fon yorlig'i rasmga tushmaydi — yorliqni oching)",
    "auto": "ochiq TradingView oynasi yo'q: Desktop ham, brauzerdagi faol TradingView yorlig'i ham topilmadi"}


def tv_like_title(title: str, ticker: str = "") -> bool:
    """Brauzer oynasining FAOL yorlig'i TradingView grafigiga o'xshaydimi ('BTCUSD 75 817,22 ▼ −0.25% Unnamed').
    Sarlavha faqat QAYSI oynaga qarashni tanlaydi — grafik holatining dalili emas."""
    t = title or ""
    return "tradingview" in t.lower() or bool(re.search("[\u25b2\u25bc]", t)) or \
        bool(ticker and _norm(ticker) in _norm(t))


def find_windows(target: str = "auto", ticker: str = "") -> list[dict]:
    """Ko'rinadigan TradingView oynalari: Desktop (TradingView.exe) va/yoki brauzer oynasi, faol yorlig'i TradingView'ga
    o'xshasa. Boshqa ilovalar olinmaydi. Brauzerda faqat faol yorliq rasmga tushadi."""
    try:
        import win32gui
        import win32process
        import psutil
    except ImportError:
        return []
    found: list[dict] = []

    def cb(h, _):
        title = win32gui.GetWindowText(h)
        if not (win32gui.IsWindowVisible(h) and title):
            return
        pid = win32process.GetWindowThreadProcessId(h)[1]
        try:
            name = psutil.Process(pid).name().lower()
        except (psutil.Error, OSError):
            return
        if name == "tradingview.exe" and target in ("auto", "desktop"):
            found.append({"hwnd": h, "title": title, "kind": "desktop"})
        elif name in BROWSERS and target in ("auto", "browser") and tv_like_title(title, ticker):
            found.append({"hwnd": h, "title": title, "kind": "browser"})
    win32gui.EnumWindows(cb, None)
    found.sort(key=lambda w: w["kind"] != "desktop")
    return found[:4]


def environment(device: str, known_remote: set[str] | None = None, target: str = "auto", ticker: str = "") -> dict:
    target = target if target in TARGETS else "auto"
    kind, name = resolve_device(device, known_remote=known_remote)
    out = {"device": name, "kind": kind, "computer": os.environ.get("COMPUTERNAME", ""), "ready": False,
           "target": target}
    if kind == "ambiguous":
        out.update(state="ambiguous", reason=f"Qurilma noaniq: {name}. Egasidan so'rang: shu noutbuk "
                                             f"({out['computer']}) yoki boshqa qurilma?")
        return out
    if kind == "remote":
        out.update(state="needs_setup", reason=f"{name} — masofaviy qurilma: WinRM/SSH sessiyasida foydalanuvchi ish "
                                               "stoli yo'q, TradingView oynasini ko'rib ham, tekshirib ham bo'lmaydi. Pine "
                                               "faylni o'sha qurilmada qo'lda o'rnatish kerak.")
        return out
    ok_inst, inst = tradingview_installed()
    ok_sess, sess = interactive_session()
    wins = find_windows(target, ticker)
    out.update(installed=ok_inst, install_info=inst, interactive=ok_sess, session_info=sess,
               windows=[{"kind": w["kind"], "title": w["title"]} for w in wins],
               window=bool(wins), window_title=wins[0]["title"] if wins else None,
               screenshot_allowed=os.environ.get("TRADINGVIEW_SCREENSHOT", "1").strip() not in ("0", "false", "no"))
    if not ok_sess:
        out.update(state="needs_setup", reason=sess)
    elif not out["screenshot_allowed"]:
        out.update(state="needs_setup", reason="skrinshot ruxsati o'chirilgan (TRADINGVIEW_SCREENSHOT=0)")
    elif target == "desktop" and not ok_inst:
        out.update(state="needs_setup", reason=inst)
    elif not wins and target == "auto" and not ok_inst:
        out.update(state="needs_setup", reason=f"{inst}; brauzerda ham faol TradingView yorlig'i yo'q")
    elif not wins:
        out.update(state="unverified", reason=NO_WINDOW[target])
    else:
        kinds = ", ".join("Desktop" if w["kind"] == "desktop" else "brauzer" for w in wins)
        out.update(state="ready", ready=True, reason=f"TradingView oynasi topildi: {kinds}")
    return out


# -------------------------------------------------------------------------------------------- vizual tekshiruv
def capture(hwnd: int, out_png: Path) -> tuple[bool, str]:
    """Faqat TradingView oynasi (PrintWindow, PW_RENDERFULLCONTENT). Oynani faollashtirmaydi va o'zgartirmaydi."""
    import ctypes

    import win32gui
    import win32ui
    from PIL import Image
    if ctypes.windll.user32.IsIconic(hwnd):
        return False, "oyna minimallashtirilgan — skrinshot olib bo'lmaydi (oynani oching)"
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    w, h = right - left, bottom - top
    if w < 300 or h < 300:
        return False, "oyna juda kichik"
    hdc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hdc)
    mem = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, w, h)
    mem.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, mem.GetSafeHdc(), 2)
    info, bits = bmp.GetInfo(), bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    mem.DeleteDC()
    mfc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hdc)
    win32gui.DeleteObject(bmp.GetHandle())
    if not ok:
        return False, "PrintWindow muvaffaqiyatsiz"
    lo, hi = img.convert("L").resize((64, 64)).getextrema()
    if hi - lo < 8:
        return False, "skrinshot bo'sh (oyna tarkibi berilmadi)"
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return True, str(out_png)


def ocr_items(png: Path) -> list[tuple[str, float]]:
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    width = Image.open(png).size[0]
    result, _ = RapidOCR()(str(png))
    rows = [(min(p[1] for p in box), min(p[0] for p in box), txt) for box, txt, _conf in (result or [])]
    rows.sort(key=lambda r: (round(r[0] / 12), r[1]))
    return [(txt, x / width) for _y, x, txt in rows]


def _norm(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def evaluate(items: list[tuple[str, float]], sc: Scenario) -> dict:
    """OCR matni bo'yicha dalil. Oyna sarlavhasi hisobga OLINMAYDI."""
    text = _norm(" ".join(t for t, _ in items))
    marker = _norm(f"ID {sc.id}")
    res = {"symbol_text": _norm(sc.ticker) in text,
           "wrong_chart": _norm(WRONG_TEXT) in text,
           "disclaimer": _norm(DISCLAIMER) in text,
           "analysis_id": marker in text,
           "indicator_copies": text.count(marker),
           "levels": {title: _norm(title) in text for _, title, _ in sc.levels()}}
    # Instrument + taymfreym dalili: indikatorning o'zi syminfo.ticker va timeframe.period ni solishtirib yozadi.
    res["chart_match"] = _norm(MATCH_TEXT) in text and not res["wrong_chart"]
    res["symbol"] = res["symbol_text"] or res["chart_match"]  # indikator syminfo.ticker ni o'zi tasdiqlagan
    res["missing"] = [k for k in ("symbol", "disclaimer", "analysis_id", "chart_match") if not res[k]] + \
        [t for t, v in res["levels"].items() if not v]
    res["duplicate_indicator"] = res["indicator_copies"] > 1
    res["confirmed"] = not res["missing"] and not res["duplicate_indicator"]
    return res


def is_tradingview_page(items: list[tuple[str, float]], sc: Scenario) -> bool:
    """Brauzer rasmi haqiqatan TradingView sahifasimi: manzil satri (tradingview.com) yoki indikatorning o'z belgisi.
    Aks holda rasm begona sahifa — saqlanmaydi."""
    text = _norm(" ".join(t for t, _ in items))
    return "TRADINGVIEW" in text or _norm(f"ID {sc.id}") in text or _norm(DISCLAIMER) in text


def chart_status(valid: bool, env_state: str, verification: dict | None) -> str:
    if not valid:
        return "FAILED"
    if verification and verification.get("confirmed"):
        return "SUCCESS"
    if env_state in ("needs_setup", "ambiguous"):
        return "NEEDS_SETUP"
    return "PARTIAL"
