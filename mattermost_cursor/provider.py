"""Provider façade — selects Cursor or Claude based on ``AI_PROVIDER``.

Callers (the Mattermost bot, the OpenAI server, the entry point) go through here
instead of importing a specific provider, so swapping providers is one env var.
Both providers return the same ``agent.send → run.messages()/.wait()`` surface.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import AppEnv
    from .util.logger import Logger


async def create_client(env: "AppEnv", log: "Logger") -> Any:
    if env.AI_PROVIDER == "claude":
        from .claude.client import create_client as _create
        return await _create(env, log)
    from .cursor.client import create_client as _create
    return await _create(env, log)


async def create_agent(
    env: "AppEnv", log: "Logger", client: Any, resume: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    if env.AI_PROVIDER == "claude":
        from .claude.create_agent import create_claude_agent
        return await create_claude_agent(env, log, client, resume=resume)
    from .cursor.create_agent import create_cursor_agent
    return await create_cursor_agent(env, log, client, resume=resume)


def active_model(env: "AppEnv") -> str:
    return env.CLAUDE_MODEL if env.AI_PROVIDER == "claude" else env.CURSOR_MODEL
