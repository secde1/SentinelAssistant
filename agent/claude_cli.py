"""Claude obunasi: rasmiy Claude Code CLI, login tekshiruvi, env tozalash, limit holati.

Model faqat Claude Code CLI orqali, `claude auth login` (yoki `claude setup-token`) bilan olingan Claude Pro/Max
login bilan chaqiriladi. CLI'ni pullik API'ga yo'naltiradigan har qanday credential jarayon muhitidan olib
tashlanadi va har topshiriqdan oldin `claude auth status` bilan tekshiriladi. Limit tugasa — to'xtaymiz.
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .tools.powershell import exec_process

# code.claude.com/docs/en/authentication -> "Authentication precedence": bularning har biri claude.ai obunadan
# USTUN turadi (ANTHROPIC_API_KEY `-p`/SDK rejimida doim ishlatiladi). Obuna rejimida CLI ularni ko'rmasligi shart.
PAID_ENV = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
    "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_SERVICE_ACCOUNT_ID",
    "ANTHROPIC_IDENTITY_TOKEN", "ANTHROPIC_IDENTITY_TOKEN_FILE",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
)
SUBSCRIPTION_PLANS = {"pro", "max", "team", "enterprise"}

LOGIN_HELP = (
    "Login (agent ishlaydigan hisobda, bir marta): claude auth login -> brauzerda Pro akkaunt bilan kiring; "
    "tekshirish: claude auth status. Windows xizmati (LocalSystem) uchun: claude setup-token -> chiqqan tokenni "
    ".env ga CLAUDE_CODE_OAUTH_TOKEN=... deb yozing. Batafsil: README, 'Obuna rejimi'."
)

_WINDOWS = {"five_hour": "5 soatlik", "seven_day": "haftalik", "seven_day_opus": "haftalik (Opus)",
            "seven_day_sonnet": "haftalik (Sonnet)", "overage": "qo'shimcha (extra usage)"}


class SubscriptionStop(Exception):
    """Obuna rejimida davom etib bo'lmaydi (limit, login, pullik credential). code: quota | error."""

    def __init__(self, text: str, code: str = "error", until: float | None = None):
        super().__init__(text)
        self.text = text
        self.code = code
        self.until = until


def _paid_or_nested(key: str, nested: bool) -> bool:
    if key in PAID_ENV:
        return True
    # Agent boshqa Claude Code sessiyasi ichidan (VS Code terminali) ishga tushirilsa — ota sessiyaga bog'lanmasin.
    return nested and (key in ("CLAUDECODE", "CLAUDE_PID") or key.startswith("CLAUDE_AGENT_SDK")
                       or (key.startswith("CLAUDE_CODE_") and key != "CLAUDE_CODE_OAUTH_TOKEN"))


def clean_env(cfg: Config) -> dict:
    """CLI uchun muhit nusxasi: pullik credential'larsiz (os.environ o'zgarmaydi)."""
    nested = bool(os.environ.get("CLAUDECODE"))
    env = {k: v for k, v in os.environ.items() if not _paid_or_nested(k, nested)}
    if cfg.claude_oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = cfg.claude_oauth_token
    return env


def prepare_process_env() -> list[str]:
    """Agent SDK CLI'ga os.environ ni meros qilib beradi, shuning uchun pullik credential'lar jarayondan olib tashlanadi.
    Qiymati bo'sh bo'lmagan olib tashlangan o'zgaruvchi nomlarini qaytaradi (qiymatlarsiz)."""
    nested = bool(os.environ.get("CLAUDECODE"))
    removed = []
    for k in [k for k in list(os.environ) if _paid_or_nested(k, nested)]:
        if os.environ.pop(k, "").strip():
            removed.append(k)
    return removed


def cli_path(cfg: Config) -> str | None:
    """CLAUDE_CLI_PATH -> claude-agent-sdk bilan kelgan rasmiy CLI -> PATH dagi claude. Faqat .exe/binary, .cmd emas."""
    if cfg.claude_cli_path:
        return cfg.claude_cli_path
    name = "claude.exe" if os.name == "nt" else "claude"
    try:
        import claude_agent_sdk
        bundled = Path(claude_agent_sdk.__file__).parent / "_bundled" / name
        if bundled.is_file():
            return str(bundled)
    except ImportError:
        pass
    found = shutil.which(name)
    return found if found and Path(found).suffix.lower() not in {".cmd", ".bat"} else None


@dataclass
class AuthInfo:
    ok: bool
    method: str = ""
    plan: str = ""
    email: str = ""
    problem: str = ""

    @property
    def label(self) -> str:
        if self.method == "oauth_token":
            return "claude setup-token (CLAUDE_CODE_OAUTH_TOKEN), obuna"
        return f"claude.ai login, {self.plan.capitalize()} obuna" + (f" ({self.email})" if self.email else "")


