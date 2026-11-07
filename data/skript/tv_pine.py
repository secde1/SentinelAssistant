"""TradingView chart annotation tayyorlash (SENTINAL AI, V17).

Qiladi: ssenariy -> Pine v5 kod -> statik tekshiruv -> xavfsiz saqlash (dublikatsiz) -> clipboard
-> (ixtiyoriy) TradingView oynasi skrinshoti + OCR orqali holatni tekshirish -> rost status.
Qilmaydi: TradingView ichiga sichqoncha/klaviatura yubormaydi, kompilyatsiyani "tasdiqlangan" demaydi.

CLI:
  python tv_pine.py prepare --scenario s.json|--legacy-btc [--check-price]
  python tv_pine.py clip --id ID
  python tv_pine.py verify --id ID --device COMPUTERNAME
  python tv_pine.py device
"""
import argparse, ctypes, hashlib, json, math, os, re, subprocess, sys
from datetime import datetime

HOME = os.environ.get("AGENT_HOME", r"D:\it-agent\data")
PINE_DIR = os.path.join(HOME, "ish", "trading", "pine")
VERIFY_DIR = os.path.join(HOME, "ish", "trading", "verify")
INDEX = os.path.join(PINE_DIR, "index.json")

TF_MAP = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120",
          "4h": "240", "1d": "D", "1w": "W"}
TF_TOKENS = {"1": ["1M"], "5": ["5M"], "15": ["15M"], "30": ["30M"], "60": ["1H", "60"],
             "120": ["2H"], "240": ["4H"], "D": ["1D"], "W": ["1W"]}
BANNED = [r"\bstrategy\s*\(", r"\bstrategy\.", r"\bstudy\s*\(", r"\brequest\.", r"\bsecurity\s*\(",
          r"\balert\s*\(", r"\balertcondition\s*\(", r"//@version=[1-4]\b"]
DISCLAIMER = "SIMULATED RESEARCH - NOT ADVICE"


# ---------------- ssenariy ----------------
def timeframe_code(tf):
    t = str(tf).strip().lower()
    code = TF_MAP.get(t, t.upper() if t.upper() == "D" else t)
    if code not in TF_TOKENS:
        raise ValueError(f"noma'lum timeframe: {tf}")
    return code


def _ascii_safe(s, field, maxlen=110):
    if not isinstance(s, str) or not s.strip():
        raise ValueError(f"{field} bo'sh")
    if any(ord(c) > 126 or ord(c) < 32 for c in s) or '"' in s or "\\" in s:
        raise ValueError(f"{field}: faqat ASCII, tirnoq va teskari slash yo'q")
    if len(s) > maxlen:
        raise ValueError(f"{field} juda uzun (> {maxlen})")
    return s.strip()


def validate_scenario(s):
    """Raqamli kirishlar va mantiqiy tartib. Xato bo'lsa ValueError."""
    for k in ("id", "symbol", "timeframe", "side", "entry", "sl", "tp", "strategy", "version",
              "created", "invalidation"):
        if k not in s:
            raise ValueError(f"ssenariyda '{k}' yo'q")
    _ascii_safe(s["id"], "id", 40)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", s["id"]):
        raise ValueError("id faqat harf/raqam/_-.")
    if not re.fullmatch(r"[A-Z0-9]{3,20}", s["symbol"]):
        raise ValueError("symbol katta harf/raqam (masalan BTCUSDT)")
    timeframe_code(s["timeframe"])
    side = s["side"].upper()
    if side not in ("SHORT", "LONG"):
        raise ValueError("side SHORT yoki LONG")
    tps = s["tp"]
    if not isinstance(tps, list) or not tps:
        raise ValueError("kamida bitta TP kerak")
    nums = [s["entry"], s["sl"]] + list(tps)
    for n in nums:
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0:
            raise ValueError(f"noto'g'ri daraja: {n!r}")
    e, sl = float(s["entry"]), float(s["sl"])
    if side == "SHORT":
        ok = sl > e and all(e > t for t in tps) and list(tps) == sorted(tps, reverse=True)
    else:
        ok = sl < e and all(e < t for t in tps) and list(tps) == sorted(tps)
    if not ok:
        raise ValueError(f"{side} uchun SL/entry/TP tartibi noto'g'ri")
    if len(set(float(x) for x in nums)) != len(nums):
        raise ValueError("takroriy daraja (duplicate)")
    datetime.fromisoformat(s["created"])
    _ascii_safe(s["strategy"], "strategy", 40)
    _ascii_safe(str(s["version"]), "version", 12)
    _ascii_safe(s["invalidation"], "invalidation")
    return True


