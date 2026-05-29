"""Tracks replaceable regions in a growing Mattermost post buffer (port of stream-buffer.ts)."""
from __future__ import annotations

import re

from ..cursor.run_status import (
    SdkRunStatus,
    format_run_status_line,
    is_transient_run_status_line,
    should_clear_run_status_line,
)
from ..cursor.tool_markdown import format_tool_completed, format_tool_running
from .buffer_region import (
    BufferRegion,
    replace_buffer_region,
    shift_region,
    shift_regions_after,
)
from .message_format import format_mattermost_assistant_text, merge_assistant_stream_text

_THINKING_PLACEHOLDER = re.compile(r"^_Thinking[.…]+_$")
_NEWLINES = re.compile(r"\n+")


class MattermostStreamBuffer:
    def __init__(self, buffer: str = "") -> None:
        self.buffer = buffer
        self._assistant_raw = ""
        self._assistant_region: BufferRegion | None = None
        self._thinking_region: BufferRegion | None = None
        self._tool_ranges: dict[str, BufferRegion] = {}
        self._status_region: BufferRegion | None = None

    def _clear_thinking_placeholder(self) -> None:
        if _THINKING_PLACEHOLDER.match(self.buffer.strip()):
            self.buffer = ""

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self.buffer += chunk

    def update_assistant(self, incoming: str) -> None:
        self._clear_thinking_placeholder()
        self._assistant_raw = merge_assistant_stream_text(self._assistant_raw, incoming)
        self._replace_assistant_region(format_mattermost_assistant_text(self._assistant_raw))

    def update_thinking(self, text: str) -> None:
        self._clear_thinking_placeholder()
        trimmed = text.strip()
        display = f"_{_NEWLINES.sub(' ', trimmed)}_" if trimmed else ""
        self._replace_thinking_region(display)

    def finalize_assistant(self) -> None:
        if not self._assistant_raw:
            return
        self._replace_assistant_region(format_mattermost_assistant_text(self._assistant_raw))

    def update_tool_call(self, call_id: str, name: str, status: str) -> None:
        if status == "running":
            self._clear_thinking_placeholder()
            line = format_tool_running(name)
            start = len(self.buffer)
            self.buffer += line
            self._tool_ranges[call_id] = BufferRegion(start=start, length=len(line))
            return
        line = format_tool_completed(name, status)
        rng = self._tool_ranges.get(call_id)
        if rng:
            pivot = rng.start
            self.buffer = self.buffer[: rng.start] + line + self.buffer[rng.start + rng.length :]
            delta = len(line) - rng.length
            del self._tool_ranges[call_id]
            self._tool_ranges[call_id] = BufferRegion(start=rng.start, length=len(line))
            self._shift_all_except_tools(pivot, delta)
        else:
            self.append(line)

    def update_run_status(self, status: str, message: str | None = None) -> None:
        if should_clear_run_status_line(status):
            self.clear_transient_run_status()
            return
        line = format_run_status_line(status, message)
        if self._status_region:
            pivot = self._status_region.start
            length = self._status_region.length
            self.buffer = self.buffer[:pivot] + line + self.buffer[pivot + length :]
            delta = len(line) - length
            self._status_region = BufferRegion(start=pivot, length=len(line))
            self._shift_all_except_status(pivot, delta)
        else:
            start = len(self.buffer)
            self.buffer += line
            self._status_region = BufferRegion(start=start, length=len(line))

    def clear_transient_run_status(self) -> None:
        if not self._status_region:
            return
        line = self.buffer[
            self._status_region.start : self._status_region.start + self._status_region.length
        ]
        if not is_transient_run_status_line(line):
            return
        start = self._status_region.start
        length = self._status_region.length
        self.buffer = self.buffer[:start] + self.buffer[start + length :]
        self._status_region = None
        self._shift_all_except_status(start, -length)

    def _replace_assistant_region(self, content: str) -> None:
        pivot = self._assistant_region.start if self._assistant_region else len(self.buffer)
        result = replace_buffer_region(self.buffer, self._assistant_region, content)
        self.buffer = result.buffer
        self._assistant_region = result.region
        self._shift_all_except_assistant(pivot, result.delta)

    def _replace_thinking_region(self, content: str) -> None:
        pivot = self._thinking_region.start if self._thinking_region else len(self.buffer)
        result = replace_buffer_region(self.buffer, self._thinking_region, content)
        self.buffer = result.buffer
        self._thinking_region = result.region
        self._shift_all_except_thinking(pivot, result.delta)

    def _shift_all_except_assistant(self, pivot: int, delta: int) -> None:
        self._thinking_region = shift_region(self._thinking_region, pivot, delta)
        shift_regions_after(self._tool_ranges, pivot, delta)
        self._status_region = shift_region(self._status_region, pivot, delta)

    def _shift_all_except_thinking(self, pivot: int, delta: int) -> None:
        self._assistant_region = shift_region(self._assistant_region, pivot, delta)
        shift_regions_after(self._tool_ranges, pivot, delta)
        self._status_region = shift_region(self._status_region, pivot, delta)

    def _shift_all_except_tools(self, pivot: int, delta: int) -> None:
        self._assistant_region = shift_region(self._assistant_region, pivot, delta)
        self._thinking_region = shift_region(self._thinking_region, pivot, delta)
        shift_regions_after(self._tool_ranges, pivot, delta)
        self._status_region = shift_region(self._status_region, pivot, delta)

    def _shift_all_except_status(self, pivot: int, delta: int) -> None:
        self._assistant_region = shift_region(self._assistant_region, pivot, delta)
        self._thinking_region = shift_region(self._thinking_region, pivot, delta)
        shift_regions_after(self._tool_ranges, pivot, delta)


__all__ = ["MattermostStreamBuffer", "SdkRunStatus"]
