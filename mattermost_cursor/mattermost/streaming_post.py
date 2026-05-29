"""Incrementally updates a single Mattermost post (port of mattermost/streaming-post.ts).

Updates the post via REST PUT, debounced by ``stream_ms``. Implements StreamSink.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .stream_buffer import MattermostStreamBuffer

if TYPE_CHECKING:
    from .api import MattermostApi
    from .types import MattermostPost


class StreamingPost:
    def __init__(
        self,
        api: "MattermostApi",
        post: "MattermostPost",
        stream_ms: int,
        max_chars: int,
    ) -> None:
        self._api = api
        self._post = post
        self._stream_ms = stream_ms
        self._max_chars = max_chars
        self._stream = MattermostStreamBuffer()
        self._timer: asyncio.TimerHandle | None = None
        self._closed = False

    async def append(self, chunk: str) -> None:
        if self._closed:
            return
        self._stream.append(chunk)
        self._trim_if_needed()
        self._schedule_flush()

    async def update_assistant(self, text: str) -> None:
        if self._closed:
            return
        self._stream.update_assistant(text)
        self._trim_if_needed()
        self._schedule_flush()

    async def update_thinking(self, text: str) -> None:
        if self._closed:
            return
        self._stream.update_thinking(text)
        self._trim_if_needed()
        self._schedule_flush()

    async def finalize_assistant(self) -> None:
        if self._closed:
            return
        self._stream.finalize_assistant()
        self._trim_if_needed()

    async def update_tool_call(self, call_id: str, name: str, status: str) -> None:
        if self._closed:
            return
        self._stream.update_tool_call(call_id, name, status)
        self._trim_if_needed()
        self._schedule_flush()

    async def update_run_status(self, status: str, message: str | None = None) -> None:
        if self._closed:
            return
        self._stream.update_run_status(status, message)
        self._trim_if_needed()
        self._schedule_flush()

    async def clear_transient_run_status(self) -> None:
        if self._closed:
            return
        self._stream.clear_transient_run_status()
        self._trim_if_needed()
        self._schedule_flush()

    @property
    def _buffer(self) -> str:
        return self._stream.buffer

    @_buffer.setter
    def _buffer(self, v: str) -> None:
        self._stream.buffer = v

    def _trim_if_needed(self) -> None:
        if len(self._buffer) > self._max_chars:
            self._buffer = (
                self._buffer[: self._max_chars - 80]
                + "\n\n_(truncated — output exceeded configured limit)_"
            )

    def _schedule_flush(self) -> None:
        if self._timer is not None:
            return
        loop = asyncio.get_event_loop()
        self._timer = loop.call_later(self._stream_ms / 1000, self._fire_flush)

    def _fire_flush(self) -> None:
        self._timer = None
        asyncio.ensure_future(self.flush())

    async def flush(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._closed:
            return
        try:
            latest = await self._api.get_post(self._post.id)
            latest.message = self._buffer
            self._post = await self._api.update_post(latest)
        except Exception:
            # post may have been deleted
            pass

    async def close(self, final_message: str | None = None) -> None:
        self._closed = True
        if final_message is None:
            await self.finalize_assistant()
        else:
            self._buffer = final_message
        await self.flush()