def fingerprint(s):
    key = json.dumps([s["symbol"], timeframe_code(s["timeframe"]), s["side"].upper(),
                      float(s["entry"]), float(s["sl"]), [float(t) for t in s["tp"]]])
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def _lbl(x):
    x = float(x)
    return str(int(x)) if x == int(x) else f"{x:.8f}".rstrip("0")


def _flt(x):
    t = _lbl(x)
    return t if "." in t else t + ".0"


def levels(s):
    """[(kind, title, price)] - kutiladigan annotatsiyalar tartibi bilan."""
    out = [("ENTRY", f"SIM ENTRY {_lbl(s['entry'])}", float(s["entry"])),
           ("SL", f"SIM SL {_lbl(s['sl'])}", float(s["sl"]))]
    for i, t in enumerate(s["tp"], 1):
        out.append((f"TP{i}", f"SIM TP{i} {_lbl(t)}", float(t)))
    return out


# ---------------- Pine generatsiya ----------------
def generate_pine(s):
    validate_scenario(s)
    lv = levels(s)
    tf = timeframe_code(s["timeframe"])
    colors = {"ENTRY": "color.blue", "SL": "color.red"}
    L = ["//@version=5",
         "// SIMULATED RESEARCH ONLY - hypothetical levels, not financial advice.",
         f"// ID: {s['id']} | Strategy: {s['strategy']} v{s['version']} | Created: {s['created']} | FP: {fingerprint(s)}",
         f'indicator("SENTINAL SIM {s["id"]}", overlay=true)',
         f'EXPECT_TICKER = "{s["symbol"]}"',
         f'EXPECT_TF = "{tf}"']
    for kind, title, price in lv:
        c = colors.get(kind, "color.green")
        L.append(f'hline({_flt(price)}, "{title}", color={c}, linewidth=2, linestyle=hline.style_solid)')
    rows = [DISCLAIMER,
            f"ID {s['id']}",
            f"{s['strategy']} v{s['version']} {s['side'].upper()}",
            f"Created {s['created']}"]
    rows += [f"{title}" for _, title, _ in lv]
    rows.append(f"INVALID: {s['invalidation']}")
    n = len(rows) + 1
    L.append(f"var table info = table.new(position.middle_left, 1, {n}, bgcolor=color.new(color.black, 25), border_width=1)")
    L.append("if barstate.islast")
    for i, r in enumerate(rows):
        col = "color.yellow" if i == 0 else "color.white"
        L.append(f'    table.cell(info, 0, {i}, "{r}", text_color={col}, text_size=size.small)')
    L.append("    chartOk = syminfo.ticker == EXPECT_TICKER and timeframe.period == EXPECT_TF")
    L.append(f'    table.cell(info, 0, {n - 1}, chartOk ? "Chart matches scenario" : "WRONG CHART: expected {s["symbol"]} {tf}", '
             "text_color=chartOk ? color.lime : color.red, text_size=size.small)")
    return "\n".join(L) + "\n"


# ---------------- statik tekshiruv ----------------
def _strip(code):
    no_str = re.sub(r'"[^"\n]*"', '""', code)
    return "\n".join(l.split("//")[0] if not l.startswith("//@") else l for l in no_str.split("\n"))


