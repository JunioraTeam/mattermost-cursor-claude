"""Wrap ClaudeSDKClient as a Cursor-shaped agent/run pair.

The Mattermost and OpenAI dispatchers consume a provider-neutral event stream:
each event has a ``type`` of ``assistant`` / ``thinking`` / ``tool_call`` /
``status`` / ``task`` / ``request`` plus a few duck-typed attributes (see
``cursor/stream_sink.py``). This module translates Claude Agent SDK messages into
those events, and exposes the ``agent.send → run.messages()/.wait()`` surface the
runners expect.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeSDKClient,
    ResultMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions

    from ..util.logger import Logger


# --- neutral stream events (match cursor/stream_sink.py duck typing) ------------


@dataclass
class _TextPart:
    text: str
    type: str = "text"


@dataclass
class _AssistantMessageBox:
    content: list[_TextPart]


@dataclass
class _AssistantEvent:
    message: _AssistantMessageBox
    type: str = "assistant"


@dataclass
class _ThinkingEvent:
    text: str
    type: str = "thinking"


@dataclass
class _ToolCallEvent:
    call_id: str
    name: str
    status: str  # "running" | "completed" | "error"
    type: str = "tool_call"


# --- run result (matches cursor RunResult duck typing) --------------------------


@dataclass
class ClaudeRunResult:
    status: str  # "finished" | "error" | "cancelled"
    result: str
    git: Any = None


# --- run --------------------------------------------------------------------


class ClaudeRun:
    """One assistant response for a single ``send``."""

    def __init__(self, client: ClaudeSDKClient, log: "Logger") -> None:
        self._client = client
        self._log = log
        self.run_id = uuid.uuid4().hex
        self._session_id: str | None = None
        self._result: ResultMessage | None = None
        self._cancelled = False
        self._tool_names: dict[str, str] = {}
        self._assistant_acc = ""

    @property
    def agent_id(self) -> str | None:
        return self._session_id

    def supports(self, op: str) -> bool:
        return op == "cancel"

    async def cancel(self) -> None:
        self._cancelled = True
        try:
            await self._client.interrupt()
        except Exception as e:
            self._log.error("Claude interrupt failed", err=str(e))

    async def messages(self) -> AsyncIterator[Any]:
        async for msg in self._client.receive_response():
            sid = getattr(msg, "session_id", None)
            if sid:
                self._session_id = sid

            if isinstance(msg, AssistantMessage):
                for ev in self._from_assistant(msg):
                    yield ev
            elif isinstance(msg, UserMessage):
                for ev in self._from_user(msg):
                    yield ev
            elif isinstance(msg, ResultMessage):
                self._result = msg
            # SystemMessage / StreamEvent / RateLimitEvent: not surfaced.

    def _from_assistant(self, msg: AssistantMessage) -> list[Any]:
        events: list[Any] = []
        content = msg.content if isinstance(msg.content, list) else []
        for block in content:
            if isinstance(block, TextBlock):
                if block.text:
                    self._assistant_acc = (
                        f"{self._assistant_acc}\n\n{block.text}"
                        if self._assistant_acc
                        else block.text
                    )
                    events.append(
                        _AssistantEvent(_AssistantMessageBox([_TextPart(self._assistant_acc)]))
                    )
            elif isinstance(block, ThinkingBlock):
                if block.thinking:
                    events.append(_ThinkingEvent(block.thinking))
            elif isinstance(block, ToolUseBlock):
                self._tool_names[block.id] = block.name
                events.append(_ToolCallEvent(block.id, block.name, "running"))
        return events

    def _from_user(self, msg: UserMessage) -> list[Any]:
        events: list[Any] = []
        content = msg.content if isinstance(msg.content, list) else []
        for block in content:
            if isinstance(block, ToolResultBlock):
                name = self._tool_names.get(block.tool_use_id, "tool")
                status = "error" if block.is_error else "completed"
                events.append(_ToolCallEvent(block.tool_use_id, name, status))
        return events

    async def wait(self) -> ClaudeRunResult:
        if self._cancelled:
            return ClaudeRunResult(status="cancelled", result="cancelled")
        r = self._result
        if r is None:
            return ClaudeRunResult(status="error", result="no result")
        if r.is_error or r.subtype != "success":
            return ClaudeRunResult(status="error", result=r.result or r.subtype)
        return ClaudeRunResult(status="finished", result=r.result or "finished")


# --- agent session ----------------------------------------------------------


@dataclass
class ClaudeAgentSession:
    """A persistent Claude Code conversation; ``send`` issues one turn."""

    options: "ClaudeAgentOptions"
    log: "Logger"
    _client: ClaudeSDKClient = field(init=False)
    agent_id: str | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._client = ClaudeSDKClient(self.options)

    async def connect(self) -> None:
        await self._client.connect()

    async def send(self, text: str, opts: Any = None) -> ClaudeRun:
        # opts (mcp_servers) are fixed at connect time for Claude; accepted for parity.
        await self._client.query(text)
        return ClaudeRun(self._client, self.log)

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception as e:
            self.log.error("Claude disconnect failed", err=str(e))
