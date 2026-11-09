"""Bo'lim xodimlari uchun Claude chaqiruvi: Claude Code obunasi (pullik API'siz), HECH QANDAY tool yo'q (faqat matn)."""
from __future__ import annotations

import logging
from pathlib import Path

from .. import claude_cli
from ..config import Config

log = logging.getLogger(__name__)


def make_llm(cfg: Config, home: Path):
    """(system, prompt) -> matn. Obuna kvotasi tugasa yoki pullik credential ko'rinsa — istisno (bo'lim zdelka ochmaydi)."""
    work = Path(home) / "ish" / "staff"
    work.mkdir(parents=True, exist_ok=True)

    async def ask(system: str, prompt: str) -> str:
        from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, HookMatcher, RateLimitEvent,
                                      ResultMessage, SystemMessage, TextBlock)

        async def deny_all(input_data: dict, tool_use_id, context) -> dict:
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                           "permissionDecisionReason": "Bo'lim xodimlarida tool yo'q."}}

        env = {"CLAUDE_AGENT_SDK_CLIENT_APP": "it-agent-staff", "DISABLE_AUTOUPDATER": "1"}
        if cfg.claude_oauth_token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = cfg.claude_oauth_token
        (work / "system.md").write_text(system, encoding="utf-8")
        options = ClaudeAgentOptions(system_prompt=system, tools=[], mcp_servers={}, allowed_tools=[], permission_mode="dontAsk",
                                     strict_mcp_config=True, setting_sources=[], model=cfg.model, effort="low", max_turns=1,
                                     cwd=str(work), cli_path=claude_cli.cli_path(cfg), env=env,
                                     hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[deny_all])]})
        result_text, last_text = "", ""
        async with ClaudeSDKClient(options) as client:
            await client.query(prompt)
            async for msg in client.receive_response():
                if isinstance(msg, SystemMessage) and msg.subtype == "init":
                    if str(msg.data.get("apiKeySource") or "none") != "none":
                        raise claude_cli.SubscriptionStop("pullik API credential — obuna rejimida taqiqlangan")
                elif isinstance(msg, RateLimitEvent):
                    info = msg.rate_limit_info
                    if info.status == "rejected" or (info.raw or {}).get("isUsingOverage"):
                        raise claude_cli.quota_stop(info.rate_limit_type, info.resets_at)
                elif isinstance(msg, AssistantMessage):
                    if msg.error == "rate_limit":
                        raise claude_cli.quota_stop(None, None)
                    if msg.error in ("billing_error", "authentication_failed"):
                        raise claude_cli.SubscriptionStop(f"Claude xatosi: {msg.error}")
                    text = "".join(b.text for b in msg.content if isinstance(b, TextBlock)).strip()
                    last_text = text or last_text
                elif isinstance(msg, ResultMessage):
                    if msg.is_error and msg.api_error_status == 429:
                        raise claude_cli.quota_stop(None, None)
                    result_text = (msg.result or "").strip()
        return result_text or last_text

    return ask
