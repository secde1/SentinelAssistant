"""Umumiy test yordamchisi: ToolContext (soxta kanal bilan)."""
from __future__ import annotations


def _ctx(tmp_path):
    from agent.config import Config
    from agent.inventory import Inventory
    from agent.journal import Journal
    from agent.redact import Redactor
    from agent.tools import ToolContext
    from agent.workspace import ensure_workspace

    paths = ensure_workspace(tmp_path / "home")
    inv = Inventory(paths.inventory_json)
    red = Redactor(inv.secret_values)

    class Ch:
        async def send(self, t): pass
        async def send_file(self, p, c=""): pass
        async def ask(self, q): return None
        async def request_approval(self, t): return False
        async def request_secret(self, p): return None
    return ToolContext(task_id="T-TEST", cfg=Config(agent_home=paths.home), paths=paths, inventory=inv, redactor=red,
                       journal=Journal(paths.jurnal, red), channel=Ch())