def validate_pine(code, s):
    """Statik tekshiruv. TradingView kompilyatsiyasi O'RNINI BOSMAYDI."""
    err, warn = [], []
    lines = code.split("\n")
    m = re.match(r"//@version=(\d+)\s*$", lines[0] if lines else "")
    if not m:
        err.append("1-qatorda //@version=N yo'q")
    elif m.group(1) not in ("5", "6"):
        err.append(f"version {m.group(1)} qo'llab-quvvatlanmaydi")
    if "\t" in code:
        err.append("tab belgisi bor")
    bare = _strip(code)
    for pat in BANNED:
        if re.search(pat, code if "version" in pat else bare):
            err.append(f"taqiqlangan konstruksiya: {pat}")
    if bare.count('"') % 2 or code.count('"') % 2:
        err.append("tirnoqlar juft emas")
    if bare.count("(") != bare.count(")"):
        err.append("qavslar balansi buzuq")
    if len(re.findall(r"^indicator\(", bare, re.M)) != 1:
        err.append("indicator() aynan 1 ta bo'lishi kerak")
    for i, l in enumerate(lines, 1):
        if l.strip() and not l.startswith("//") and (len(l) - len(l.lstrip(" "))) % 4:
            err.append(f"{i}-qator: chekinish 4 ga karrali emas")
    # annotatsiyalar
    hl = re.findall(r'^hline\(([0-9.]+),\s*"([^"]+)"', code, re.M)
    exp = levels(s)
    if len(hl) != len(exp):
        err.append(f"hline soni {len(hl)}, kutilgan {len(exp)}")
    titles = [t for _, t in hl]
    prices = [float(p) for p, _ in hl]
    if len(set(titles)) != len(titles) or len(set(prices)) != len(prices):
        err.append("takroriy annotatsiya (duplicate hline)")
    for _, title, price in exp:
        if not any(abs(price - p) < 1e-9 and title == t for p, t in zip(prices, titles)):
            err.append(f"yo'q: {title}")
    # metama'lumot
    for need, label in ((DISCLAIMER, "simulyatsiya ogohlantirishi"), (s["id"], "analysis ID"),
                        (f"{s['strategy']} v{s['version']}", "strategiya nomi/versiyasi"),
                        (s["created"], "ssenariy vaqti"), (s["invalidation"], "invalidation sharti"),
                        (f'EXPECT_TICKER = "{s["symbol"]}"', "instrument"),
                        (f'EXPECT_TF = "{timeframe_code(s["timeframe"])}"', "timeframe")):
        if need not in code:
            err.append(f"yo'q: {label}")
    if "guaranteed" in code.lower() and "not guaranteed" not in code.lower():
        warn.append("'guaranteed' so'zi uchradi")
    warn.append("faqat statik tekshiruv: TradingView kompilyatsiyasi tasdiqlanmagan")
    return {"ok": not err, "errors": err, "warnings": warn, "hline_count": len(hl)}


def check_price(s, fetch=None, max_dev=0.15):
    """Darajalar joriy narxdan 15% dan uzoq bo'lsa ogohlantirish (instrument taxmini tekshiruvi)."""
    try:
        if fetch is None:
            import requests
            r = requests.get("https://data-api.binance.vision/api/v3/ticker/price",
                             params={"symbol": s["symbol"]}, timeout=10)
            r.raise_for_status()
            px = float(r.json()["price"])
        else:
            px = float(fetch(s["symbol"]))
    except Exception as e:
        return {"checked": False, "note": f"narx olinmadi: {type(e).__name__}"}
    far = [t for _, t, p in levels(s) if abs(p - px) / px > max_dev]
    return {"checked": True, "price": px, "far_levels": far, "ok": not far}


# ---------------- saqlash (dublikatsiz) ----------------
def _load_index(index_path):
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_pine(s, code, pine_dir=PINE_DIR):
    """Mavjud faylni ustiga YOZMAYDI. Bir xil ssenariy ikkinchi marta saqlanmaydi."""
    os.makedirs(pine_dir, exist_ok=True)
    index_path = os.path.join(pine_dir, "index.json")
    idx = _load_index(index_path)
    fp = fingerprint(s)
    if fp in idx and os.path.exists(idx[fp]["file"]):
        return {"status": "duplicate", "file": idx[fp]["file"], "id": idx[fp]["id"]}
    path = os.path.join(pine_dir, f"{s['symbol']}_{timeframe_code(s['timeframe'])}_{s['id']}.pine")
    if os.path.exists(path):
        raise FileExistsError(f"fayl mavjud, ustiga yozilmaydi: {path}")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(code)
    idx[fp] = {"id": s["id"], "file": path, "scenario": s}
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)
    return {"status": "saved", "file": path, "id": s["id"]}


def find_by_id(sid, pine_dir=PINE_DIR):
    for v in _load_index(os.path.join(pine_dir, "index.json")).values():
        if v["id"] == sid:
            return v
    return None


