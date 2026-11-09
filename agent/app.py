"""Komponentlarni bog'lash: xizmat rejimi (Telegram), --check va --once."""
from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import sys
import traceback
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from . import claude_cli, proactive
from .bot import TelegramBot, TelegramChannel
from .config import Config, daily_time
from .console import ConsoleChannel
from .inventory import Inventory
from .journal import Journal
from .lifecycle import HEARTBEAT_SEC, Lifecycle
from .loop import AgentRunner, TaskRequest, TaskStatus, load_external_mcp
from .pending import PendingInputs
from .redact import Redactor
from .tasks import TaskManager
from .telegram_api import TelegramAPI, TelegramError, TelegramNetworkError
from .tools import ToolExecutor
from .tools.powershell import exec_process, pwsh_path, child_env
from .weekly import make_summary
from .workspace import Paths

log = logging.getLogger(__name__)


def build_core(cfg: Config, paths: Paths) -> tuple[Redactor, Inventory, Journal, AgentRunner]:
    inventory = Inventory(paths.inventory_json)
    redactor = Redactor(inventory.secret_values)
    redactor.add(cfg.telegram_token, cfg.claude_oauth_token, cfg.control_token, cfg.azure_speech_key,
                 cfg.twelvedata_api_key)
    journal = Journal(paths.jurnal, redactor)
    runner = AgentRunner(cfg, paths, ToolExecutor(), inventory, redactor, journal)
    return redactor, inventory, journal, runner


class StartupError(Exception):
    """Sozlama xatosi (masalan Telegram tokeni yaroqsiz): qayta ishga tushirish yordam bermaydi."""


async def wait_for_telegram(api: TelegramAPI, first_delay: float = 10, max_delay: float = 300) -> dict:
    """Windows'ga kirganda internet hali bo'lmasligi mumkin (Wi-Fi ulanmagan). Butun agentni qayta ishga
    tushirmasdan, o'sib boruvchi pauza bilan (10 s ... 5 daqiqa) kutamiz. Token xato bo'lsa — darhol to'xtaymiz."""
    delay = first_delay
    while True:
        try:
            return await api.get_me()
        except TelegramNetworkError as exc:
            log.warning("Telegram'ga ulanib bo'lmadi (%s) — %d s dan keyin qayta urinaman", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, max_delay)
        except TelegramError as exc:
            raise StartupError(f"Telegram bot ishga tushmadi: {exc} — TELEGRAM_BOT_TOKEN ni tekshiring") from None


async def _heartbeat(life: Lifecycle) -> None:
    """agent.state dagi "tirik" belgisi: jarayon kutilmaganda o'lsa, keyingi ishga tushishda qachon o'lgani ko'rinadi."""
    while True:
        await asyncio.sleep(HEARTBEAT_SEC)
        with suppress(OSError):
            life.alive()


def _start_message(cfg: Config, auth: claude_cli.AuthInfo, life: Lifecycle | None) -> str | None:
    prev = life.previous if life else None
    warn = ""
    if prev and prev["kind"] == "unexpected":
        warn = (f"\n⚠️ Oldingi ish {prev['how']}. Oxirgi tirik belgi: {str(prev.get('last_alive'))[:16]}. "
                "Tafsilot: data\\jurnal\\console.log")
    if not (cfg.notify_on_start or warn):
        return None
    auth_line = f" Claude: {auth.label}." if auth.ok else ""
    return f"✅ IT-agent ishga tushdi. Model: {cfg.model}.{auth_line} /help — buyruqlar.{warn}"


async def run_service(cfg: Config, paths: Paths, redactor: Redactor, inventory: Inventory, journal: Journal,
                      runner: AgentRunner, life: Lifecycle | None = None) -> None:
    heartbeat = asyncio.create_task(_heartbeat(life)) if life else None
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
    me = await wait_for_telegram(api)
    journal.event("start", f"Agent ishga tushdi (@{me.get('username')}, model {cfg.model})", bot=me.get("username"))
    log.info("Agent ishga tushdi: @%s, model %s, AGENT_HOME %s", me.get("username"), cfg.model, paths.home)
    # Login yo'q bo'lsa ham bot ishlaydi (xabar beradi); har topshiriq oldidan login qayta tekshiriladi.
    auth = await claude_cli.auth_status(cfg)
    journal.event("claude_auth", f"Claude login: {auth.label if auth.ok else auth.problem}", ok=auth.ok,
                  method=auth.method, plan=auth.plan)
    if not auth.ok:
        await bot.send_text(f"❌ Claude obuna logini topilmadi: {auth.problem}\n{claude_cli.LOGIN_HELP}")
    message = _start_message(cfg, auth, life)
    if message:
        await bot.send_text(message)
    background = proactive.start(cfg, paths, inventory, journal, redactor, bot.tasks, bot.send_text)
    if heartbeat:
        background.append(heartbeat)
    if cfg.trading_enabled:
        trading_job = _start_trading(cfg, paths, journal, bot)
        if trading_job is not None:
            background.append(trading_job)
    night_job = _start_nightly(cfg, paths, journal, bot)
    if night_job is not None:
        background.append(night_job)
    background.append(_start_outbox(cfg, paths, bot))
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


