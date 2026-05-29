"""Post text helpers: mention stripping, command parsing (port of mattermost/post-utils.ts)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_BRACKET_MENTION = re.compile(r"<@[^>]+>")
_APPROVAL = re.compile(r"^(approve|deny)\s+([a-z0-9]{8,})$", re.IGNORECASE)
_CANCEL_ID = re.compile(r"^cancel\s+([a-f0-9]{6,16})$", re.IGNORECASE)
_WS = re.compile(r"\s+")


def strip_mentions(message: str, bot_user_id: str, bot_username: str | None = None) -> str:
    """Remove Mattermost @mention tokens like ``<@userid>`` and plain @username."""
    m = _BRACKET_MENTION.sub("", message)
    m = m.replace(f"@{bot_user_id}", "")
    if bot_username:
        m = re.sub(rf"@{re.escape(bot_username)}\b", "", m, flags=re.IGNORECASE)
    m = _WS.sub(" ", m).strip()
    return m


@dataclass
class ApprovalToken:
    kind: str  # "approve" | "deny"
    token: str


def is_approval_token(text: str) -> ApprovalToken | None:
    a = _APPROVAL.match(text)
    if not a:
        return None
    kind = "approve" if a.group(1).lower() == "approve" else "deny"
    return ApprovalToken(kind=kind, token=a.group(2))


@dataclass
class CancelCommand:
    kind: str  # "queue" | "run" | "id"
    id: str | None = None


def parse_cancel_command(text: str) -> CancelCommand | None:
    """cancel queue | cancel all | cancel run | cancel <queue-id>"""
    m = text.strip().lower()
    if m in ("cancel queue", "cancel all"):
        return CancelCommand(kind="queue")
    if m == "cancel run":
        return CancelCommand(kind="run")
    found = _CANCEL_ID.match(text.strip())
    if found:
        return CancelCommand(kind="id", id=found.group(1).lower())
    return None


def is_queue_status_command(text: str) -> bool:
    return text.strip().lower() == "queue"


def truncate_for_post(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 60] + "\n\n_(truncated)_"