# ---------------- clipboard ----------------
def to_clipboard(path):
    ps = ("$t=[IO.File]::ReadAllText($env:TV_PINE_PATH,[Text.Encoding]::UTF8); Set-Clipboard -Value $t; "
          "if((Get-Clipboard -Raw).TrimEnd() -eq $t.TrimEnd()){'CLIP_OK'}else{'CLIP_MISMATCH'}")
    import shutil
    for name in ("pwsh", "powershell"):
        exe = shutil.which(name) or shutil.which(name + ".exe")
        if not exe:
            continue
        try:
            r = subprocess.run([exe, "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=30,
                               env={**os.environ, "TV_PINE_PATH": path})
        except Exception:
            continue
        if "CLIP_OK" in r.stdout:
            return True
    return False


# ---------------- status ----------------
def task_status(pine_valid, stored, chart_state):
    """chart_state: confirmed | unverified | integration_missing"""
    if not pine_valid:
        return "FAILED"
    if chart_state == "confirmed":
        return "SUCCESS"
    if chart_state == "integration_missing" and not stored:
        return "NEEDS_SETUP"
    return "PARTIAL"


# ---------------- vizual tekshiruv ----------------
def _norm(t):
    return re.sub(r"[^A-Z0-9]", "", t.upper())


def evaluate_ocr(items, s, hint=""):
    """items: [(matn, x_nisbiy 0..1)] o'qish tartibida. Oyna sarlavhasi emas, faqat skrinshot matni."""
    text = _norm("".join(t for t, _ in items))
    tick = _norm(s["symbol"])
    res = {"symbol": tick in text or (bool(hint) and _norm(hint) in text)}
    toks = TF_TOKENS[timeframe_code(s["timeframe"])]
    names = [tick] + ([_norm(hint)] if hint else [])
    res["timeframe_legend_supporting"] = any(re.search(f"{n}.{{0,3}}{re.escape(tk)}", text) for n in names for tk in toks)
    # asosiy dalil: indikator ichidagi Pine o'zi syminfo.ticker/timeframe.period ni solishtiradi
    res["wrong_chart_shown"] = "WRONGCHART" in text
    res["timeframe"] = "CHARTMATCHESSCENARIO" in text and not res["wrong_chart_shown"]
    res["disclaimer"] = _norm(DISCLAIMER) in text
    res["analysis_id"] = _norm("ID " + s["id"]) in text
    res["levels"] = {title: _norm(title) in text for _, title, _ in levels(s)}
    right = _norm("".join(t for t, x in items if x > 0.88))
    res["axis_labels_supporting"] = {title: _lbl(p) in right for _, title, p in levels(s)}
    res["missing"] = [k for k in ("symbol", "timeframe", "disclaimer", "analysis_id") if not res[k]] + \
                     [t for t, v in res["levels"].items() if not v]
    res["confirmed"] = not res["missing"]
    return res


def device_info():
    return {"computer": os.environ.get("COMPUTERNAME", ""), "user": os.environ.get("USERNAME", "")}


def find_tv_window():
    import win32gui, win32process
    k = ctypes.windll.kernel32
    found = []

    def exe(pid):
        h = k.OpenProcess(0x1000, False, pid)
        if not h:
            return ""
        buf = ctypes.create_unicode_buffer(1024)
        n = ctypes.c_uint(1024)
        ok = k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
        k.CloseHandle(h)
        return os.path.basename(buf.value).lower() if ok else ""

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
            pid = win32process.GetWindowThreadProcessId(h)[1]
            if exe(pid) == "tradingview.exe":
                found.append(h)
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def capture_window(hwnd, out_png):
    """Faqat TradingView oynasi (PrintWindow, fokus o'zgarmaydi). Qaytaradi (ok, sabab)."""
    import win32gui, win32ui
    from PIL import Image
    ctypes.windll.user32.SetProcessDPIAware()
    if ctypes.windll.user32.IsIconic(hwnd):
        return False, "oyna minimallashtirilgan (skrinshot olib bo'lmaydi)"
    l, t, r, b = win32gui.GetWindowRect(hwnd)
    w, h = r - l, b - t
    if w < 300 or h < 300:
        return False, "oyna o'lchami juda kichik"
    hdc = win32gui.GetWindowDC(hwnd)
    mfc = win32ui.CreateDCFromHandle(hdc)
    dc = mfc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc, w, h)
    dc.SelectObject(bmp)
    ok = ctypes.windll.user32.PrintWindow(hwnd, dc.GetSafeHdc(), 2)
    info, bits = bmp.GetInfo(), bmp.GetBitmapBits(True)
    img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
    dc.DeleteDC(); mfc.DeleteDC(); win32gui.ReleaseDC(hwnd, hdc); win32gui.DeleteObject(bmp.GetHandle())
    if not ok:
        return False, "PrintWindow muvaffaqiyatsiz"
    ext = img.convert("L").resize((64, 64)).getextrema()
    if ext[1] - ext[0] < 8:
        return False, "skrinshot bo'm-bo'sh (GPU oyna ichini bermadi)"
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    img.save(out_png)
    return True, out_png


