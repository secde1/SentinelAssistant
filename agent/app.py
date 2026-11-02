"""Komponentlarni bog'lash: xizmat rejimi (Telegram), --check va --once."""
from __future__ import annotations

import asyncio
import importlib.util
import logging
from datetime import datetime

from . import claude_cli, proactive
from .bot import TelegramBot, TelegramChannel
from .config import Config, daily_time
from .console import ConsoleChannel
from .inventory import Inventory
from .journal import Journal
from .loop import AgentRunner, TaskRequest, TaskStatus, load_external_mcp
from .pending import PendingInputs
from .redact import Redactor
from .tasks import TaskManager
from .telegram_api import TelegramAPI, TelegramError
from .tools import ToolExecutor
from .tools.powershell import exec_process, pwsh_path, child_env
from .weekly import make_summary
from .workspace import Paths

log = logging.getLogger(__name__)


def build_core(cfg: Config, paths: Paths) -> tuple[Redactor, Inventory, Journal, AgentRunner]:
    inventory = Inventory(paths.inventory_json)
    redactor = Redactor(inventory.secret_values)
    redactor.add(cfg.telegram_token, cfg.claude_oauth_token, cfg.control_token, cfg.azure_speech_key)
    journal = Journal(paths.jurnal, redactor)
    runner = AgentRunner(cfg, paths, ToolExecutor(), inventory, redactor, journal)
    return redactor, inventory, journal, runner


async def run_service(cfg: Config, paths: Paths, redactor: Redactor, inventory: Inventory, journal: Journal,
                      runner: AgentRunner) -> None:
    api = TelegramAPI(cfg.telegram_token)
    pending = PendingInputs()
    bot = TelegramBot(cfg, api, paths, journal, redactor, inventory, pending)
    bot.tasks = TaskManager(runner, cfg, journal, notify=bot.send_text,
                            channel_factory=lambda tid: TelegramChannel(bot, tid),
                            send_outcome=bot.send_outcome, on_finish=pending.cancel_task)
    bot.weekly_fn = lambda: make_summary(paths)
    if cfg.stt_enabled:
        from .stt import Transcriber  # faster-whisper faqat shu yerda import qilinadi
        bot.stt = Transcriber(cfg.stt_model, cfg.stt_language, paths.models)
    if cfg.reels_enabled:
        from .studio.store import StudioStore
        bot.studio = StudioStore(paths.studio)
    me = await api.get_me()
    journal.event("start", f"Agent ishga tushdi (@{me.get('username')}, model {cfg.model})", bot=me.get("username"))
    log.info("Agent ishga tushdi: @%s, model %s, AGENT_HOME %s", me.get("username"), cfg.model, paths.home)
    # Login yo'q bo'lsa ham bot ishlaydi (xabar beradi); har topshiriq oldidan login qayta tekshiriladi.
    auth = await claude_cli.auth_status(cfg)
    journal.event("claude_auth", f"Claude login: {auth.label if auth.ok else auth.problem}", ok=auth.ok,
                  method=auth.method, plan=auth.plan)
    if not auth.ok:
        await bot.send_text(f"❌ Claude obuna logini topilmadi: {auth.problem}\n{claude_cli.LOGIN_HELP}")
    if cfg.notify_on_start:
        auth_line = f" Claude: {auth.label}." if auth.ok else ""
        await bot.send_text(f"✅ IT-agent ishga tushdi. Model: {cfg.model}.{auth_line} /help — buyruqlar.")
    background = proactive.start(cfg, paths, inventory, journal, redactor, bot.tasks, bot.send_text)
    control = None
    if cfg.control_enabled and cfg.control_port > 0:
        from .control import ControlServer
        control = ControlServer(cfg, paths, journal, redactor, bot.tasks, pending, runner)
        try:
            await control.start()
            journal.event("control", f"Ustki panel serveri: 127.0.0.1:{cfg.control_port}", port=cfg.control_port)
            log.info("Ustki panel serveri: 127.0.0.1:%s (oynacha.cmd bilan oching)", cfg.control_port)
        except OSError as exc:
            log.warning("Ustki panel serveri ishga tushmadi (%s) — port band bo'lishi mumkin", exc)
            control = None
    try:
        await bot.run()
    finally:
        for t in background:
            t.cancel()
        if control:
            await control.stop()
        await api.aclose()


