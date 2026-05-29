"""Replaceable-region bookkeeping for the streaming post buffer (port of buffer-region.ts)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import MutableMapping, NamedTuple


@dataclass
class BufferRegion:
    start: int
    length: int


def shift_regions_after(
    regions: MutableMapping[str, BufferRegion], pivot: int, delta: int,
) -> None:
    if delta == 0:
        return
    for r in regions.values():
        if r.start > pivot:
            r.start += delta


def shift_region(region: BufferRegion | None, pivot: int, delta: int) -> BufferRegion | None:
    if region is None or delta == 0:
        return region
    if region.start > pivot:
        return BufferRegion(start=region.start + delta, length=region.length)
    return region


class ReplaceResult(NamedTuple):
    buffer: str
    region: BufferRegion | None
    delta: int


def replace_buffer_region(
    buffer: str, region: BufferRegion | None, content: str,
) -> ReplaceResult:
    if region is None:
        if not content:
            return ReplaceResult(buffer, None, 0)
        start = len(buffer)
        prefix = "\n\n" if len(buffer) > 0 and not buffer.endswith("\n\n") else ""
        insert = prefix + content
        return ReplaceResult(
            buffer + insert,
            BufferRegion(start=start + len(prefix), length=len(content)),
            len(insert),
        )
    nxt = buffer[: region.start] + content + buffer[region.start + region.length :]
    delta = len(content) - region.length
    next_region = BufferRegion(start=region.start, length=len(content)) if content else None
    return ReplaceResult(nxt, next_region, delta)
