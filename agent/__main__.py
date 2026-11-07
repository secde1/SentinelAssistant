"""Ishga tushirish:
    python -m agent            — doimiy rejim: Telegram bot. Odatda AgentRestart vazifasi Windows'ga kirganda
                                 pythonw.exe bilan oynasiz ishga tushiradi (boshqarish: agentctl.cmd)
    python -m agent --check    — konfiguratsiya, PowerShell, Telegram va Claude ulanishini tekshirish
    python -m agent --once "…" — bitta topshiriqni konsolda bajarish (Telegramsiz sinov)
    python -m agent --init     — faqat AGENT_HOME papkalarini yaratish
"""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
import logging
import sys
from pathlib import Path

from .config import Config
from .lifecycle import STORM_LIMIT, STORM_WINDOW, Lifecycle, hide_child_consoles
from .workspace import Paths


def _attach_console_log(jurnal: Path) -> None:
    """pythonw.exe da stdout/stderr yo'q: chiqish va kutilmagan xato izi (faulthandler ham) console.log ga."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    jurnal.mkdir(parents=True, exist_ok=True)
    stream = open(jurnal / "console.log", "a", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = stream
    faulthandler.enable(stream)
    hide_child_consoles()


def _refuse_restart_storm(cfg: Config, paths: Paths, starts: int) -> int:
    """Har safar yiqilayotgan agentni cheksiz qayta ko'tarmaymiz: jurnalga yozamiz va egasiga bir marta aytamiz."""
    from .journal import Journal
    from .redact import Redactor

    mins = int(STORM_WINDOW.total_seconds() // 60)
    text = (f"Agent {mins} daqiqada {starts} marta ishga tushdi — har safar yiqilyapti. Avtomatik qayta ko'tarish "
            "to'xtatildi. Sabab: data\\jurnal\\console.log va agent.log. Tuzatgach: agentctl start")
    print(text)
    redactor = Redactor()
    redactor.add(cfg.telegram_token)
    Journal(paths.jurnal, redactor).event("agent_crash_loop", text, starts=starts)
    try:
        from .telegram_api import TelegramAPI

        async def notify() -> None:
            api = TelegramAPI(cfg.telegram_token)
            try:
                await api.call("sendMessage", {"chat_id": cfg.allowed_chat_id, "text": "⛔ " + text}, retries=1)
            finally:
                await api.aclose()

        asyncio.run(notify())
    except Exception as exc:  # noqa: BLE001 — xabar ketmasa ham agent baribir ishga tushmaydi
        print(f"Telegram'ga xabar yuborilmadi: {type(exc).__name__}")
    return 0


def main(argv: list[str] | None = None) -> int:
    cfg = Config.from_env()
    paths = Paths(cfg.agent_home)
    _attach_console_log(paths.jurnal)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m agent", description="Avtonom IT-infratuzilma agenti")
    parser.add_argument("--check", action="store_true", help="sozlamalar va ulanishlarni tekshirish")
    parser.add_argument("--once", metavar="MATN", help="bitta topshiriqni konsolda bajarish")
    parser.add_argument("--opus", action="store_true", help="--once bilan: kuchli modelni ishlatish")
    parser.add_argument("--init", action="store_true", help="faqat AGENT_HOME papkalarini yaratish")
    args = parser.parse_args(argv)

    if not (args.check or args.once or args.init):
        starts = Lifecycle(paths.ish).record_start()
        if starts > STORM_LIMIT:
            return _refuse_restart_storm(cfg, paths, starts)

    # Og'ir modullar crash-loop hisobidan KEYIN yuklanadi: koddagi import/sintaksis xatosi ham agentni cheksiz
    # qayta ishga tushirishga olib kelmasin.
    from .app import build_core, check, run_forever, run_once
    from .claude_cli import PAID_ENV, prepare_process_env
    from .logsetup import setup_logging
    from .workspace import ensure_workspace

    # SDK CLI'ga os.environ ni meros qilib beradi — pullik credential'lar jarayondan butunlay olib tashlanadi.
    removed = prepare_process_env()
    paid = [k for k in removed if k in PAID_ENV]
    if paid:
        print(f"{', '.join(paid)} CLI'ga uzatilmaydi — agent faqat Claude obunasi bilan ishlaydi (pullik API yo'q).")
    paths = ensure_workspace(cfg.agent_home)
    if args.init:
        print(f"AGENT_HOME tayyor: {paths.home}")
        return 0

    if args.check:
        return asyncio.run(check(cfg, paths))
    problems = cfg.problems(need_telegram=not args.once)
    if problems:
        print("Ishga tushirib bo'lmaydi — quyidagi qiymatlar kerak:\n" + "\n".join("  • " + p for p in problems))
        return 2

    redactor, inventory, journal, runner = build_core(cfg, paths)
    setup_logging(paths.jurnal, redactor, logging.INFO)
    if removed:
        logging.getLogger(__name__).info("Obuna rejimi: %s jarayon muhitidan olib tashlandi", ", ".join(removed))
    if args.once:
        return asyncio.run(run_once(cfg, paths, runner, redactor, args.once, args.opus))
    return run_forever(cfg, paths, redactor, inventory, journal, runner)


if __name__ == "__main__":
    raise SystemExit(main())