def ocr_items(png):
    from rapidocr_onnxruntime import RapidOCR
    from PIL import Image
    w = Image.open(png).size[0]
    res, _ = RapidOCR()(png)
    rows = []
    for box, txt, _c in (res or []):
        rows.append((min(p[1] for p in box), min(p[0] for p in box), txt, min(p[0] for p in box) / w))
    rows.sort(key=lambda r: (round(r[0] / 12), r[1]))
    return [(r[2], r[3]) for r in rows]


def verify_chart(s, device, hint=""):
    d = device_info()
    if device.upper() != d["computer"].upper():
        return {"state": "integration_missing", "reason": f"maqsad qurilma {device}, bu kompyuter {d['computer']}"}
    try:
        hwnd = find_tv_window()
    except Exception as e:
        return {"state": "integration_missing", "reason": f"win32 yo'q: {e}"}
    if not hwnd:
        return {"state": "unverified", "reason": "TradingView oynasi topilmadi (ilova yopiq yoki ko'rinmaydi)"}
    png = os.path.join(VERIFY_DIR, f"{s['id']}_{datetime.now():%H%M%S}.png")
    ok, why = capture_window(hwnd, png)
    if not ok:
        return {"state": "unverified", "reason": why}
    ev = evaluate_ocr(ocr_items(png), s, hint)
    return {"state": "confirmed" if ev["confirmed"] else "unverified", "screenshot": png, "evaluation": ev}


# ---------------- ssenariylar ----------------
LEGACY_BTC = {"id": "BTC-SHORT-20261106-01", "symbol": "BTCUSDT", "timeframe": "1h", "side": "SHORT",
              "entry": 76600, "sl": 77500, "tp": [75250, 74400], "strategy": "Manual-Research",
              "version": "0", "created": "2026-11-06T15:25:00+05:00",
              "invalidation": "1H close above 77500 voids it; no entry if price never reaches 76600"}


def prepare(s, with_price=False, pine_dir=PINE_DIR):
    code = generate_pine(s)
    v = validate_pine(code, s)
    out = {"validation": v}
    if with_price:
        out["price_check"] = check_price(s)
    if not v["ok"]:
        out["status"] = task_status(False, False, "unverified")
        return out
    out["save"] = save_pine(s, code, pine_dir)
    out["status"] = task_status(True, True, "unverified")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--scenario"); p.add_argument("--legacy-btc", action="store_true")
    p.add_argument("--check-price", action="store_true")
    c = sub.add_parser("clip"); c.add_argument("--id", required=True)
    v = sub.add_parser("verify"); v.add_argument("--id", required=True); v.add_argument("--device", required=True)
    v.add_argument("--hint", default="")
    sub.add_parser("device")
    a = ap.parse_args(argv)
    if a.cmd == "device":
        print(json.dumps(device_info())); return 0
    if a.cmd == "prepare":
        s = LEGACY_BTC if a.legacy_btc else json.load(open(a.scenario, encoding="utf-8-sig"))
        print(json.dumps(prepare(s, a.check_price), ensure_ascii=False, indent=1)); return 0
    rec = find_by_id(a.id)
    if not rec:
        print(json.dumps({"status": "FAILED", "reason": "ID topilmadi"})); return 1
    if a.cmd == "clip":
        print(json.dumps({"clipboard": to_clipboard(rec["file"]), "file": rec["file"]})); return 0
    r = verify_chart(rec["scenario"], a.device, a.hint)
    r["status"] = task_status(True, True, r["state"])
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
