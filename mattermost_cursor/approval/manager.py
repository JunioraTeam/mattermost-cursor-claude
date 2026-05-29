"""Temporary approval tokens with timeout (port of approval/manager.ts)."""
from __future__ import annotations

import asyncio
import secrets
from typing import TYPE_CHECKING, Awaitable

if TYPE_CHECKING:
    from ..util.logger import Logger


class _Pending:
    __slots__ = ("future", "timer")

    def __init__(self, future: "asyncio.Future[bool]", timer: asyncio.TimerHandle) -> None:
        self.future = future
        self.timer = timer


class ApprovalManager:
    def __init__(self, log: "Logger") -> None:
        self._log = log
        self._pending: dict[str, _Pending] = {}

    def create_waiter(self, timeout_ms: int) -> tuple[str, "Awaitable[bool]"]:
        token = secrets.token_hex(10)
        loop = asyncio.get_event_loop()
        future: asyncio.Future[bool] = loop.create_future()

        def on_timeout() -> None:
            self._pending.pop(token, None)
            self._log.warning("Approval timed out", token=token)
            if not future.done():
                future.set_result(False)

        timer = loop.call_later(timeout_ms / 1000, on_timeout)
        self._pending[token] = _Pending(future, timer)
        return token, future

    def resolve(self, token: str, value: bool) -> bool:
        p = self._pending.get(token)
        if not p:
            return False
        p.timer.cancel()
        self._pending.pop(token, None)
        if not p.future.done():
            p.future.set_result(value)
        return True
