"""SQLAlchemy 2.0 async implementation of :class:`HistoryStore`.

Reads rebuild the ``RunRecord`` / ``UserRecord`` / ``UserEvent`` dataclasses and
call their ``.to_dict()``, so the camelCase JSON contract is identical to the
in-memory store regardless of DB backend.
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from .base import HistoryStore
from .models import RunRow, ThreadSessionRow, UserEventRow, UserRow
from .store import MAX_EVENTS_PER_USER, MAX_RUNS, _now, _truncate
from .types import RunRecord, RunSource, RunStatus, UserEvent, UserEventType, UserRecord

if TYPE_CHECKING:
    from ..util.logger import Logger


def _run_to_record(row: RunRow) -> RunRecord:
    return RunRecord(
        id=row.id,
        status=row.status,  # type: ignore[arg-type]
        source=row.source,  # type: ignore[arg-type]
        startedAt=row.started_at,
        userId=row.user_id,
        messagePreview=row.message_preview,
        cursorRunId=row.cursor_run_id,
        queueId=row.queue_id,
        agentId=row.agent_id,
        ok=row.ok,
        finishedAt=row.finished_at,
        username=row.username,
        channelId=row.channel_id,
        threadKey=row.thread_key,
        detail=row.detail,
        replyPostId=row.reply_post_id,
    )


def _user_to_record(row: UserRow) -> UserRecord:
    events = [
        UserEvent(
            at=e.at,
            type=e.type,  # type: ignore[arg-type]
            channelId=e.channel_id,
            threadKey=e.thread_key,
            preview=e.preview,
        )
        for e in row.events[:MAX_EVENTS_PER_USER]
    ]
    return UserRecord(
        userId=row.user_id,
        firstSeenAt=row.first_seen_at,
        lastSeenAt=row.last_seen_at,
        messageCount=row.message_count,
        username=row.username,
        events=events,
    )


class SqlHistoryStore(HistoryStore):
    def __init__(self, engine: AsyncEngine, log: "Logger") -> None:
        self._engine = engine
        self._log = log
        self._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    # --- run lifecycle ------------------------------------------------------

    async def start_run(
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
        async with self._sessionmaker() as session:
            async with session.begin():
                session.add(
                    RunRow(
                        id=run_id,
                        status=status or "running",
                        source=source,
                        started_at=_now(),
                        user_id=userId,
                        username=username,
                        channel_id=channelId,
                        thread_key=threadKey,
                        message_preview=_truncate(messagePreview, 240),
                        queue_id=queueId,
                    )
                )
            await self._prune_runs(session)
        return run_id

    async def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        cursorRunId: str | None = None,
        agentId: str | None = None,
        replyPostId: str | None = None,
        username: str | None = None,
    ) -> None:
        values: dict[str, Any] = {}
        if status is not None:
            values["status"] = status
        if cursorRunId is not None:
            values["cursor_run_id"] = cursorRunId
        if agentId is not None:
            values["agent_id"] = agentId
        if replyPostId is not None:
            values["reply_post_id"] = replyPostId
        if username is not None:
            values["username"] = username
        if not values:
            return
        async with self._sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    update(RunRow).where(RunRow.id == run_id).values(**values)
                )

    async def finish_run(
        self, run_id: str, *, ok: bool, detail: str, status: RunStatus | None = None,
    ) -> None:
        final_status = status or (
            "completed" if ok else "cancelled" if detail == "cancelled" else "error"
        )
        async with self._sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    update(RunRow)
                    .where(RunRow.id == run_id)
                    .values(
                        finished_at=_now(),
                        ok=ok,
                        detail=_truncate(detail, 500),
                        status=final_status,
                    )
                )

    # --- user activity ------------------------------------------------------

    async def record_user_event(
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
        async with self._sessionmaker() as session:
            async with session.begin():
                user = await session.get(UserRow, userId)
                if user is None:
                    user = UserRow(
                        user_id=userId,
                        username=username,
                        first_seen_at=now,
                        last_seen_at=now,
                        message_count=0,
                    )
                    session.add(user)
                if username:
                    user.username = username
                user.last_seen_at = now
                if type == "message":
                    user.message_count = (user.message_count or 0) + 1
                session.add(
                    UserEventRow(
                        user_id=userId,
                        at=now,
                        type=type,
                        channel_id=channelId,
                        thread_key=threadKey,
                        preview=_truncate(preview, 200) if preview else None,
                    )
                )
            await self._prune_user_events(session, userId)

    # --- queue cancellation -------------------------------------------------

    async def cancel_queued_by_queue_id(self, queue_id: str) -> bool:
        async with self._sessionmaker() as session:
            async with session.begin():
                result = await session.execute(
                    update(RunRow)
                    .where(RunRow.queue_id == queue_id, RunRow.status == "queued")
                    .values(
                        status="cancelled",
                        finished_at=_now(),
                        ok=False,
                        detail="removed from queue",
                    )
                )
            return (result.rowcount or 0) > 0

    async def cancel_all_queued(self) -> int:
        async with self._sessionmaker() as session:
            async with session.begin():
                result = await session.execute(
                    update(RunRow)
                    .where(RunRow.status == "queued")
                    .values(
                        status="cancelled",
                        finished_at=_now(),
                        ok=False,
                        detail="removed from queue",
                    )
                )
            return result.rowcount or 0

    # --- reads --------------------------------------------------------------

    async def list_runs(self, limit: int = 100) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(RunRow).order_by(RunRow.seq.desc()).limit(limit)
                )
            ).scalars().all()
            return [_run_to_record(r).to_dict() for r in rows]

    async def list_users(self) -> list[dict]:
        async with self._sessionmaker() as session:
            rows = (
                await session.execute(
                    select(UserRow).order_by(UserRow.last_seen_at.desc())
                )
            ).scalars().all()
            return [_user_to_record(u).to_dict() for u in rows]

    # --- agent resume tokens ------------------------------------------------

    async def get_thread_session(self, thread_key: str) -> dict | None:
        async with self._sessionmaker() as session:
            row = await session.get(ThreadSessionRow, thread_key)
            if row is None:
                return None
            return {
                "threadKey": row.thread_key,
                "provider": row.provider,
                "resumeToken": row.resume_token,
                "model": row.model,
                "createdAt": row.created_at,
                "updatedAt": row.updated_at,
            }

    async def save_thread_session(
        self,
        *,
        thread_key: str,
        provider: str,
        resume_token: str,
        model: str | None = None,
    ) -> None:
        now = _now()
        async with self._sessionmaker() as session:
            async with session.begin():
                row = await session.get(ThreadSessionRow, thread_key)
                if row is None:
                    session.add(
                        ThreadSessionRow(
                            thread_key=thread_key,
                            provider=provider,
                            resume_token=resume_token,
                            model=model,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                else:
                    row.provider = provider
                    row.resume_token = resume_token
                    row.model = model
                    row.updated_at = now

    async def delete_thread_session(self, thread_key: str) -> None:
        async with self._sessionmaker() as session:
            async with session.begin():
                await session.execute(
                    delete(ThreadSessionRow).where(
                        ThreadSessionRow.thread_key == thread_key
                    )
                )

    # --- lifecycle ----------------------------------------------------------

    async def aclose(self) -> None:
        await self._engine.dispose()

    # --- pruning helpers (mirror the in-memory caps) ------------------------

    async def _prune_runs(self, session: Any) -> None:
        """Keep only the newest MAX_RUNS rows (bounds table growth)."""
        async with session.begin():
            threshold = (
                await session.execute(
                    select(RunRow.seq).order_by(RunRow.seq.desc()).limit(1).offset(MAX_RUNS)
                )
            ).scalar_one_or_none()
            if threshold is not None:
                await session.execute(delete(RunRow).where(RunRow.seq <= threshold))

    async def _prune_user_events(self, session: Any, user_id: str) -> None:
        async with session.begin():
            threshold = (
                await session.execute(
                    select(UserEventRow.id)
                    .where(UserEventRow.user_id == user_id)
                    .order_by(UserEventRow.id.desc())
                    .limit(1)
                    .offset(MAX_EVENTS_PER_USER)
                )
            ).scalar_one_or_none()
            if threshold is not None:
                await session.execute(
                    delete(UserEventRow).where(
                        UserEventRow.user_id == user_id, UserEventRow.id <= threshold
                    )
                )
