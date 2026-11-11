"""Konfiguratsiya: .env dan o'qiladi. Haqiqiy maxfiy qiymatlar faqat .env da."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

VALID_EFFORTS = {"low", "medium", "high", "xhigh", "max"}
DEFAULT_STT_MODEL = "univoice-stt-uz-ct2"  # AGENT_HOME/modellar ichidagi CTranslate2 o'zbekcha whisper papkasi


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "ha", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Config:
    telegram_token: str = ""
    allowed_chat_id: int = 0
    allowed_user_id: int = 0
    claude_cli_path: str = ""
    claude_oauth_token: str = ""
    claude_idle_timeout: int = 900
    task_timeout: int = 7200
    model: str = "claude-sonnet-5-5"
    strong_model: str = "claude-opus-5-5"
    effort: str = "medium"
    strong_effort: str = "high"
    web_search: bool = True
    agent_home: Path = Path(r"C:\agent")
    max_iterations: int = 60
    max_consecutive_failures: int = 8
    max_concurrent_tasks: int = 3
    max_questions_per_task: int = 2
    approval_timeout: int = 900
    question_timeout: int = 1800
    progress_after: int = 60
    progress_interval: int = 180
    tool_output_limit: int = 12000
    command_timeout: int = 600
    pwsh_path: str = ""
    notify_on_start: bool = True
    stt_enabled: bool = True
    stt_model: str = DEFAULT_STT_MODEL
    stt_language: str = ""
    zabbix_entry: str = "zabbix"
    zabbix_poll_sec: int = 120
    zabbix_min_severity: int = 3
    alert_tasks_per_hour: int = 3
    daily_check_at: str = ""
    control_enabled: bool = True
    control_port: int = 8787
    control_token: str = ""
    reels_enabled: bool = False
    reels_per_day: int = 2
    reels_prepare_at: str = ""
    reels_tts: str = "auto"
    reels_voice: str = "uz-UZ-MadinaNeural"
    reels_rate: str = "+0%"
    reels_font: str = ""
    reels_brand: str = ""
    azure_speech_key: str = ""
    azure_speech_region: str = ""
    twelvedata_api_key: str = ""

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Config":
        load_dotenv(env_file or ENV_FILE, override=False)
        e = os.environ.get
        chat_id = _int(e("ALLOWED_CHAT_ID"), 0)
        return cls(
            telegram_token=(e("TELEGRAM_BOT_TOKEN") or "").strip(),
            allowed_chat_id=chat_id,
            # Shaxsiy chatda chat_id == user_id. Guruh ishlatilsa ALLOWED_USER_ID majburiy.
            allowed_user_id=_int(e("ALLOWED_USER_ID"), chat_id),
            claude_cli_path=(e("CLAUDE_CLI_PATH") or "").strip(),
            claude_oauth_token=(e("CLAUDE_CODE_OAUTH_TOKEN") or "").strip(),
            claude_idle_timeout=_int(e("CLAUDE_IDLE_TIMEOUT_SEC"), 900),
            task_timeout=_int(e("TASK_TIMEOUT_SEC"), 7200),
            model=(e("ANTHROPIC_MODEL") or "claude-sonnet-5-5").strip(),
            strong_model=(e("ANTHROPIC_STRONG_MODEL") or "claude-opus-5-5").strip(),
            effort=(e("ANTHROPIC_EFFORT") or "medium").strip().lower(),
            strong_effort=(e("ANTHROPIC_STRONG_EFFORT") or "high").strip().lower(),
            web_search=_bool(e("WEB_SEARCH"), True),
            agent_home=Path((e("AGENT_HOME") or r"C:\agent").strip()),
            max_iterations=_int(e("MAX_ITERATIONS"), 60),
            max_consecutive_failures=_int(e("MAX_CONSECUTIVE_FAILURES"), 8),
            max_concurrent_tasks=_int(e("MAX_CONCURRENT_TASKS"), 3),
            max_questions_per_task=_int(e("MAX_QUESTIONS_PER_TASK"), 2),
            approval_timeout=_int(e("APPROVAL_TIMEOUT_SEC"), 900),
            question_timeout=_int(e("QUESTION_TIMEOUT_SEC"), 1800),
            progress_after=_int(e("PROGRESS_AFTER_SEC"), 60),
            progress_interval=_int(e("PROGRESS_INTERVAL_SEC"), 180),
            tool_output_limit=_int(e("TOOL_OUTPUT_LIMIT"), 12000),
            command_timeout=_int(e("COMMAND_TIMEOUT_SEC"), 600),
            pwsh_path=(e("PWSH_PATH") or "").strip(),
            notify_on_start=_bool(e("NOTIFY_ON_START"), True),
            stt_enabled=_bool(e("STT_ENABLED"), True),
            stt_model=(e("STT_MODEL") or DEFAULT_STT_MODEL).strip(),
            stt_language=(e("STT_LANGUAGE") or "").strip().lower(),
            zabbix_entry=(e("ZABBIX_ENTRY") or "zabbix").strip(),
            zabbix_poll_sec=_int(e("ZABBIX_POLL_SEC"), 120),
            zabbix_min_severity=_int(e("ZABBIX_MIN_SEVERITY"), 3),
            alert_tasks_per_hour=_int(e("ALERT_TASKS_PER_HOUR"), 3),
            daily_check_at=(e("DAILY_CHECK_AT") or "").strip(),
            control_enabled=_bool(e("CONTROL_ENABLED"), True),
            control_port=_int(e("CONTROL_PORT"), 8787),
            control_token=(e("CONTROL_TOKEN") or "").strip(),
            reels_enabled=_bool(e("REELS_ENABLED"), False),
            reels_per_day=_int(e("REELS_PER_DAY"), 2),
            reels_prepare_at=(e("REELS_PREPARE_AT") or "").strip(),
            reels_tts=(e("REELS_TTS") or "auto").strip().lower(),
            reels_voice=(e("REELS_VOICE") or "uz-UZ-MadinaNeural").strip(),
            reels_rate=(e("REELS_RATE") or "+0%").strip(),
            reels_font=(e("REELS_FONT") or "").strip(),
            reels_brand=(e("REELS_BRAND") or "").strip(),
            azure_speech_key=(e("AZURE_SPEECH_KEY") or "").strip(),
            azure_speech_region=(e("AZURE_SPEECH_REGION") or "").strip(),
            twelvedata_api_key=(e("TWELVEDATA_API_KEY") or "").strip(),
        )

    def problems(self, need_telegram: bool = True) -> list[str]:
        """Yetishmayotgan qiymatlar — aniq qayerga nima qo'yish kerakligi bilan."""
        out: list[str] = []
        env = str(ENV_FILE)
        if need_telegram and not self.telegram_token:
            out.append(f"TELEGRAM_BOT_TOKEN bo'sh. BotFather'dan YANGI token olib {env} ga yozing.")
        if need_telegram and not self.allowed_chat_id:
            out.append(f"ALLOWED_CHAT_ID bo'sh. {env} ga ALLOWED_CHAT_ID=871134228 yozing.")
        for name, value in (("ANTHROPIC_EFFORT", self.effort), ("ANTHROPIC_STRONG_EFFORT", self.strong_effort)):
            if value not in VALID_EFFORTS:
                out.append(f"{name}={value} noto'g'ri. Ruxsat: {', '.join(sorted(VALID_EFFORTS))}.")
        if self.daily_check_at and daily_time(self.daily_check_at) is None:
            out.append(f"DAILY_CHECK_AT={self.daily_check_at} noto'g'ri. Format: HH:MM (masalan 09:00) yoki bo'sh.")
        if not 0 <= self.zabbix_min_severity <= 5:
            out.append(f"ZABBIX_MIN_SEVERITY={self.zabbix_min_severity} noto'g'ri. Ruxsat: 0..5 (3 = Average).")
        if self.reels_prepare_at and daily_time(self.reels_prepare_at) is None:
            out.append(f"REELS_PREPARE_AT={self.reels_prepare_at} noto'g'ri. Format: HH:MM yoki bo'sh.")
        if self.reels_tts not in {"auto", "azure", "edge"}:
            out.append(f"REELS_TTS={self.reels_tts} noto'g'ri. Ruxsat: auto, azure, edge.")
        if self.reels_tts == "azure" and not (self.azure_speech_key and self.azure_speech_region):
            out.append("REELS_TTS=azure, lekin AZURE_SPEECH_KEY / AZURE_SPEECH_REGION bo'sh.")
        if not 1 <= self.reels_per_day <= 10:
            out.append(f"REELS_PER_DAY={self.reels_per_day} noto'g'ri. Ruxsat: 1..10.")
        return out


def daily_time(value: str) -> tuple[int, int] | None:
    """'09:00' -> (9, 0); noto'g'ri bo'lsa None."""
    parts = (value or "").strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    hh, mm = int(parts[0]), int(parts[1])
    return (hh, mm) if 0 <= hh < 24 and 0 <= mm < 60 else None
