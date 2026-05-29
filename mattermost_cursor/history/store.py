"""In-memory run + user activity store (port of history/store.ts)."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from .types import RunRecord, RunSource, RunStatus, UserEvent, UserEventType, UserRecord

MAX_RUNS = 500
MAX_EVENTS_PER_USER = 100
_WS = re.compile(r"\s+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truncate(text: str, max_len: int) -> str:
    t = _WS.sub(" ", text).strip()
    if len(t) <= max_len:
        return t
    return f"{t[: max_len - 1]}…"


class HistoryStore:
    def __init__(self) -> None:
        self._runs: list[RunRecord] = []
        self._users: dict[str, UserRecord] = {}

    def start_run(
        self,
        *,
        source: RunSource,
        userId: str,
        messagePreview: str,
        username: str | None = None,
        channelId: str | None = None,
        threadKey: str | None = None,
        queueId: str | None = None,
        status: RunStatus | None = None,
    ) -> str:
        run_id = str(uuid.uuid4())
        record = RunRecord(
            id=run_id,
            status=status or "running",
            source=source,
            startedAt=_now(),
            userId=userId,
            username=username,
            channelId=channelId,
            threadKey=threadKey,
            messagePreview=_truncate(messagePreview, 240),
            queueId=queueId,
        )
        self._runs.insert(0, record)
        if len(self._runs) > MAX_RUNS:
            del self._runs[MAX_RUNS:]
        return run_id

    def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        cursorRunId: str | None = None,
        agentId: str | None = None,
        replyPostId: str | None = None,
        username: str | None = None,
    ) -> None:
        run = next((r for r in self._runs if r.id == run_id), None)
        if not run:
            return
        if status is not None:
            run.status = status
        if cursorRunId is not None:
            run.cursorRunId = cursorRunId
        if agentId is not None:
            run.agentId = agentId
        if replyPostId is not None:
            run.replyPostId = replyPostId
        if username is not None:
            run.username = username

    def finish_run(
        self, run_id: str, *, ok: bool, detail: str, status: RunStatus | None = None,
    ) -> None:
        run = next((r for r in self._runs if r.id == run_id), None)
        if not run:
            return
        run.finishedAt = _now()
        run.ok = ok
        run.detail = _truncate(detail, 500)
        run.status = status or (
            "completed" if ok else "cancelled" if detail == "cancelled" else "error"
        )

    def record_user_event(
        self,
        *,
        userId: str,
        type: UserEventType,
        username: str | None = None,
        channelId: str | None = None,
        threadKey: str | None = None,
        preview: str | None = None,
    ) -> None:
        now = _now()
        user = self._users.get(userId)
        if not user:
            user = UserRecord(
                userId=userId,
                username=username,
                firstSeenAt=now,
                lastSeenAt=now,
                messageCount=0,
                events=[],
            )
            self._users[userId] = user
        if username:
            user.username = username
        user.lastSeenAt = now
        if type == "message":
            user.messageCount += 1

        event = UserEvent(
            at=now,
            type=type,
            channelId=channelId,
            threadKey=threadKey,
            preview=_truncate(preview, 200) if preview else None,
        )
        user.events.insert(0, event)
        if len(user.events) > MAX_EVENTS_PER_USER:
            del user.events[MAX_EVENTS_PER_USER:]

    def cancel_queued_by_queue_id(self, queue_id: str) -> bool:
        run = next(
            (r for r in self._runs if r.queueId == queue_id and r.status == "queued"), None
        )
        if not run:
            return False
        run.status = "cancelled"
        run.finishedAt = _now()
        run.ok = False
        run.detail = "removed from queue"
        return True

    def cancel_all_queued(self) -> int:
        n = 0
        for run in self._runs:
            if run.status != "queued":
                continue
            run.status = "cancelled"
            run.finishedAt = _now()
            run.ok = False
            run.detail = "removed from queue"
            n += 1
        return n

    def list_runs(self, limit: int = 100) -> list[dict]:
        return [r.to_dict() for r in self._runs[:limit]]

    def list_users(self) -> list[dict]:
        users = sorted(
            self._users.values(),
            key=lambda u: u.lastSeenAt,
            reverse=True,
        )
        return [u.to_dict() for u in users]
