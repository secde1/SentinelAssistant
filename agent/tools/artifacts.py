"""inspect_artifact, verify_artifact, excel_total — fayl (artefakt) bilan to'g'ri ishlash tool'lari.

path berilmasa — faol ishchi fayl (FAOL ISH konteksti) olinadi: "ИТОГО қўш", "тўғрилаб бер" kabi follow-up'da model
qaysi fayl ekanini taxmin qilmaydi.
"""
from __future__ import annotations

from pathlib import Path

from .. import gate
from ..artifacts import EXCEL_EXT, tracker, validate, xlsx
from .base import ToolContext, ToolResult


def _target(ctx: ToolContext, args: dict) -> Path | None:
    if args.get("path"):
        return ctx.resolve_path(args["path"])
    res = getattr(ctx, "resolution", None)
    if res is not None and res.file is not None:
        return Path(res.file)
    store = getattr(ctx, "artifact_store", None)
    return store.active_file() if store is not None else None


def _external(ctx: ToolContext, path: Path) -> bool:
    try:
        path.resolve().relative_to(Path(ctx.paths.home).resolve())
        return False
    except ValueError:
        return True


def _missing(ctx: ToolContext, args: dict) -> ToolResult | None:
    path = _target(ctx, args)
    if path is None:
        return ToolResult(False, "Fayl ko'rsatilmagan va faol ishchi fayl yo'q — path bering.")
    if not path.is_file():
        return ToolResult(False, f"Fayl topilmadi: {path}")
    return None


# ---------------------------------------------------------------- inspect_artifact
def classify_read(ctx: ToolContext, args: dict) -> gate.Decision:
    path = _target(ctx, args)
    return gate.classify_file_read(path, ctx.secret_paths) if path else gate.Decision(host="localhost")


async def inspect_artifact(ctx: ToolContext, args: dict) -> ToolResult:
    err = _missing(ctx, args)
    if err:
        return err
    path = _target(ctx, args)
    if path.suffix.lower() in EXCEL_EXT:
        text = xlsx.inspect(path)
    else:
        from .files import DOC_SUFFIXES, _read_document, _read_text

        body = _read_document(path) if path.suffix.lower() in DOC_SUFFIXES else _read_text(path)
        lines = body.splitlines()
        text = f"Fayl: {path} ({path.stat().st_size} bayt), {len(lines)} qator\n" + "\n".join(lines[:120])
    store = getattr(ctx, "artifact_store", None)
    art = store.artifact(path) if store is not None else None
    if art:
        vers = art.get("versions", [])
        verified = [v for v in vers if v.get("verified")]
        text += (f"\n\nVersiyalar: {len(vers)} ta (tasdiqlangan: {len(verified)}); oxirgisi {vers[-1]['ts'] if vers else '-'}"
                 f"; nusxalar: {Path(vers[-1]['snapshot']).parent if vers else '-'}")
    return ToolResult(True, text)


# ---------------------------------------------------------------- verify_artifact
async def verify_artifact(ctx: ToolContext, args: dict) -> ToolResult:
    err = _missing(ctx, args)
    if err:
        return err
    path = _target(ctx, args)
    notes = []
    writable = gate.classify_file_write(path, ctx.paths.home, ctx.secret_paths, ctx.code_root).level != gate.BLOCK
    if path.suffix.lower() in EXCEL_EXT and args.get("fix_display", True) and writable and xlsx.missing_cache(path):
        tracker.pre_scan(ctx)
        if _external(ctx, path):
            from .files import backup_local_file

            backup_local_file(ctx, path)
        rep = xlsx.write_cached_values(path)
        tracker.quiet_update(ctx, path)
        notes.append(f"Natijalar faylga yozildi (kesh qiymat, {rep.written} katak) — formulalar saqlandi, endi har qanday "
                     "ko'rgichda ko'rinadi.")
    report = validate.validate(path, expect=args.get("expect"), require_sheets=args.get("require_sheets"),
                               require_labels=args.get("require_labels"), previous=tracker.previous_version(ctx, path),
                               allow_formula_removal=bool(args.get("allow_formula_removal")))
    tracker.record_check(ctx, path, report)
    if args.get("expect") or args.get("require_labels"):
        ctx.validation_requirements = {k: args[k] for k in ("expect", "require_labels", "require_sheets") if args.get(k)}
    hint = ""
    if not report.ok:
        hint = ("\nTUZAT va qayta tekshir. Formulani songa almashtirma (Jamshid aniq so'ramagan bo'lsa); jami bo'sh "
                "ko'rinsa — bu kesh muammosi, verify_artifact uni o'zi tuzatadi.")
    elif not report.verified:
        hint = "\nXato yo'q, lekin hammasi isbotlanmadi — hisobotda buni ochiq yoz (holat PARTIAL)."
    return ToolResult(report.ok, "\n".join(notes + [report.summary()]) + hint)


# ---------------------------------------------------------------- excel_total
def classify_total(ctx: ToolContext, args: dict) -> gate.Decision:
    path = _target(ctx, args)
    if path is None:
        return gate.Decision(host="localhost")
    return gate.classify_file_write(path, ctx.paths.home, ctx.secret_paths, ctx.code_root)


