"""Topshiriq davomida qaysi fayllar yaratildi/o'zgardi — kod kuzatadi (model qaysi usulda yozganidan qat'i nazar:
write_file, python skript, PowerShell). Fayl yuborishdan oldingi tekshiruv ham shu yerda.

Holat qoidasi (verification.py): yaratilgan/o'zgargan hujjat (xlsx/docx/pdf/pptx) uchun joriy versiyasi
tekshiruvdan o'tmagan bo'lsa — SUCCESS bo'la olmaydi.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import ARTIFACT_EXT, EXCEL_EXT, is_artifact, sha256

# Majburiy tekshiruv talab qilinadigan "natija" turlari (csv — ko'pincha oraliq eksport, majburiy emas).
DELIVERABLE_EXT = ARTIFACT_EXT - {".csv"}


def _stat(p: Path) -> tuple[int, int] | None:
    try:
        st = p.stat()
        return st.st_mtime_ns, st.st_size
    except OSError:
        return None


@dataclass
class Tracker:
    roots: list[Path]  # faqat yuqori daraja
    deep_roots: list[Path] = field(default_factory=list)  # ichki papkalari bilan (topshiriq papkasi)
    baseline: dict[str, tuple[int, int]] = field(default_factory=dict)
    changed: dict[str, dict] = field(default_factory=dict)  # yo'l -> {"created": bool}

    def _files(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for root in self.roots:
            try:
                with os.scandir(root) as it:
                    for e in it:
                        if e.is_file() and is_artifact(e.name):
                            st = _stat(Path(e.path))
                            if st:
                                out[str(Path(e.path).resolve())] = st
            except OSError:
                continue
        for root in self.deep_roots:
            for dirpath, dirnames, filenames in os.walk(root):
                if dirpath.count(os.sep) - str(root).count(os.sep) >= 3:
                    dirnames[:] = []
                for name in filenames:
                    if is_artifact(name):
                        p = Path(dirpath) / name
                        st = _stat(p)
                        if st:
                            out[str(p.resolve())] = st
        return out

    def start(self) -> None:
        self.baseline = self._files()


    def scan(self) -> list[str]:
        """Yangi o'zgargan fayllar ro'yxati."""
        new = []
        for path, st in self._files().items():
            before = self.baseline.get(path)
            if before == st:
                continue
            info = self.changed.setdefault(path, {"created": before is None})
            info["stat"] = st
            new.append(path)
            self.baseline[path] = st
        return new

    def deliverables(self) -> list[str]:
        return [p for p in self.changed if Path(p).suffix.lower() in DELIVERABLE_EXT and Path(p).is_file()]


@dataclass
class ArtifactFacts:
    changed: list[str] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    undelivered: list[str] = field(default_factory=list)
    followup_unapplied: bool = False
    followup_file: str | None = None

    @staticmethod
    def names(paths: list[str]) -> str:
        return ", ".join(Path(p).name for p in paths[:4]) + ("…" if len(paths) > 4 else "")


def facts(ctx) -> ArtifactFacts:
    """ToolContext bo'yicha artefakt faktlari (kod biladigan haqiqat)."""
    out = ArtifactFacts()
    tracker = getattr(ctx, "tracker", None)
    if tracker is None:
        return out
    tracker.scan()
    for path in tracker.deliverables():
        out.changed.append(path)
        cur = sha256(path)
        check = ctx.artifact_checks.get(path)
        if check is None or check.get("sha") != cur:
            out.unverified.append(path)
        elif not check.get("ok"):
            out.failed.append(path)
        elif not check.get("verified"):
            out.unverified.append(path)
        if ctx.delivered.get(path) != cur and path not in out.failed:
            out.undelivered.append(path)
    for path, check in ctx.artifact_checks.items():
        if path in out.failed:
            continue
        if check.get("forced"):
            out.failed.append(path)
        elif not check.get("ok") and Path(path).is_file() and check.get("sha") == sha256(path):
            out.failed.append(path)  # tekshiruvdan o'tmagan versiya shu holicha qoldi (yuborilmagan bo'lsa ham)
    res = getattr(ctx, "resolution", None)
    if res is not None and res.followup and res.modify and res.file is not None:
        target = str(Path(res.file).resolve())
        out.followup_file = target
        # Fayl o'zgarmagan VA qayta yuborilmagan bo'lsa — javob faqat chatda qolgan (06.11 dagi xato).
        if not out.changed and target not in tracker.changed and target not in ctx.delivered:
            out.followup_unapplied = True
    return out


