"""Cursor run status helpers (port of cursor/run-status.ts)."""
from __future__ import annotations

import re
from typing import Literal, Mapping

SdkRunStatus = Literal["CREATING", "RUNNING", "FINISHED", "ERROR", "CANCELLED", "EXPIRED"]

_TRANSIENT_LINE = re.compile(r"_Status: (CREATING|RUNNING)\b")


def format_run_status_line(status: str, message: str | None = None) -> str:
    return f"\n_Status: {status}{f' — {message}' if message else ''}_\n"


def is_transient_run_status(status: str) -> bool:
    return status in ("CREATING", "RUNNING")


def should_clear_run_status_line(status: str) -> bool:
    return status == "FINISHED"


def is_transient_run_status_line(line: str) -> bool:
    return bool(_TRANSIENT_LINE.search(line))


def shift_ranges_after(ranges: Mapping[str, object], pivot: int, delta: int) -> None:
    if delta == 0:
        return
    for r in ranges.values():
        if getattr(r, "start") > pivot:  # noqa: B009
            r.start += delta  # type: ignore[attr-defined]
