"""TradingView tool'lari (V17). Grafikka kor-korona klik/tugma YUBORILMAYDI: Pine tayyorlanadi, egasi qo'yadi, kod
oynani skrinshot + OCR bilan tekshiradi. Natija ctx.chart ga yoziladi va yakuniy holatni kod belgilaydi
(tasdiqlanmagan grafik — hech qachon SUCCESS emas)."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from .. import gate
from ..trading import tradingview as tv
from .base import ToolContext, ToolResult
from .trading import _service


def classify_read(ctx: ToolContext, args: dict) -> gate.Decision:
    return gate.Decision(host="localhost")


def classify_internal(ctx: ToolContext, args: dict) -> gate.Decision:
    return gate.Decision(host="localhost").escalate(gate.INTERNAL)


def _known_remote(ctx: ToolContext) -> set[str]:
    out = set()
    for name in ctx.inventory.names():
        found = ctx.inventory.get(name)
        if found and found[1].get("type") == "windows":
            out.add(name.lower())
            host = str(found[1].get("host") or "")
            if host:
                out.add(host.split(".")[0].lower())
    return out


def _store(ctx: ToolContext) -> tv.PineStore:
    return tv.PineStore(_service(ctx).memory.root / "pine")


def _set_chart(ctx: ToolContext, state: str, scenario_id: str | None, detail: str = "") -> None:
    ctx.chart = {"state": state, "scenario": scenario_id, "detail": detail[:300]}


_LABEL = {"desktop": "TradingView Desktop", "browser": "brauzer (faol yorliq)"}


def _env_text(env: dict) -> str:
    lines = [f"Qurilma: {env['device']} ({env['kind']}); holat: {env['state']} — {env.get('reason', '')}"]
    if env["kind"] == "local":
        wins = "; ".join(f"{_LABEL[w['kind']]} «{w['title'][:60]}»" for w in env.get("windows", [])) or "yo'q"
        lines.append(f"  Desktop o'rnatilgan: {env.get('install_info')}; sessiya: {env.get('session_info')}; "
                     f"oynalar: {wins}")
    return "\n".join(lines)


async def environment_tool(ctx: ToolContext, args: dict) -> ToolResult:
    env = await asyncio.to_thread(tv.environment, args.get("device", ""), _known_remote(ctx),
                                  args.get("window") or "auto", args.get("symbol") and tv.tv_ticker(args["symbol"]) or "")
    return ToolResult(env["state"] != "ambiguous", _env_text(env) + "\n(Oyna sarlavhasi grafik holatini isbotlamaydi.)")


def _launch_desktop() -> str:
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "(Get-AppxPackage -Name TradingView.Desktop | Select-Object -First 1).PackageFamilyName"],
                           capture_output=True, text=True, timeout=60, creationflags=0x08000000)
        pfn = (r.stdout or "").strip()
        if not pfn:
            return "TradingView Desktop topilmadi"
        os.startfile(f"shell:AppsFolder\\{pfn}!TradingView.Desktop")  # noqa: S606 — o'rnatilgan ilovani ochish
        return "TradingView Desktop ishga tushirildi (simvol/taymfreymni egasi tanlaydi)"
    except OSError as exc:
        return f"ishga tushmadi: {exc}"


async def prepare(ctx: ToolContext, args: dict) -> ToolResult:
    svc = _service(ctx)
    try:
        if args.get("analysis_id"):
            from ..trading.analysis import load, verify_integrity

            rec = load(svc.db, args["analysis_id"])
            if rec is None:
                raise tv.ScenarioError(f"tahlil topilmadi: {args['analysis_id']}")
            if not verify_integrity(svc.db, args["analysis_id"]):
                raise tv.ScenarioError("asl tahlil yaxlitligi buzilgan (sha256 mos emas) — annotatsiya tayyorlanmaydi")
            sc = tv.scenario_from_analysis(rec)
        else:
            sc = tv.scenario_manual(args)
    except (tv.ScenarioError, ValueError, KeyError, TypeError) as exc:
        _set_chart(ctx, "invalid", args.get("analysis_id") or args.get("id"), str(exc))
        return ToolResult(False, f"Holat: FAILED — ssenariy yaroqsiz: {exc}")
    env = await asyncio.to_thread(tv.environment, args.get("device", ""), _known_remote(ctx))
    if env["state"] == "ambiguous":
        _set_chart(ctx, "needs_setup", sc.id, env["reason"])
        return ToolResult(False, f"Holat: NEEDS_SETUP — {env['reason']} (ask_owner bilan aniqlashtir)")
    code = tv.generate(sc)
    val = tv.validate_pine(code, sc)
    if not val.ok:
        _set_chart(ctx, "invalid", sc.id, "; ".join(val.errors))
        return ToolResult(False, "Holat: FAILED — Pine tekshiruvdan o'tmadi:\n" + "\n".join(f"  ✗ {e}" for e in val.errors))
    saved = _store(ctx).save(sc, code, val)
    svc.db.execute("INSERT OR IGNORE INTO chart_annotations(scenario_id, fingerprint, file, created_at, validation, "
                   "clipboard, source) VALUES(?,?,?,?,?,?,?)",
                   (sc.id, sc.fingerprint(), saved["file"], datetime.now().astimezone().isoformat(timespec="seconds"),
                    json.dumps({"errors": val.errors, "annotations": val.annotations}, ensure_ascii=False), 0, sc.source))
    clip = "o'tkazilmadi"
    if env["kind"] == "local" and env.get("interactive") and args.get("copy_to_clipboard", True):
        text = Path(saved["file"]).read_text(encoding="ascii")
        ok = await asyncio.to_thread(tv.copy_to_clipboard, text)
        clip = "clipboardga qo'yildi (qayta o'qib tekshirildi)" if ok else "clipboardga qo'yib bo'lmadi"
    opened = ""
    mode = args.get("open_chart", "none")
    if mode != "none" and env["kind"] == "local" and env.get("interactive"):
        if mode == "web":
            os.startfile(sc.chart_url())  # noqa: S606 — standart brauzerda hujjatlashtirilgan URL parametrlari bilan
            opened = f"Brauzerda ochildi: {sc.chart_url()}"
        elif mode == "desktop" and not any(w["kind"] == "desktop" for w in env.get("windows", [])):
            opened = await asyncio.to_thread(_launch_desktop)
    status = tv.chart_status(True, env["state"], None)
    _set_chart(ctx, "needs_setup" if status == "NEEDS_SETUP" else "unverified", sc.id, env.get("reason", ""))
    dup = {"duplicate": "bu ssenariy uchun Pine allaqachon bor — qayta yaratilmadi (dublikat yo'q)",
           "exists": "bu ssenariy uchun boshqa tarkibli fayl bor — tegilmadi", "saved": "yangi fayl saqlandi"}[saved["status"]]
    lines = [f"Holat: {status} — Pine tayyor, grafikda TASDIQLANMAGAN (kompilyatsiya ham faqat TradingView'da).",
             f"Ssenariy: {sc.id} | {sc.exchange + ':' if sc.exchange else ''}{sc.ticker} {sc.timeframe} | {sc.direction} | "
             f"{sc.strategy} v{sc.version} | manba: {sc.source}",
             f"Annotatsiyalar ({len(val.annotations)}): " + "; ".join(val.annotations),
             f"Statik tekshiruv: PASS ({len(sc.levels())} ta hline, dublikatsiz). Fayl: {saved['file']} — {dup}",
             f"Clipboard: {clip}", _env_text(env)]
    if opened:
        lines.append(opened)
    lines += ["O'rnatish:", tv.install_steps(sc, saved["file"], "qo'yildi" in clip)]
    return ToolResult(True, "\n".join(lines))


async def verify(ctx: ToolContext, args: dict) -> ToolResult:
    sid = args["scenario_id"]
    entry = _store(ctx).find(sid)
    if entry is None:
        return ToolResult(False, f"{sid} uchun tayyorlangan Pine yo'q — avval tradingview_prepare.")
    sc = tv.Scenario(**entry["scenario"])
    target = args.get("window") or "auto"
    env = await asyncio.to_thread(tv.environment, args.get("device", ""), _known_remote(ctx), target, sc.ticker)
    svc = _service(ctx)

    def record(state: str, status: str, shot: str | None, evidence: dict) -> None:
        svc.db.execute("INSERT INTO chart_verifications(scenario_id, ts, device, state, screenshot, evidence, status) "
                       "VALUES(?,?,?,?,?,?,?)", (sid, datetime.now().astimezone().isoformat(timespec="seconds"),
                                                 env["device"], state, shot, json.dumps(evidence, ensure_ascii=False),
                                                 status))
    if env["state"] != "ready":
        status = tv.chart_status(True, env["state"], None)
        _set_chart(ctx, "needs_setup" if status == "NEEDS_SETUP" else "unverified", sid, env.get("reason", ""))
        record(env["state"], status, None, {"reason": env.get("reason")})
        return ToolResult(True, f"Holat: {status} — tekshirib bo'lmadi: {env.get('reason')}\n{_env_text(env)}")
    wins = await asyncio.to_thread(tv.find_windows, target, sc.ticker)
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    checks: list[tuple[dict, dict | None, str | None, str]] = []  # (oyna, dalil, skrinshot, izoh)
    for i, w in enumerate(wins, 1):
        shot = svc.memory.root / "chart_checks" / f"{sid}_{stamp}_{w['kind']}{i}.png"
        ok, why = await asyncio.to_thread(tv.capture, w["hwnd"], shot)
        if not ok:
            checks.append((w, None, None, f"skrinshot olinmadi: {why}"))
            continue
        try:
            items = await asyncio.to_thread(tv.ocr_items, shot)
        except Exception as exc:  # noqa: BLE001 — OCR modeli yo'q bo'lishi mumkin
            checks.append((w, None, str(shot), f"OCR ishlamadi ({type(exc).__name__})"))
            continue
        if w["kind"] == "browser" and not tv.is_tradingview_page(items, sc):
            shot.unlink(missing_ok=True)  # begona sahifa rasmi saqlanmaydi
            checks.append((w, None, None, "faol yorliq TradingView sahifasi emas — rasm o'chirildi"))
            continue
        checks.append((w, tv.evaluate(items, sc), str(shot), ""))
    if not checks:
        checks.append(({"kind": target if target != "auto" else "desktop", "title": ""}, None, None,
                       tv.NO_WINDOW[target]))
    evaluated = [c for c in checks if c[1] is not None]
    best = next((c for c in evaluated if c[1]["confirmed"]), None) or \
        min(evaluated, key=lambda c: len(c[1]["missing"]) + c[1]["duplicate_indicator"], default=None)
    ev = best[1] if best else None
    status = tv.chart_status(True, "ready", ev)
    if status == "SUCCESS":
        detail = ""
    elif ev:
        detail = "yo'q: " + ", ".join(ev["missing"])
    else:
        detail = "; ".join(c[3] for c in checks)
    _set_chart(ctx, "confirmed" if status == "SUCCESS" else "unverified", sid, detail)
    for w, e, shot, note in checks:
        st = tv.chart_status(True, "ready", e)
        record("confirmed" if st == "SUCCESS" else "unverified", st, shot,
               {**(e or {}), "window": w["kind"], "title": w["title"][:120], "note": note})
    head = "annotatsiyalar to'g'ri grafikda ko'rindi (OCR dalili)" if status == "SUCCESS" else "grafikda tasdiqlanmadi"
    lines = [f"Holat: {status} — {head}"]
    for w, e, shot, note in checks:
        if e is None:
            lines.append(f"- {_LABEL[w['kind']]}: {note}")
            continue
        lines += [f"- {_LABEL[w['kind']]}: {'TASDIQLANDI' if e['confirmed'] else 'tasdiqlanmadi'}; skrinshot: {shot}",
                  f"  Instrument/taymfreym (indikator tekshiruvi '{tv.MATCH_TEXT}'): {'ha' if e['chart_match'] else 'yoq'}"
                  + (" — WRONG CHART ko'rindi" if e["wrong_chart"] else ""),
                  f"  Simulyatsiya belgisi: {'ha' if e['disclaimer'] else 'yoq'}; ID: {'ha' if e['analysis_id'] else 'yoq'}; "
                  f"indikator nusxalari: {e['indicator_copies']}",
                  "  Darajalar: " + ", ".join(f"{k}={'ha' if v else 'yoq'}" for k, v in e["levels"].items())]
        if e["duplicate_indicator"]:
            lines.append("  ⚠️ Indikator grafikka bir necha marta qo'shilgan — ortiqchasini olib tashlash kerak (dublikat).")
        if e["missing"]:
            lines.append("  Yo'q elementlar: " + ", ".join(e["missing"]))
        if not e["confirmed"] and (e["wrong_chart"] or not e["symbol_text"]):
            lines.append(f"  Bu oynada {sc.ticker} {sc.timeframe} ko'rinmadi — kerakli grafik: {sc.chart_url()}")
    if status != "SUCCESS":
        lines.append("Eslatma: brauzerda faqat faol yorliq rasmga tushadi; oyna minimallashtirilmagan bo'lsin.")
    return ToolResult(True, "\n".join(lines))


_DEVICE = {"type": "string", "description": "Qurilma: 'local' (shu noutbuk) yoki inventar nomi (masalan nb-xs-tex02). "
                                            "Noaniq bo'lsa egasidan so'ra."}
_WINDOW = {"type": "string", "enum": ["auto", "desktop", "browser"],
           "description": "Qaysi oyna: auto (Desktop + brauzer), desktop (TradingView Desktop) yoki browser (Chrome/Edge — "
                          "faqat faol yorliq). Default auto."}
ENV_SCHEMA = {"type": "object", "properties": {"device": _DEVICE, "window": _WINDOW,
                                               "symbol": {"type": "string", "description": "kutilgan simvol (ixtiyoriy)"}},
              "required": ["device"]}
PREPARE_SCHEMA = {"type": "object", "properties": {
    "analysis_id": {"type": "string", "description": "Tadqiqot bazasidagi tahlil (TA-...). Darajalar o'zgartirilmaydi."},
    "device": _DEVICE,
    "id": {"type": "string", "description": "Qo'lda ssenariy ID (analysis_id bo'lmasa)"},
    "symbol": {"type": "string"}, "exchange": {"type": "string"}, "timeframe": {"type": "string"},
    "direction": {"type": "string", "enum": ["LONG", "SHORT"]}, "entry_type": {"type": "string"},
    "entry": {"type": "number"}, "sl": {"type": "number"}, "tp": {"type": "array", "items": {"type": "number"}},
    "strategy": {"type": "string"}, "version": {"type": "string"},
    "created": {"type": "string", "description": "ISO vaqt, vaqt mintaqasi bilan"},
    "invalidation": {"type": "string"},
    "copy_to_clipboard": {"type": "boolean"},
    "open_chart": {"type": "string", "enum": ["none", "web", "desktop"],
                   "description": "web — brauzerda to'g'ri simvol/taymfreym URL; desktop — ilovani ochish (klik yo'q)"}},
    "required": ["device"]}
VERIFY_SCHEMA = {"type": "object", "properties": {"scenario_id": {"type": "string"}, "device": _DEVICE,
                                                  "window": _WINDOW},
                 "required": ["scenario_id", "device"]}

ENV_DESCRIPTION = ("TradingView bilan ishlashdan OLDIN: qurilmani aniqlash (shu noutbuk yoki NB-XS-TEX02), Desktop "
                   "o'rnatilganmi, interaktiv sessiya bormi, qaysi oynalar ochiq (Desktop va brauzerdagi faol TradingView "
                   "yorlig'i). Faqat o'qish.")
PREPARE_DESCRIPTION = ("TradingView uchun Pine Script (v5) tayyorlaydi: kirish, virtual SL/TP, strategiya va versiya, "
                       "Analysis ID, vaqt, bekor qilish sharti, 'SIMULATED RESEARCH' belgisi va instrument/taymfreym "
                       "mosligi tekshiruvi. Statik tekshiradi, trading_memory/pine ga dublikatsiz saqlaydi (eski fayl "
                       "ustiga yozilmaydi), clipboardga qo'yadi, o'rnatish yo'riqnomasini beradi. Grafikka O'ZI qo'shmaydi: "
                       "holat PARTIAL bo'ladi, toki tradingview_verify tasdiqlaguncha.")
VERIFY_DESCRIPTION = ("TradingView oynalarini — Desktop va brauzer (Chrome/Edge, faqat faol yorliq) — har birini alohida "
                      "skrinshot qilib OCR bilan tekshiradi (boshqa ilovalar olinmaydi, begona sahifa rasmi o'chiriladi): "
                      "to'g'ri instrument va "
                      "taymfreym (indikatorning o'zi tasdiqlagan), simulyatsiya belgisi, ID, barcha darajalar, indikator "
                      "dublikati. SUCCESS faqat hammasi ko'rinsa. Oyna sarlavhasiga ishonilmaydi.")
