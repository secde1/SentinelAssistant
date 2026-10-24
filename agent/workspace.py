"""Agent bazaviy papkasi (AGENT_HOME): papkalar, boshlang'ich xotira fayllari, .gitignore."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SUBDIRS = ("xotira", "skill", "jurnal", "maxfiy", "zaxira", "ish", "skript")

# GitHubga faqat skill/, xotira/, skript/ tushadi.
GITIGNORE = """\
.env
maxfiy/
zaxira/
jurnal/
ish/
modellar/
__pycache__/
*.pyc
venv/
.venv/
"""

SEED_FILES = {
    "xotira/inventar.md": (
        "# Inventar\n\n"
        "> Host / IP / VM / qurilma ro'yxati. PAROL YOZILMAYDI — parollar faqat maxfiy/inventar.json da.\n"
    ),
    "xotira/fakt.md": "# Doimiy faktlar\n\n> Bir marta aytilgan doimiy ma'lumot.\n",
    "xotira/tarix.md": (
        "# Hal qilingan muammolar tarixi\n\n"
        "> Har yozuv: belgi -> sabab -> tuzatish -> natija. Yangi muammoda avval shu yerdan o'xshashini qidiring.\n"
    ),
    "xotira/boshliq.md": "# Jamshid: uslub va ustuvorliklar\n\n> 2 marta tuzatilgan narsa — doimiy qoida.\n",
    "xotira/prompt_qoshimcha.md": (
        "# Tizim promptiga qo'shimchalar\n\n"
        "> Agent o'z ish uslubini shu yerda yaxshilaydi. Xavfsizlik qoidalari bu yerda O'ZGARMAYDI.\n"
    ),
    "xotira/kunlik_tekshiruv.md": (
        "# Kunlik tekshiruv\n\n"
        "> .env dagi DAILY_CHECK_AT vaqtida avtomatik bajariladi. Ro'yxatni o'zingizga moslang (har qator — bitta "
        "tekshiruv).\n> Agent faqat o'qiydi; muammo topsa — hisobot va taklif, o'zgartirish faqat tasdiq bilan.\n\n"
        "- Shu serverdagi disklarda bo'sh joy (15% dan kam bo'lsa ogohlantir)\n"
        "- Avtomatik ishga tushishi kerak, lekin to'xtagan xizmatlar (trigger/kechiktirilgan odatiy xizmatlarni hisobga olma)\n"
        "- Oxirgi 24 soatdagi System va Application loglaridagi Critical/Error hodisalar: soni va eng ko'p takrorlanganlari\n"
        "- Inventardagi hostlar ping'ga javob beradimi\n"
    ),
}


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def xotira(self) -> Path:
        return self.home / "xotira"

    @property
    def skill(self) -> Path:
        return self.home / "skill"

    @property
    def jurnal(self) -> Path:
        return self.home / "jurnal"

    @property
    def maxfiy(self) -> Path:
        return self.home / "maxfiy"

    @property
    def zaxira(self) -> Path:
        return self.home / "zaxira"

    @property
    def ish(self) -> Path:
        return self.home / "ish"

    @property
    def skript(self) -> Path:
        return self.home / "skript"

    @property
    def inventory_json(self) -> Path:
        return self.maxfiy / "inventar.json"

    @property
    def known_hosts(self) -> Path:
        return self.maxfiy / "known_hosts"

    @property
    def chat_history(self) -> Path:
        return self.ish / "suhbat.jsonl"

    @property
    def mcp_json(self) -> Path:
        """Tashqi MCP serverlar sozlamasi — maxfiy/ ichida: model uni o'qiy ham, o'zgartira ham olmaydi."""
        return self.maxfiy / "mcp.json"

    @property
    def zabbix_state(self) -> Path:
        return self.ish / "zabbix_kuzatuv.json"

    @property
    def models(self) -> Path:
        """STT modellari (GitHubga tushmaydi — skill/xotira/skript emas)."""
        return self.home / "modellar"


def ensure_workspace(home: Path) -> Paths:
    paths = Paths(Path(home))
    for name in SUBDIRS:
        (paths.home / name).mkdir(parents=True, exist_ok=True)
    for rel, content in SEED_FILES.items():
        target = paths.home / rel
        if not target.exists():
            target.write_text(content, encoding="utf-8")
    gi = paths.home / ".gitignore"
    if not gi.exists() or gi.read_text(encoding="utf-8") != GITIGNORE:
        gi.write_text(GITIGNORE, encoding="utf-8")
    if not paths.inventory_json.exists():
        paths.inventory_json.write_text(
            json.dumps({"hosts": {}, "generated": {}}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return paths
