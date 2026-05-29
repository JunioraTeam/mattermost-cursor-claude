"""Helpers for running aiohttp apps as background servers on a shared event loop."""
from __future__ import annotations

from aiohttp import web


class ServerHandle:
    """A started aiohttp server with an async ``close()`` for graceful shutdown."""

    def __init__(self, runner: web.AppRunner) -> None:
        self._runner = runner

    async def close(self) -> None:
        await self._runner.cleanup()


async def start_app(app: web.Application, port: int) -> ServerHandle:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    return ServerHandle(runner)
