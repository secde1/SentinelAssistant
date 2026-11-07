"""Dashboard sozlamalari — .env dan (Config.from_env() uni os.environ ga yuklagandan keyin o'qiladi)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ..config import PROJECT_ROOT, _bool, _int

DEFAULT_AD_EXPORTS = "ish/ActiveComps.csv;ish/StaleComps.csv"


@dataclass
class DashboardSettings:
    port: int = 8790
    token: str = ""
    ad_exports: list[str] = field(default_factory=lambda: DEFAULT_AD_EXPORTS.split(";"))
    chat_enabled: bool = True
    sample_sec: int = 5
    history_points: int = 720  # 5 s * 720 = 1 soatlik grafik
    session_hours: int = 12
    stale_days: int = 30  # AD da shuncha kundan beri kirilmagan kompyuter — "nofaol"
    web_dir: Path = PROJECT_ROOT / "web" / "out"

    @classmethod
    def from_env(cls) -> "DashboardSettings":
        e = os.environ.get
        exports = [p.strip() for p in (e("DASHBOARD_AD_EXPORTS") or DEFAULT_AD_EXPORTS).split(";") if p.strip()]
        return cls(
            port=_int(e("DASHBOARD_PORT"), 8790),
            token=(e("DASHBOARD_TOKEN") or "").strip(),
            ad_exports=exports,
            chat_enabled=_bool(e("DASHBOARD_CHAT"), True),
            sample_sec=max(2, _int(e("DASHBOARD_SAMPLE_SEC"), 5)),
            stale_days=max(1, _int(e("DASHBOARD_STALE_DAYS"), 30)),
        )