def _safe(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 — MT5 yopiq bo'lsa ham xabar yuborish to'xtamasin
        return default


def _start_outbox(cfg: Config, paths: Paths, bot: TelegramBot):
    """data/chiqish/ papkasiga tashlangan fayllar egasining shaxsiy chatiga yuboriladi (V27)."""
    from .outbox import Outbox, run_forever

    async def send_file(path, caption: str) -> bool:
        try:
            await bot.api.send_document(cfg.allowed_chat_id, path, bot.redactor.redact(caption))
            return True
        except Exception as exc:  # noqa: BLE001
            log.error("Chiqish fayli yuborilmadi: %s", exc)
            return False

    return asyncio.create_task(run_forever(Outbox(Path(paths.home) / "chiqish", send_file, bot.send_text)), name="chiqish-papkasi")


def _start_nightly(cfg: Config, paths: Paths, journal: Journal, bot: TelegramBot):
    """Tungi tadqiqot (V26): har kuni 21:00-05:00 GitHub/internet/YouTube -> yangi funksiyalar rejasi (Excel + Word) shaxsiy chatga."""
    try:
        from .nightly import NightIdeas, run_forever

        async def submit(prompt: str) -> str | None:
            return await bot.tasks.submit(TaskRequest(id=bot.tasks.new_id(), text=prompt, auto=True))

        async def send_file(path, caption: str) -> bool:
            try:  # FAQAT egasining shaxsiy chatiga
                await bot.api.send_document(cfg.allowed_chat_id, path, bot.redactor.redact(caption))
                return True
            except Exception as exc:  # noqa: BLE001
                log.error("Tungi hisobot fayli yuborilmadi: %s", exc)
                return False

        night = NightIdeas(Path(paths.home) / "tadqiqot", submit, lambda tid: tid in bot.tasks.active,
                           bot.tasks.runner.unavailable_reason, bot.send_text, send_file, journal=journal)
        bot.nightly = night
        journal.event("night_ideas", "Tungi tadqiqot yoqildi", enabled=night.cfg.get("enabled", True))
        return asyncio.create_task(run_forever(night), name="tungi-tadqiqot")
    except Exception:  # noqa: BLE001 — xato bo'lsa ham bot ishlayveradi
        log.exception("Tungi tadqiqot ishga tushmadi")
        return None


def _start_trading(cfg: Config, paths: Paths, journal: Journal, bot: TelegramBot):
    """Trading tadqiqoti (V16, faqat qog'oz savdo). Xato bo'lsa ham bot ishlayveradi."""
    try:
        from .trading.publish import Publisher
        from .trading.research import RESEARCH_NOTE
        from .trading.scheduler import TradingScheduler
        from .trading.service import TradingService

        svc = TradingService(paths.home)

        async def send(chat_id: int, text: str, reply_to: int | None) -> dict:
            return await bot.api.send_message(chat_id, text, reply_to=reply_to)

        async def submit_research(prompt: str) -> str | None:
            req = TaskRequest(id=bot.tasks.new_id(), text=prompt, auto=True, notes=[RESEARCH_NOTE])
            return await bot.tasks.submit(req)

        publisher = Publisher(svc.db, svc.settings, send, bot.send_text, clock=svc.clock)
        scheduler = TradingScheduler(svc, publisher, bot.send_text, submit_research, journal,
                                     can_submit=bot.tasks.runner.unavailable_reason)
        bot.trading, bot.trading_scheduler = svc, scheduler
        from .trading.signals import SignalService

        async def send_signal(chat_id: int, text: str, markup: dict | None, reply_to: int | None) -> dict:
            return await bot.api.send_message(chat_id, text, reply_markup=markup, reply_to=reply_to)

        async def edit_signal(chat_id: int, message_id: int, text: str) -> None:
            await bot.api.edit_message_text(chat_id, message_id, text)  # reply_markup berilmaydi — tugmalar olib tashlanadi

        from .trading.mt5_history import MT5History
        from .trading.mt5_monitor import NotificationQueue, PositionMonitor, private_chat_resolver

        async def send_plain(chat_id: int, text: str) -> dict:
            return await bot.api.send_message(chat_id, text)

        if cfg.allowed_chat_id > 0 and svc.settings.data.get("private_chat_id") != cfg.allowed_chat_id:
            svc.settings.data["private_chat_id"] = cfg.allowed_chat_id  # guruh manzilidan alohida saqlanadi
            svc.settings.save()

        chat_for = private_chat_resolver(svc.settings, cfg.allowed_chat_id)

        hist = MT5History(svc.mt5)
        scheduler.monitor = PositionMonitor(
            svc, hist, NotificationQueue(svc.db, send_plain, chat_for, svc.clock),
            candles_fn=lambda sym, tf, limit, end: svc.mt5.candles(sym, tf, limit, end=end),
            currency_fn=lambda: _safe(hist.currency, "USD"), contract_fn=lambda sym: _safe(lambda: hist.contract_size(sym), None),
            journal=journal)
        bot.signals = scheduler.signals = SignalService(svc, send_signal, edit_signal, cfg.allowed_user_id, journal,
                                                        trader=svc.mt5_trader if sys.platform == "win32" else None, history=hist)
        sv = scheduler.signals
        sv.notify_private = notify_private = scheduler.notify_owner
        try:  # Claude xodimlari bo'limi (obuna, tool yo'q); ulanmasa signal tizimi bahssiz ishlayveradi
            from .staff.desk import Desk
            from .staff.llm import make_llm
            sv.desk = Desk(svc.db, make_llm(cfg, paths.home), calendar=svc.calendar,
                           zone_min_approvals=int((svc.settings.data.get("zones") or {}).get("zone_min_approvals", 3)))
        except Exception:  # noqa: BLE001
            log.exception("Xodimlar bo'limi ulanmadi")
        from .webcontrol import WebControl
        routine = None
        if sv.desk is not None:
            from .staff.routine import StaffRoutine
            routine = StaffRoutine(sv.desk, svc.db, lambda: sv.cfg, calendar=svc.calendar)
        web = WebControl(sv, notify_private, routine)
        journal.event("trading", "Trading tadqiqoti yoqildi (paper trading)", group=svc.settings.group_chat_id)

        jobs = [scheduler.run(), web.run()] + ([routine.run()] if routine is not None else [])
        try:  # ZONE-1..5: butun bozor skaneri (faqat o'qish); ulanmasa qolgan tizim ishlayveradi
            import httpx

            from .zones.scanner import ZoneScanner
            if sv.desk is not None:
                zs = ZoneScanner(svc, sv.desk, httpx.Client(timeout=20), mt5=svc.mt5 if sys.platform == "win32" else None)
                from .zones.trade import ZoneTrader
                zt = ZoneTrader(sv, zs)
                zs.after_pass = zt.on_pass  # DIR-1 vazifasi: aktiv zonadan zdelka (AUTO + DEMO + barcha himoya)
                web.zone_trader = zt
                jobs.append(zs.run())
        except Exception:  # noqa: BLE001
            log.exception("Zona skaneri ulanmadi")

        async def _run_all() -> None:
            await asyncio.gather(*jobs)
        return asyncio.create_task(_run_all(), name="trading-tadqiqot")
    except Exception:  # noqa: BLE001
        log.exception("Trading tadqiqoti ishga tushmadi")
        return None


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
                runner: AgentRunner) -> int:
    """Doimiy rejim. Chiqish kodi AgentRestart vazifasi uchun: 0 — normal, ikkinchi nusxa yoki egasi to'xtatgan;
    1 — kutilmagan xato (vazifadagi hodisa-trigger 1 daqiqadan keyin qayta ko'taradi); 2 — sozlama xatosi."""
    life = Lifecycle(paths.ish)
    pid = os.getpid()
    if not life.lock.acquire(wait=15):
        other = life.running_pid()
        journal.event("agent_duplicate", f"Agent allaqachon ishlayapti (PID {other}) — ikkinchi nusxa ochilmadi",
                      pid=pid, other_pid=other)
        log.warning("Agent allaqachon ishlayapti (PID %s) — bu nusxa (PID %s) chiqadi", other, pid)
        return 0
    stop = life.owner_stop()
    if stop and not stop.get("allow"):
        journal.event("agent_refused", "Agent egasi to'xtatgan — o'zi ishga tushmaydi (yoqish: agentctl start)",
                      pid=pid, stop=stop)
        log.warning("Egasi to'xtatgan (%s) — ishga tushmayman. Yoqish: agentctl start", stop.get("ts"))
        life.lock.release()
        return 0
    prev = life.begin()
    version = life.state["version"]
    journal.event("agent_start", f"Agent jarayoni boshlandi: PID {pid}, v{version}"
                  + (f"; oldingi ish: {prev['how']}" if prev else ""),
                  pid=pid, version=version, python=sys.executable, previous=prev)
    log.info("Agent jarayoni: PID %s, v%s%s", pid, version, f"; oldingi ish: {prev['how']}" if prev else "")
    try:
        asyncio.run(run_service(cfg, paths, redactor, inventory, journal, runner, life))
        reason = "bot to'xtadi"
    except KeyboardInterrupt:
        reason = "Ctrl+C"
    except StartupError as exc:
        log.error("%s", exc)
        journal.event("agent_config_error", f"Agent sozlama xatosi bilan to'xtadi: {exc}", pid=pid)
        life.end()
        return 2
    except Exception as exc:  # noqa: BLE001 — har qanday kutilmagan xato yozib qo'yiladi
        log.exception("Agent kutilmagan xato bilan to'xtadi")
        journal.event("agent_crash", f"Agent yiqildi: {type(exc).__name__}: {str(exc)[:200]} (ishladi {life.uptime()})",
                      pid=pid, error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-4000:],
                      uptime=life.uptime())
        life.lock.release()
        return 1
    journal.event("agent_stop", f"Agent to'xtadi ({reason}), ishladi {life.uptime()}", pid=pid, reason=reason,
                  uptime=life.uptime())
    life.end()
    return 0
