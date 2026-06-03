"""Claude provider client holder.

The Claude Agent SDK spawns a local Claude Code process per agent session, so —
unlike the Cursor bridge — there is no shared long-lived client to launch. This
holder exists only to keep the provider façade symmetric with the Cursor one
(``create_client`` → passed to ``create_agent`` → closed on shutdown).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger


class ClaudeClient:
    """No-op shared client. Each agent owns its own ClaudeSDKClient subprocess."""

    async def aclose(self) -> None:
        return


async def create_client(env: "AppEnv", log: "Logger") -> ClaudeClient:
    log.info("Using Claude Agent SDK provider", model=env.CLAUDE_MODEL)
    return ClaudeClient()
