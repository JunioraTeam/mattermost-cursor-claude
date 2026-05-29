"""Mattermost WebSocket client (port of mattermost/websocket.ts).

Auth must use action ``authentication_challenge`` (not ``authentication``); otherwise
the server never sets a session token and closes the socket after ~5s.
See https://api.mattermost.com/#tag/WebSocket
"""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlsplit, urlunsplit

import aiohttp

if TYPE_CHECKING:
    from ..util.logger import Logger

MattermostWsHandler = Callable[[dict[str, Any]], Any]


class MattermostWebSocket:
    def __init__(
        self,
        site_url: str,
        token: str,
        log: "Logger",
        on_event: MattermostWsHandler,
    ) -> None:
        self._site_url = site_url
        self._token = token
        self._log = log
        self._on_event = on_event
        self._seq = 1
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._closing = False

    def _ws_url(self) -> str:
        parts = urlsplit(self._site_url)
        scheme = "wss" if parts.scheme == "https" else "ws"
        return urlunsplit((scheme, parts.netloc, "/api/v4/websocket", "", ""))

    def connect(self) -> None:
        """Start the connect/receive loop as a background task."""
        self._closing = False
        if self._task is None or self._task.done():
            self._task = asyncio.ensure_future(self._run())

    async def _run(self) -> None:
        while not self._closing:
            url = self._ws_url()
            self._log.info("Connecting Mattermost WebSocket", url=url)
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession()
                async with self._session.ws_connect(url) as ws:
                    self._ws = ws
                    self._log.info("WebSocket open, authenticating")
                    await self._send_json(
                        {
                            "seq": self._next_seq(),
                            "action": "authentication_challenge",
                            "data": {"token": self._token},
                        }
                    )
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                raw = json.loads(msg.data)
                                result = self._on_event(raw)
                                if asyncio.iscoroutine(result):
                                    asyncio.ensure_future(result)
                            except Exception as e:
                                self._log.warning("Invalid WS payload", err=str(e))
                        elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                            break
            except Exception as e:
                self._log.error("WebSocket error", err=str(e))
            finally:
                self._ws = None

            if self._closing:
                break
            self._log.warning("WebSocket closed, reconnecting in 5s")
            await asyncio.sleep(5)

    def _next_seq(self) -> int:
        s = self._seq
        self._seq += 1
        return s

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if self._ws is not None and not self._ws.closed:
            await self._ws.send_str(json.dumps(payload))

    async def aclose(self) -> None:
        self._closing = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._session is not None and not self._session.closed:
            await self._session.close()
