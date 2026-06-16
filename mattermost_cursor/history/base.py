"""Async ``HistoryStore`` interface.

The in-memory and SQL-backed stores both implement this. All methods are async
so the SQL backend can do real I/O; the in-memory backend just declares them
async with synchronous bodies. Reads return the same camelCase dict shape the
panel UI and OpenAI API consume (see ``history/types.py``).
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from .types import RunSource, RunStatus, UserEventType


class HistoryStore(ABC):
    # --- run lifecycle ------------------------------------------------------

    @abstractmethod
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
    ) -> str: ...

    @abstractmethod
    async def update_run(
        self,
        run_id: str,
        *,
        status: RunStatus | None = None,
        cursorRunId: str | None = None,
        agentId: str | None = None,
        replyPostId: str | None = None,
        username: str | None = None,
    ) -> None: ...

    @abstractmethod
    async def finish_run(
        self, run_id: str, *, ok: bool, detail: str, status: RunStatus | None = None,
    ) -> None: ...

    # --- user activity ------------------------------------------------------

    @abstractmethod
    async def record_user_event(
        self,
        *,
        userId: str,
        type: UserEventType,
        username: str | None = None,
        channelId: str | None = None,
        threadKey: str | None = None,
        preview: str | None = None,
    ) -> None: ...

    # --- queue cancellation -------------------------------------------------

    @abstractmethod
    async def cancel_queued_by_queue_id(self, queue_id: str) -> bool: ...

    @abstractmethod
    async def cancel_all_queued(self) -> int: ...

    # --- reads (panel + openai api) ----------------------------------------

    @abstractmethod
    async def list_runs(self, limit: int = 100) -> list[dict]: ...

    @abstractmethod
    async def list_users(self) -> list[dict]: ...

    # --- agent resume tokens (per Mattermost thread) ------------------------

    @abstractmethod
    async def get_thread_session(self, thread_key: str) -> dict | None:
        """Return ``{"threadKey","provider","resumeToken","model",...}`` or None."""
        ...

    @abstractmethod
    async def save_thread_session(
        self,
        *,
        thread_key: str,
        provider: str,
        resume_token: str,
        model: str | None = None,
    ) -> None: ...

    @abstractmethod
    async def delete_thread_session(self, thread_key: str) -> None: ...

    # --- lifecycle ----------------------------------------------------------

    @abstractmethod
    async def aclose(self) -> None:
        """Release any backend resources (e.g. dispose the DB engine pool)."""
        ...
