"""Build ClaudeAgentOptions and create Claude agent sessions."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeAgentOptions

from ..cursor.mcp_servers import build_mcp_servers
from .agent_session import ClaudeAgentSession

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger
    from .client import ClaudeClient


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def _normalize_mcp_servers(servers: dict[str, Any]) -> dict[str, Any]:
    """The Cursor and Claude SDKs share MCP config shapes, but Claude rejects
    ``None`` fields (e.g. an empty ``env``); drop them."""
    out: dict[str, Any] = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            out[name] = cfg
            continue
        out[name] = {k: v for k, v in cfg.items() if v is not None}
    return out


def _system_prompt(env: "AppEnv") -> Any:
    appended = (env.CLAUDE_SYSTEM_PROMPT or "").strip()
    if env.CLAUDE_SYSTEM_PROMPT_PRESET:
        preset: dict[str, Any] = {"type": "preset", "preset": "claude_code"}
        if appended:
            preset["append"] = appended
        return preset
    return appended or None


def build_claude_options(
    env: "AppEnv", log: "Logger", resume: str | None = None,
) -> ClaudeAgentOptions:
    mcp_servers = _normalize_mcp_servers(build_mcp_servers(env, log))

    proc_env: dict[str, str] = {}
    if env.ANTHROPIC_API_KEY:
        proc_env["ANTHROPIC_API_KEY"] = env.ANTHROPIC_API_KEY

    opts = ClaudeAgentOptions(
        model=env.CLAUDE_MODEL,
        cwd=env.CLAUDE_CWD or os.getcwd(),
        permission_mode=env.CLAUDE_PERMISSION_MODE,
        system_prompt=_system_prompt(env),
        mcp_servers=mcp_servers,
        allowed_tools=_csv(env.CLAUDE_ALLOWED_TOOLS),
        disallowed_tools=_csv(env.CLAUDE_DISALLOWED_TOOLS),
        env=proc_env,
    )
    if env.CLAUDE_MAX_TURNS:
        opts.max_turns = env.CLAUDE_MAX_TURNS
    # Resume a prior conversation by session id (persisted per Mattermost thread).
    # The SDK loads the transcript from its local session store; if that file is
    # gone (e.g. a fresh container) resume is a no-op and the bot's per-turn
    # thread re-feed still rebuilds context.
    if resume:
        opts.resume = resume
    return opts


async def create_claude_agent(
    env: "AppEnv", log: "Logger", client: "ClaudeClient", resume: str | None = None,
) -> tuple[ClaudeAgentSession, dict[str, Any]]:
    opts = build_claude_options(env, log, resume=resume)
    session = ClaudeAgentSession(opts, log)
    await session.connect()
    mcp_servers: dict[str, Any] = dict(opts.mcp_servers) if isinstance(opts.mcp_servers, dict) else {}
    log.info(
        "Claude agent created",
        model=env.CLAUDE_MODEL,
        permission_mode=env.CLAUDE_PERMISSION_MODE,
        mcp=list(mcp_servers.keys()),
        resumed=bool(resume),
    )
    return session, mcp_servers
