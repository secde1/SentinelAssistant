"""Ishga tushirish:
    python -m agent            — xizmat rejimi (Telegram bot, NSSM shuni ishga tushiradi)
    python -m agent --check    — konfiguratsiya, PowerShell, Telegram va Claude ulanishini tekshirish
    python -m agent --once "…" — bitta topshiriqni konsolda bajarish (Telegramsiz sinov)
    python -m agent --init     — faqat AGENT_HOME papkalarini yaratish
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .app import build_core, check, run_forever, run_once
from .claude_cli import PAID_ENV, prepare_process_env
from .config import Config
from .logsetup import setup_logging
from .workspace import ensure_workspace


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="python -m agent", description="Avtonom IT-infratuzilma agenti")
    parser.add_argument("--check", action="store_true", help="sozlamalar va ulanishlarni tekshirish")
    parser.add_argument("--once", metavar="MATN", help="bitta topshiriqni konsolda bajarish")
    parser.add_argument("--opus", action="store_true", help="--once bilan: kuchli modelni ishlatish")
    parser.add_argument("--init", action="store_true", help="faqat AGENT_HOME papkalarini yaratish")
    args = parser.parse_args(argv)

    cfg = Config.from_env()
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
    try:
        run_forever(cfg, paths, redactor, inventory, journal, runner)
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("To'xtatildi (Ctrl+C / xizmat stop).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
