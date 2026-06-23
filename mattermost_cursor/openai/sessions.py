"""Warm pool of single-use agents for the OpenAI-compatible API.

The OpenAI/Responses path is stateless — it re-feeds the full transcript on every
call — so each request gets its own agent, used once and disposed. That avoids a
shared conversation (no cross-thread bleed, no concurrent-request interleaving),
but spawning the bundled CLI + MCP servers costs ~seconds.

This pool keeps a few agents pre-built in the background so a request grabs a
ready one instead of waiting on a cold spawn. Each agent is still used exactly
once (never handed out twice → statelessness preserved); on a burst that drains
the pool, callers fall back to an on-demand build.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from ..provider import create_agent

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger

# Pre-built agents kept ready. Each holds an idle CLI + MCP subprocess set, so
# this trades a little idle resource for lower per-request latency.
DEFAULT_WARM_TARGET = 2


class OpenAISessionPool:
    def __init__(
        self, env: "AppEnv", log: "Logger", client: Any, *, warm_target: int = DEFAULT_WARM_TARGET
    ) -> None:
        self._env = env
        self._log = log
        self._client = client
        self._warm: asyncio.Queue[tuple[Any, dict[str, Any]]] = asyncio.Queue(
            maxsize=max(1, warm_target) if warm_target > 0 else 1
        )
        self._warm_target = warm_target
        self._replenisher: asyncio.Task[None] | None = None

    def start_warming(self) -> None:
        """Begin background pre-building. No-op if warming is disabled."""
        if self._warm_target > 0 and self._replenisher is None:
            self._replenisher = asyncio.ensure_future(self._replenish_loop())

    async def _build(self) -> tuple[Any, dict[str, Any]]:
        return await create_agent(self._env, self._log, self._client)

    async def _replenish_loop(self) -> None:
        # Keep the queue full: put() blocks while it is at capacity and unblocks as
        # soon as a request consumes one, so exactly `warm_target` stay ready.
        while True:
            try:
                item = await self._build()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._log.error("warm agent build failed; retrying", err=str(e))
                await asyncio.sleep(2)
                continue
            try:
                await self._warm.put(item)
            except asyncio.CancelledError:
                await self.dispose(item[0])
                raise

    async def create_agent_once(self) -> tuple[Any, dict[str, Any]]:
        """A warm agent if one is ready, else built on demand. Single-use — the
        caller must ``dispose()`` it when the run finishes."""
        try:
            return self._warm.get_nowait()
        except asyncio.QueueEmpty:
            return await self._build()

    async def dispose(self, agent: Any) -> None:
        await self._dispose(agent)

    async def _dispose(self, agent: Any) -> None:
        try:
            await agent.close()
        except Exception:
            pass

    async def aclose(self) -> None:
        """Stop warming and dispose any ready agents."""
        if self._replenisher:
            self._replenisher.cancel()
            self._replenisher = None
        while True:
            try:
                agent, _ = self._warm.get_nowait()
            except asyncio.QueueEmpty:
                break
            await self.dispose(agent)
