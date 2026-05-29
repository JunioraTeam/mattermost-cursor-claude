"""History record types (port of history/types.ts).

Field names are camelCase to match the JSON the admin panel UI consumes verbatim.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

RunSource = Literal["mattermost", "openai"]
RunStatus = Literal["queued", "running", "completed", "error", "cancelled"]
UserEventType = Literal["message", "approval", "cancel", "reset_session", "queue"]


def _clean(d: dict[str, Any]) -> dict[str, Any]:
    """Drop None values so optional fields are omitted from JSON (TS undefined parity)."""
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class UserEvent:
    at: str
    type: UserEventType
    channelId: str | None = None
    threadKey: str | None = None
    preview: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))


@dataclass
class UserRecord:
    userId: str
    firstSeenAt: str
    lastSeenAt: str
    messageCount: int = 0
    username: str | None = None
    events: list[UserEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = _clean(asdict(self))
        d["events"] = [e.to_dict() for e in self.events]
        return d


@dataclass
class RunRecord:
    id: str
    status: RunStatus
    source: RunSource
    startedAt: str
    userId: str
    messagePreview: str
    cursorRunId: str | None = None
    queueId: str | None = None
    agentId: str | None = None
    ok: bool | None = None
    finishedAt: str | None = None
    username: str | None = None
    channelId: str | None = None
    threadKey: str | None = None
    detail: str | None = None
    replyPostId: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _clean(asdict(self))
