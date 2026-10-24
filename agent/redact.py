"""Maxfiy qiymatlarni yashirish (redaction).

Ikki qatlam:
  1) Ma'lum qiymatlar — inventar.json, .env va yaratilgan parollardagi aniq qiymatlar.
  2) Naqshlar — password=..., "token": "...", Bearer ..., bot token, sk-ant-..., private key va h.k.
Jurnal, Telegram, skill/xotira yozuvi va modelga qaytadigan tool natijasi shu yerdan o'tadi.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Iterable

MASK = "***"

SECRET_WORDS = (
    r"(?:password|passwd|passwort|pwd|parol|пароль|secret|token|api[_-]?key|apikey|access[_-]?key"
    r"|private[_-]?key|community|psk|pre[_-]?shared[_-]?key|passphrase|auth(?:entication)?[_-]?key"
    r"|priv(?:acy)?[_-]?key|credential)"
)
_SECRET_WORDS_RE = re.compile(SECRET_WORDS, re.I)

# Kalit nomida shular bo'lsa — bu maxfiy qiymat emas, metadata (PasswordLastSet, max_tokens, secret_name...).
_EXEMPT_KEY_PARTS = (
    "lastset", "last_set", "expir", "never", "notrequired", "not_required", "cannotchange",
    "cannot_change", "age", "length", "history", "policy", "count", "complex", "required",
    "changed", "date", "time", "enabled", "type", "mode", "status", "file", "path", "url",
    "uri", "name", "tokens", "usage", "hint", "prompt", "field", "strength", "reset", "id_",
    "_id", "provider", "store", "manager",
)

_KV_RE = re.compile(
    r"(?P<key>\b[\w.-]*" + SECRET_WORDS + r"[\w.-]*)(?P<q>[\"']?)(?P<sep>\s*[:=]\s*)"
    r"(?P<val>\"(?:[^\"\\\n]|\\.)*\"|'[^'\n]*'|[^\s,;&\"'<>)\]}]+)",
    re.I,
)
_PS_SECURESTRING_RE = re.compile(r"(?i)(ConvertTo-SecureString\s+(?:-String\s+)?)(\"[^\"\n]*\"|'[^'\n]*')")
_PS_PARAM_RE = re.compile(
    r"(?i)(-(?:Password|NewPassword|OldPassword|Secret|Token|ApiKey|Passphrase|Community|PreSharedKey|Psk)"
    r"\s+)(\"[^\"\n]*\"|'[^'\n]*'|(?![$(@])[^\s;|]+)"
)
_SIMPLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S),
     "-----PRIVATE KEY " + MASK + "-----"),
    (re.compile(r"(?<!\d)\d{8,10}:[A-Za-z0-9_-]{30,}"), MASK),       # Telegram bot token (URL ichida ham)
    (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{10,}"), MASK),              # Anthropic kaliti
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"), MASK),  # GitHub token
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}"), MASK),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), MASK),           # Slack
    (re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"), MASK),            # AWS access key
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), MASK),  # JWT
    (re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]{12,}"), r"\1" + MASK),
    (re.compile(r"(?i)(\bBasic\s+)[A-Za-z0-9+/=]{12,}"), r"\1" + MASK),
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://[^/\s:@]+:)([^@\s/]+)(@)"), r"\1" + MASK + r"\3"),
]

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(?:inv|secret):")


def is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value))


def is_secret_key(key: str) -> bool:
    kl = key.lower()
    if any(part in kl for part in _EXEMPT_KEY_PARTS):
        return False
    return bool(_SECRET_WORDS_RE.search(kl))


def _kv_sub(m: re.Match[str]) -> str:
    key, val = m.group("key"), m.group("val")
    if not is_secret_key(key) or "{{" in m.string[max(0, m.start() - 3):m.start()]:
        return m.group(0)  # {{secret:NOM}} placeholderi — maxfiy qiymat emas
    inner = val[1:-1] if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0] else val
    if not inner or inner == MASK or inner.startswith("$") or is_placeholder(inner) or inner.startswith("("):
        return m.group(0)
    masked = f"{val[0]}{MASK}{val[0]}" if inner != val else MASK
    return f"{key}{m.group('q')}{m.group('sep')}{masked}"


def _quoted_sub(m: re.Match[str]) -> str:
    val = m.group(2)
    if is_placeholder(val):
        return m.group(0)
    if len(val) >= 2 and val[0] in "\"'":
        return f"{m.group(1)}{val[0]}{MASK}{val[0]}"
    return f"{m.group(1)}{MASK}"


class Redactor:
    """`secret_source` — har chaqiruvda joriy maxfiy qiymatlar ro'yxatini qaytaruvchi funksiya."""

    def __init__(self, secret_source: Callable[[], Iterable[str]] | None = None):
        self._source = secret_source
        self._static: set[str] = set()

    def add(self, *values: str) -> None:
        for v in values:
            if v:
                self._static.add(str(v))

    def known_values(self) -> list[str]:
        values = set(self._static)
        if self._source:
            try:
                values.update(str(v) for v in self._source() if v)
            except Exception:  # noqa: BLE001 — redaction hech qachon yiqilmasligi kerak
                pass
        good = [v for v in values if len(v) >= (6 if v.isdigit() else 4)]
        return sorted(good, key=len, reverse=True)

    def redact(self, text: Any) -> Any:
        if not isinstance(text, str) or not text:
            return text
        s = text
        for value in self.known_values():
            if value in s:
                s = s.replace(value, MASK)
        for pattern, repl in _SIMPLE_PATTERNS:
            s = pattern.sub(repl, s)
        s = _PS_SECURESTRING_RE.sub(_quoted_sub, s)
        s = _PS_PARAM_RE.sub(_quoted_sub, s)
        s = _KV_RE.sub(_kv_sub, s)
        return s

    def redact_obj(self, obj: Any) -> Any:
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if isinstance(k, str) and is_secret_key(k) and isinstance(v, (str, int, float)) and v != "":
                    out[k] = v if isinstance(v, str) and is_placeholder(v) else MASK
                else:
                    out[k] = self.redact_obj(v)
            return out
        if isinstance(obj, (list, tuple)):
            return [self.redact_obj(v) for v in obj]
        if isinstance(obj, str):
            return self.redact(obj)
        return obj