async def excel_total(ctx: ToolContext, args: dict) -> ToolResult:
    err = _missing(ctx, args)
    if err:
        return err
    path = _target(ctx, args)
    if path.suffix.lower() not in EXCEL_EXT:
        return ToolResult(False, f"excel_total faqat .xlsx/.xlsm uchun: {path.name}")
    store = getattr(ctx, "artifact_store", None)
    previous = None
    if store is not None:  # o'zgarishdan oldingi versiya nusxasi — tiklash va farqni tekshirish uchun
        previous = Path(store.record_version(path, ctx.task_id)["snapshot"])
    if _external(ctx, path):
        from .files import backup_local_file

        backup_local_file(ctx, path)
    res = xlsx.add_total_row(path, sheet=args.get("sheet"), amount_columns=args.get("amount_columns"),
                             label=args.get("label") or "ИТОГО", first_row=args.get("first_row"),
                             last_row=args.get("last_row"), currency=args.get("currency") or "keep",
                             highlight=args.get("highlight", True))
    if not res.ok:
        return ToolResult(False, res.message)
    cache = xlsx.write_cached_values(path)
    if tr := getattr(ctx, "tracker", None):
        tr.scan()
    report = validate.validate(path, previous=previous)
    tracker.record_check(ctx, path, report)
    totals = ", ".join(f"{c} = {xlsx.fmt_num(cache.values.get(f'{res.sheet}!{c}'))}" for c in res.cells)
    return ToolResult(report.ok, f"{res.message}\nJami qiymat(lar): {totals}\n{report.summary()}")


VERIFY_DESCRIPTION = (
    "Yaratilgan/o'zgartirilgan faylni (Excel, Word, PDF) TEKSHIRADI: ochiladimi, formulalar xatosiz va MUSTAQIL "
    "hisoblanadimi, jami (ИТОГО) qatorlari qiymat bilan ko'rinadimi, kutilgan qiymatlar (expect) mosmi, oldingi "
    "versiyaga nisbatan formula/varaq/grafik yo'qolmadimi. Excel'da natijani faylga kesh qiymat qilib yozadi (formula "
    "saqlanadi) — Telegram/telefonda bo'sh ko'rinish shu bilan tuzaladi. Hujjat yaratgan/o'zgartirgan har topshiriqda "
    "MAJBURIY: tasdiqlanmagan fayl bilan holat SUCCESS bo'lmaydi. path bo'sh — faol ishchi fayl.")
TOTAL_DESCRIPTION = (
    "Excel'ga ko'rinadigan ИТОГО qatorini qo'shadi: summa ustunini topadi, SUM formulasi yozadi (raqam emas), valyuta "
    "formati, sariq fon va qalin shrift; natijani kesh qiymat qilib yozadi va tekshiradi. Shu ustun uchun jami qatori "
    "allaqachon bo'lsa — takrorlamaydi, faqat ko'rinadigan qiladi. Qolgan ma'lumot, formula va formatlar saqlanadi, "
    "o'zgarishdan oldingi versiya nusxasi qoladi. path bo'sh — faol ishchi fayl.")
INSPECT_DESCRIPTION = (
    "Faylni o'zgartirishdan OLDIN ko'rib chiqadi: Excel'da varaqlar, kataklar, formulalar va ularning hisoblangan "
    "natijasi, jami qatorlari, kesh holati, grafik/pivot borligi; Word/PDF'da matn. path bo'sh — faol ishchi fayl.")

_PATH = {"type": "string", "description": "Fayl yo'li. Bo'sh — faol ishchi fayl (FAOL ISH kontekstidagi)."}
INSPECT_SCHEMA = {"type": "object", "properties": {"path": _PATH}}
VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "path": _PATH,
        "expect": {"type": "array", "items": {"type": "object"}, "description": "Kutilgan qiymatlar: [{\"label\": \"Итого в сумах\", \"value\": 75237800, "
                                                   "\"tolerance\": 1, \"sheet\": \"Смета\"}] — yorliq qatoridagi raqam "
                                                   "tekshiriladi. Qiymatni O'ZING mustaqil hisoblab ber."},
        "require_sheets": {"type": "array", "items": {"type": "string"}, "description": "Bo'lishi shart bo'lgan varaqlar."},
        "require_labels": {"type": "array", "items": {"type": "string"}, "description": "Faylda bo'lishi shart bo'lgan yozuvlar (masalan 'ИТОГО', 'НДС')."},
        "allow_formula_removal": {"type": "boolean", "description": "Faqat Jamshid formulani qiymatga almashtirishni aniq "
                                                                    "so'ragan bo'lsa true."},
        "fix_display": {"type": "boolean", "description": "Excel natijalarini kesh qiymat qilib yozish (standart true)."},
    },
}
TOTAL_SCHEMA = {
    "type": "object",
    "properties": {
        "path": _PATH,
        "sheet": {"type": "string", "description": "Varaq nomi (bo'sh — faol varaq)."},
        "amount_columns": {"type": "array", "items": {"type": "string"}, "description": "Summa ustuni(lari): harf ('E') yoki sarlavha matni ('Сумма'). "
                                                          "Bo'sh — avtomatik."},
        "label": {"type": "string", "description": "Yorliq (standart 'ИТОГО')."},
        "first_row": {"type": "integer", "description": "Ma'lumotning birinchi qatori (bo'sh — avtomatik)."},
        "last_row": {"type": "integer", "description": "Ma'lumotning oxirgi qatori (bo'sh — avtomatik)."},
        "currency": {"type": "string", "enum": ["UZS", "USD", "EUR", "RUB", "keep"],
                     "description": "Valyuta formati (keep — ustundagi format)."},
        "highlight": {"type": "boolean", "description": "Sariq fon va chegara (standart true)."},
    },
}


def summary(args: dict) -> str:
    return str(args.get("path") or "(faol fayl)")[:300]