def record_check(ctx, path: Path, report, *, forced: bool = False) -> None:
    ctx.artifact_checks[str(Path(path).resolve())] = {
        "sha": report.sha or (sha256(path) if Path(path).is_file() else ""), "ok": report.ok,
        "verified": report.verified, "summary": report.summary()[:1500], "forced": forced}


def previous_version(ctx, path: Path) -> Path | None:
    store = getattr(ctx, "artifact_store", None)
    if store is None or not Path(path).is_file():
        return None
    return store.latest_snapshot(path, exclude_sha=sha256(path))


def prepare_delivery(ctx, path: Path, *, force: bool = False) -> tuple[bool, str]:
    """Yuborishdan oldin: Excel'da natijalarni ko'rinadigan qiladi (kesh qiymat, formula saqlanadi) va tekshiradi.
    -> (yuborish mumkinmi, model uchun hisobot)."""
    from . import validate, xlsx

    path = Path(path)
    key = str(path.resolve())
    notes = []
    if path.suffix.lower() in EXCEL_EXT:
        try:
            if xlsx.missing_cache(path):
                pre_scan(ctx)
                _backup_if_external(ctx, path)
                rep = xlsx.write_cached_values(path)
                quiet_update(ctx, path)
                notes.append(f"natijalar faylga yozildi (kesh qiymat, {rep.written} katak; formulalar saqlandi)")
        except Exception as exc:  # noqa: BLE001 — tekshiruv baribir xatoni ko'rsatadi
            notes.append(f"kesh qiymat yozilmadi: {type(exc).__name__}: {exc}")
    cur = sha256(path)
    check = ctx.artifact_checks.get(key)
    if check and check.get("sha") == cur and check.get("ok") and not check.get("forced"):
        text = "Bu fayl shu topshiriqda tekshirilgan versiya (sha mos)."
        return True, "\n".join(notes + [text])
    store = getattr(ctx, "artifact_store", None)
    verified = store.latest_verified(path) if store is not None else None
    if verified and verified.get("sha") == cur:
        ctx.artifact_checks[key] = {"sha": cur, "ok": True, "verified": True, "summary": verified.get("summary", ""),
                                    "forced": False}
        text = f"Bu fayl oxirgi TASDIQLANGAN versiya ({verified['ts'][5:16]}, sha {cur[:10]}) — qayta yaratilmadi."
        return True, "\n".join(notes + [text])
    report = validate.validate(path, previous=previous_version(ctx, path))
    record_check(ctx, path, report, forced=force and not report.ok)
    text = "\n".join(notes + [report.summary()])
    if report.ok:
        return True, text
    if force:
        return True, text + "\n⚠️ force_unverified: fayl tekshiruvdan o'tmagan holda yuborildi — holat SUCCESS bo'lmaydi."
    return False, ("YUBORILMADI: fayl tekshiruvdan o'tmadi. Xatoni tuzat (formula/qiymat/yo'qolgan qism), qayta tekshir va "
                   "keyin yubor. Tuzatib bo'lmasa — hisobotda aniq sababini yoz.\n" + text)


def pre_scan(ctx) -> None:
    """Kod faylga o'zi yozishidan OLDIN: agentning shu paytgacha qilgan o'zgarishlari ro'yxatga olinsin."""
    tracker = getattr(ctx, "tracker", None)
    if tracker is not None:
        tracker.scan()


def quiet_update(ctx, path: Path) -> None:
    """Kodning o'zi qilgan mazmunsiz o'zgarish (kesh qiymat yozish) — "agent faylni o'zgartirdi" deb hisoblanmaydi.
    Avval pre_scan() chaqirilgan bo'lishi kerak."""
    tracker = getattr(ctx, "tracker", None)
    st = _stat(Path(path))
    if tracker is not None and st:
        tracker.baseline[str(Path(path).resolve())] = st


def _backup_if_external(ctx, path: Path) -> None:
    home = Path(ctx.paths.home).resolve()
    try:
        path.resolve().relative_to(home)
        return
    except ValueError:
        pass
    from ..tools.files import backup_local_file

    backup_local_file(ctx, path)