async def run_once(cfg: Config, paths: Paths, runner: AgentRunner, redactor: Redactor, text: str, strong: bool) -> int:
    req = TaskRequest(id="CLI-" + datetime.now().strftime("%m%d-%H%M%S"), text=text, strong=strong)
    outcome = await runner.run(req, ConsoleChannel(redactor), TaskStatus())
    print("\n" + outcome.text)
    if outcome.file:
        print(f"To'liq hisobot: {outcome.file}")
    return 0 if outcome.status == "ok" else 1


async def check(cfg: Config, paths: Paths) -> int:
    ok = True

    def line(good: bool, text: str) -> None:
        nonlocal ok
        ok = ok and good
        print(("  ✓ " if good else "  ✗ ") + text)

    print(f"AGENT_HOME: {paths.home}")
    for problem in cfg.problems():
        line(False, problem)
    for d in (paths.xotira, paths.skill, paths.jurnal, paths.maxfiy, paths.zaxira, paths.ish, paths.skript):
        line(d.is_dir(), f"papka {d}")
    exe = pwsh_path(cfg.pwsh_path)
    try:
        rc, out = await exec_process([exe, "-NoProfile", "-NonInteractive", "-Command",
                                      "$PSVersionTable.PSVersion.ToString()"], child_env(), 60)
    except OSError as exc:
        rc, out = 1, f"ishga tushmadi: {exc}"
    line(rc == 0, f"PowerShell: {exe} ({out.strip()[:40]})")
    if "pwsh" not in exe.lower():
        print("    ! PowerShell 7 (pwsh) topilmadi — install.ps1 uni o'rnatadi. Hozircha Windows PowerShell ishlatiladi.")
    try:
        Inventory(paths.inventory_json).public_view()
        line(True, "maxfiy/inventar.json o'qildi")
    except Exception as exc:  # noqa: BLE001
        line(False, f"inventar.json: {type(exc).__name__}: {exc}")
    if cfg.telegram_token:
        api = TelegramAPI(cfg.telegram_token)
        try:
            me = await api.get_me()
            line(True, f"Telegram bot: @{me.get('username')}")
        except TelegramError as exc:
            line(False, f"Telegram: {exc} — TELEGRAM_BOT_TOKEN ni tekshiring")
        finally:
            await api.aclose()
    cli = claude_cli.cli_path(cfg)
    version = await claude_cli.cli_version(cfg) if cli else ""
    line(bool(cli and version), f"Claude Code CLI: {cli or 'topilmadi'} {version}".rstrip())
    auth = await claude_cli.auth_status(cfg)
    line(auth.ok, f"Claude login: {auth.label}" if auth.ok else f"Claude login: {auth.problem}")
    if not auth.ok:
        print("    ! " + claude_cli.LOGIN_HELP)
    await _check_proactive(cfg, paths, line)
    print("Natija: " + ("hammasi joyida ✅" if ok else "muammolar bor ❌"))
    return 0 if ok else 1


