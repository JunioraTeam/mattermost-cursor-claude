"""Mattermost data types (port of mattermost/types.ts).

These mirror the JSON shapes returned by the Mattermost REST/WS APIs. We keep
them as light dataclasses with ``from_json`` helpers so the rest of the code can
use attribute access while still round-tripping to plain dicts for the REST API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MattermostPost:
    id: str = ""
    channel_id: str = ""
    user_id: str = ""
    message: str = ""
    root_id: str = ""
    parent_id: str | None = None
    props: dict[str, Any] | None = None
    type: str | None = None
    # Preserve any other server fields so updatePost round-trips the full post.
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "MattermostPost":
        known = {"id", "channel_id", "user_id", "message", "root_id", "parent_id", "props", "type"}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            id=data.get("id", ""),
            channel_id=data.get("channel_id", ""),
            user_id=data.get("user_id", ""),
            message=data.get("message", ""),
            root_id=data.get("root_id", ""),
            parent_id=data.get("parent_id"),
            props=data.get("props"),
            type=data.get("type"),
            extra=extra,
        )

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = dict(self.extra)
        out.update(
            {
                "id": self.id,
                "channel_id": self.channel_id,
                "user_id": self.user_id,
                "message": self.message,
                "root_id": self.root_id,
            }
        )
        if self.parent_id is not None:
            out["parent_id"] = self.parent_id
        if self.props is not None:
            out["props"] = self.props
        if self.type is not None:
            out["type"] = self.type
        return out


@dataclass
class MattermostUser:
    id: str
    username: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "MattermostUser":
        return cls(id=data.get("id", ""), username=data.get("username", ""))


@dataclass
class PostThreadResponse:
    order: list[str]
    posts: dict[str, MattermostPost]

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "PostThreadResponse":
        posts = {pid: MattermostPost.from_json(p) for pid, p in (data.get("posts") or {}).items()}
        return cls(order=list(data.get("order") or []), posts=posts)
