"""Reuses Cursor agents across OpenAI API calls (port of openai/sessions.ts).

Keyed by the Mattermost user id from the ``user`` field; idle sessions expire.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..provider import create_agent

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger

SESSION_TTL_MS = 60 * 60 * 1000


@dataclass
class Session:
    agent: Any
    mcp_servers: dict[str, Any]
    last_used: float  # epoch ms


class OpenAISessionPool:
    def __init__(self, env: "AppEnv", log: "Logger", client: Any) -> None:
        self._env = env
        self._log = log
        self._client = client
        self._sessions: dict[str, Session] = {}

    async def get(self, session_key: str) -> Session:
        self._evict_stale()
        s = self._sessions.get(session_key)
        if s:
            s.last_used = time.time() * 1000
            return s
        agent, mcp_servers = await create_agent(self._env, self._log, self._client)
        s = Session(agent=agent, mcp_servers=mcp_servers, last_used=time.time() * 1000)
        self._sessions[session_key] = s
        return s

    def _evict_stale(self) -> None:
        now = time.time() * 1000
        for key in list(self._sessions.keys()):
            s = self._sessions[key]
            if now - s.last_used > SESSION_TTL_MS:
                asyncio.ensure_future(self._dispose(s.agent))
                del self._sessions[key]

    async def create_agent_once(self) -> tuple[Any, dict[str, Any]]:
        """A fresh, uncached agent for one stateless request.

        The OpenAI/Responses path re-feeds the full transcript every call, so it
        does not reuse a persistent conversation — a per-request agent avoids
        cross-thread bleed and concurrent-request interleaving on a shared session.
        Caller must ``dispose()`` it when the run finishes.
        """
        return await create_agent(self._env, self._log, self._client)

    async def dispose(self, agent: Any) -> None:
        await self._dispose(agent)

    async def _dispose(self, agent: Any) -> None:
        try:
            await agent.close()
        except Exception:
            pass