async def _check_proactive(cfg: Config, paths: Paths, line) -> None:
    found = Inventory(paths.inventory_json).get(cfg.zabbix_entry)
    if cfg.zabbix_poll_sec <= 0:
        print("  i Zabbix kuzatuvi: o'chiq (ZABBIX_POLL_SEC=0)")
    elif not found:
        print(f"  i Zabbix kuzatuvi: kutmoqda — inventarda '{cfg.zabbix_entry}' yozuvi yo'q (url + token yoki login/parol)")
    elif proactive.zabbix_url(found[1]) is None:
        print(f"  i Zabbix kuzatuvi: kutmoqda — '{cfg.zabbix_entry}' yozuvida to'g'ri url/host yo'q (hozirgi: "
              f"{found[1].get('url') or found[1].get('host') or '—'})")
    else:
        try:
            version = await asyncio.to_thread(lambda: proactive.ZabbixClient(found[1]).version())
            line(True, f"Zabbix kuzatuvi: {found[0]} (API {version}), har {cfg.zabbix_poll_sec} s, "
                       f"{proactive.SEVERITY.get(cfg.zabbix_min_severity, '?')}+")
        except proactive.ZabbixError as exc:
            line(False, f"Zabbix ({found[0]}): {exc}")
    hm = daily_time(cfg.daily_check_at)
    print(f"  i Kunlik tekshiruv: {cfg.daily_check_at} (ro'yxat: xotira/kunlik_tekshiruv.md)" if hm
          else "  i Kunlik tekshiruv: o'chiq (DAILY_CHECK_AT bo'sh)")
    if cfg.control_enabled and cfg.control_port > 0:
        print(f"  i Ustki panel (oynacha): 127.0.0.1:{cfg.control_port} — agent ishlaganda oynacha.cmd bilan oching")
    else:
        print("  i Ustki panel (oynacha): o'chiq (CONTROL_ENABLED=0)")
    servers, read_only = load_external_mcp(paths.mcp_json)
    print(f"  i Tashqi MCP: {', '.join(sorted(servers))} ({len(read_only)} ta tool tasdiqsiz)" if servers
          else "  i Tashqi MCP: yo'q (maxfiy/mcp.json)")
    if not cfg.stt_enabled:
        print("  i Ovozli xabar (nutq->matn): o'chiq (STT_ENABLED=0)")
    elif importlib.util.find_spec("faster_whisper") is None:
        line(False, "faster-whisper o'rnatilmagan — pip install -r requirements.txt (yoki STT_ENABLED=0)")
    else:
        model_dir = paths.models / cfg.stt_model
        line(model_dir.is_dir(), f"Ovozli xabar (nutq->matn): model '{cfg.stt_model}', til: {cfg.stt_language or 'uz'}"
                                 + ("" if model_dir.is_dir() else f" — papka TOPILMADI: {model_dir}"))
    _check_reels(cfg, line)


def _check_reels(cfg: Config, line) -> None:
    if not cfg.reels_enabled:
        print("  i Instagram Reels studiyasi: o'chiq (REELS_ENABLED=0)")
        return
    from .studio import render, tts

    try:
        import imageio_ffmpeg
        font = render.find_font(cfg.reels_font)
        line(True, f"Reels studiyasi: ffmpeg {imageio_ffmpeg.get_ffmpeg_version()}, shrift {font.name}")
    except Exception as exc:  # noqa: BLE001
        line(False, f"Reels studiyasi: {type(exc).__name__}: {exc}")
    engine = tts.pick_engine(cfg.reels_tts, cfg.azure_speech_key)
    if engine == "azure":
        print(f"  i Reels ovozi: Azure Speech ({cfg.azure_speech_region}), {cfg.reels_voice}")
    else:
        print(f"  i Reels ovozi: edge-tts (sinov), {cfg.reels_voice} — ochiq e'lon uchun Azure kaliti tavsiya etiladi")
    print(f"  i Kunlik Reels: {cfg.reels_per_day} ta, {cfg.reels_prepare_at}" if daily_time(cfg.reels_prepare_at)
          else "  i Kunlik Reels: avtomatik emas (REELS_PREPARE_AT bo'sh) — /reels_tayyorla bilan qo'lda")
    print("  i Instagram joylash: hali ulanmagan (2-bosqich: professional akkaunt + Meta API kerak)")


def run_forever(cfg: Config, paths: Paths, redactor: Redactor, inventory: Inventory, journal: Journal,
                runner: AgentRunner) -> None:
    asyncio.run(run_service(cfg, paths, redactor, inventory, journal, runner))