def evaluate_auth(data: dict) -> AuthInfo:
    """`claude auth status --json` natijasini baholaydi: faqat claude.ai obunasi yoki setup-token qabul qilinadi."""
    method = str(data.get("authMethod") or "")
    if not data.get("loggedIn"):
        return AuthInfo(False, method, problem="Claude Code'ga login qilinmagan.")
    if data.get("apiProvider", "firstParty") != "firstParty":
        return AuthInfo(False, method, problem=f"CLI '{data.get('apiProvider')}' provayderiga sozlangan — obuna emas.")
    source = data.get("apiKeySource")
    if source and source != "none":
        return AuthInfo(False, method, problem=f"CLI pullik API credential'ni ishlatmoqchi ({source}). Obuna rejimida "
                                               "bu taqiqlangan — uni olib tashlang (env yoki apiKeyHelper).")
    if method == "oauth_token":
        return AuthInfo(True, method, plan="setup-token")
    if method != "claude.ai":
        return AuthInfo(False, method, problem=f"Login turi '{method or 'nomaʼlum'}' obuna emas (Console/API). "
                                               "claude.ai Pro akkaunti bilan qayta kiring.")
    plan = str(data.get("subscriptionType") or "")
    if plan not in SUBSCRIPTION_PLANS:
        return AuthInfo(False, method, plan, problem=f"claude.ai akkauntida obuna topilmadi (subscriptionType="
                                                     f"{plan or 'yoʻq'}).")
    return AuthInfo(True, method, plan, str(data.get("email") or ""))


async def cli_version(cfg: Config) -> str:
    exe = cli_path(cfg)
    if not exe:
        return ""
    try:
        rc, out = await exec_process([exe, "--version"], clean_env(cfg), 60)
    except OSError:
        return ""
    return out.strip().splitlines()[0] if rc == 0 and out.strip() else ""


async def auth_status(cfg: Config) -> AuthInfo:
    """Rasmiy `claude auth status --json` (argv ro'yxati, shell yo'q). Model chaqirilmaydi, limit sarflanmaydi."""
    exe = cli_path(cfg)
    if not exe:
        return AuthInfo(False, problem="Claude Code CLI topilmadi: pip install -r requirements.txt (claude-agent-sdk "
                                       "rasmiy CLI'ni olib keladi) yoki .env da CLAUDE_CLI_PATH ni ko'rsating.")
    try:
        rc, out = await exec_process([exe, "auth", "status", "--json"], clean_env(cfg), 60)
    except OSError as exc:
        return AuthInfo(False, problem=f"Claude Code CLI ishga tushmadi ({exe}): {exc}")
    try:
        data = json.loads(out[out.index("{"): out.rindex("}") + 1])
    except ValueError:
        return AuthInfo(False, problem=f"`claude auth status` tushunarsiz javob berdi (exit {rc}): {out.strip()[:200]}")
    return evaluate_auth(data)


# --- obuna limiti --------------------------------------------------------------------------------------------------

def window_usage(raw: dict) -> str:
    """'5 soatlik 26%, haftalik 20%' — rate_limit_event dagi oynalar bo'yicha."""
    parts = []
    for key, win in (raw.get("unifiedWindows") or {}).items():
        if isinstance(win, dict) and win.get("utilization") is not None:
            parts.append(f"{_WINDOWS.get(key, key)} {round(float(win['utilization']) * 100)}%")
    return ", ".join(parts)


def _when(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else "nomaʼlum"


def quota_stop(rate_limit_type: str | None, resets_at: float | None, detail: str = "") -> SubscriptionStop:
    kind = _WINDOWS.get(rate_limit_type or "", "obuna")
    until = float(resets_at) if resets_at else time.time() + 600
    text = (f"⛔ Claude obuna limiti tugadi ({kind}). Tiklanadi: {_when(resets_at)}"
            f"{'' if resets_at else ' (taxminan 10 daqiqadan keyin qayta urinib ko`ring)'}.\n"
            "Pullik API ham, qo'shimcha sarf (extra usage) ham ishlatilmadi — topshiriq to'xtatildi. "
            "Limit tiklangach topshiriqni qayta yuboring.")
    if detail:
        text += f"\nCLI: {detail[:200]}"
    return SubscriptionStop(text, "quota", until)


class QuotaGuard:
    """Limit tugagach yangi topshiriqlarni tiklanish vaqtigacha qabul qilmaydi (CLI'ni bekorga urmaymiz)."""

    def __init__(self) -> None:
        self.until = 0.0

    def block(self, until: float | None) -> None:
        self.until = max(self.until, until or time.time() + 600)

    def reason(self) -> str | None:
        if time.time() >= self.until:
            return None
        return (f"⛔ Claude obuna limiti tugagan — {_when(self.until)} gacha yangi topshiriq bajarilmaydi. "
                "Pullik API'ga o'tilmaydi.")
