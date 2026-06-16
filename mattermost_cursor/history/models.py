"""SQLAlchemy 2.0 declarative models for the persistent history backend.

Design notes:
- Timestamps are stored as ISO-8601 **strings** (VARCHAR), matching the in-memory
  store byte-for-byte so panel JSON is identical across backends.
- Ordering never relies on string comparison: ``runs.seq`` and ``user_events.id``
  are autoincrement integer PKs that mirror the in-memory "insert at index 0"
  newest-first semantics (highest id == newest).
- ``runs.id`` (uuid) stays a unique-indexed column for update/finish lookups.
- Text columns (preview/detail) use ``Text`` and tables should be utf8mb4 — the
  ``…`` truncation marker and emoji must round-trip.
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# BIGINT on MariaDB/Postgres, but SQLite only autoincrements INTEGER PRIMARY KEY
# (its rowid alias), so fall back to INTEGER there.
_AutoBigInt = BigInteger().with_variant(Integer, "sqlite")


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    seq: Mapped[int] = mapped_column(_AutoBigInt, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[str] = mapped_column(String(40))
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    message_preview: Mapped[str] = mapped_column(Text)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thread_key: Mapped[str | None] = mapped_column(String(160), index=True, nullable=True)
    queue_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    cursor_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reply_post_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserRow(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_seen_at: Mapped[str] = mapped_column(String(40))
    last_seen_at: Mapped[str] = mapped_column(String(40), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)

    events: Mapped[list["UserEventRow"]] = relationship(
        back_populates="user",
        order_by="UserEventRow.id.desc()",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class UserEventRow(Base):
    __tablename__ = "user_events"

    id: Mapped[int] = mapped_column(_AutoBigInt, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.user_id", ondelete="CASCADE"), index=True
    )
    at: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(24))
    channel_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thread_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    preview: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["UserRow"] = relationship(back_populates="events")


class ThreadSessionRow(Base):
    __tablename__ = "thread_sessions"

    thread_key: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider: Mapped[str] = mapped_column(String(16))
    resume_token: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
