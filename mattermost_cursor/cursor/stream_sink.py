"""Routes Cursor SDK stream messages to a sink (Mattermost post or OpenAI buffer).

Port of cursor/stream-sink.ts. All sink methods are async so the dispatcher can
``await`` them uniformly and the OpenAI SSE sink can write to the aiohttp response.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable, Protocol, runtime_checkable

from ..mattermost.stream_buffer import MattermostStreamBuffer
from .run_status import is_transient_run_status, should_clear_run_status_line

if TYPE_CHECKING:
    from ..approval.manager import ApprovalManager
    from ..config import AppEnv
    from ..util.logger import Logger


@runtime_checkable
class StreamSink(Protocol):
    """Where Cursor run stream events are written."""

    async def append(self, chunk: str) -> None: ...
    async def update_assistant(self, text: str) -> None: ...
    async def update_thinking(self, text: str) -> None: ...
    async def finalize_assistant(self) -> None: ...
    async def update_tool_call(self, call_id: str, name: str, status: str) -> None: ...
    async def update_run_status(self, status: str, message: str | None = None) -> None: ...
    async def clear_transient_run_status(self) -> None: ...
    async def flush(self) -> None: ...


def _assistant_to_markdown(msg: Any) -> str:
    out = ""
    for block in msg.message.content:
        if getattr(block, "type", None) == "text":
            out += block.text
    return out


async def dispatch_stream_event(
    event: Any,
    *,
    sink: StreamSink,
    approvals: "ApprovalManager",
    agent: Any,
    mcp_servers: dict[str, Any],
    env: "AppEnv",
    log: "Logger",
    run: Any,
    auto_approve_requests: bool = False,
) -> None:
    etype = getattr(event, "type", None)

    if etype == "assistant":
        md = _assistant_to_markdown(event)
        if md:
            await sink.update_assistant(md)
        return

    if etype == "thinking":
        if event.text:
            await sink.update_thinking(event.text)
        return

    if etype == "tool_call":
        await sink.update_tool_call(event.call_id, event.name, event.status)
        return

    if etype == "status":
        await sink.update_run_status(event.status, event.message)
        return

    if etype == "task":
        if event.text:
            await sink.append(f"\n\n**Task:** {event.text}")
        return

    if etype == "request":
        if auto_approve_requests:
            await sink.append("\n\n_Auto-approved interactive request._")
            try:
                follow_opts = {"mcp_servers": mcp_servers} if mcp_servers else None
                await agent.send(
                    f"Auto-approved interactive request {event.request_id}. Proceed.",
                    follow_opts,
                )
            except Exception as e:
                log.error("Follow-up send after auto-approval failed", err=str(e))
            return

        token, approved = approvals.create_waiter(env.APPROVAL_TIMEOUT_MS)
        await sink.append(
            f"\n\n---\n### Human approval required\nThe agent is waiting for confirmation "
            f"(request `{event.request_id}`).\n\nReply in this thread: **approve {token}** or "
            f"**deny {token}**.\n"
        )
        await sink.flush()
        ok = await approved
        if not ok:
            if run.supports("cancel"):
                await run.cancel()
            await sink.append("\n\n_Stopped after deny or timeout._")
            return
        await sink.append("\n\n_Approved — continuing…_")
        try:
            follow_opts = {"mcp_servers": mcp_servers} if mcp_servers else None
            await agent.send(
                f"Mattermost user approved interactive request {event.request_id} "
                f"(token {token}). Proceed.",
                follow_opts,
            )
        except Exception as e:
            log.error("Follow-up send after approval failed", err=str(e))
            await sink.append(f"\n\n_Failed to continue after approval: {e}_")
        return


class TextBufferSink:
    """In-memory buffer for OpenAI SSE streaming."""

    def __init__(self, on_delta: Callable[[str], Awaitable[None]]) -> None:
        self._stream = MattermostStreamBuffer()
        self._on_delta = on_delta

    @property
    def text(self) -> str:
        return self._stream.buffer

    async def _sync(self) -> None:
        await self._on_delta(self._stream.buffer)

    async def append(self, chunk: str) -> None:
        self._stream.append(chunk)
        await self._sync()

    async def update_assistant(self, incoming: str) -> None:
        self._stream.update_assistant(incoming)
        await self._sync()

    async def update_thinking(self, text: str) -> None:
        self._stream.update_thinking(text)
        await self._sync()

    async def finalize_assistant(self) -> None:
        self._stream.finalize_assistant()
        await self._sync()

    async def update_run_status(self, status: str, message: str | None = None) -> None:
        if should_clear_run_status_line(status) or is_transient_run_status(status):
            return
        self._stream.update_run_status(status, message)
        await self._sync()

    async def clear_transient_run_status(self) -> None:
        """Transient status is never written to the OpenAI stream buffer."""
        return

    async def update_tool_call(self, call_id: str, name: str, status: str) -> None:
        self._stream.update_tool_call(call_id, name, status)
        await self._sync()

    async def flush(self) -> None:
        return
