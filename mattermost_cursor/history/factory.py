"""Select and build the history store backend from configuration.

``DB_TYPE=memory`` (default) → in-memory store (no persistence, zero config).
Any other ``DB_TYPE`` → SQLAlchemy async engine + :class:`SqlHistoryStore`,
with tables created on startup via ``metadata.create_all`` (Alembic is future
work; ``create_all`` only creates missing tables, never alters existing ones).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import HistoryStore
from .store import InMemoryHistoryStore

if TYPE_CHECKING:
    from ..config import AppEnv
    from ..util.logger import Logger


async def create_history_store(env: "AppEnv", log: "Logger") -> HistoryStore:
    url = env.database_url()
    if url is None:
        log.info("History store: in-memory (set DB_TYPE to persist)")
        return InMemoryHistoryStore()

    # Imported lazily so the SQLAlchemy/driver deps are only needed when used.
    from sqlalchemy.ext.asyncio import create_async_engine

    from .models import Base
    from .sql_store import SqlHistoryStore

    engine = create_async_engine(url, pool_pre_ping=True, echo=env.DB_ECHO)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info(
        "History store: database",
        backend=env.DB_TYPE,
        host=env.DB_HOST,
        database=env.DB_NAME or env.DB_SQLITE_PATH,
    )
    return SqlHistoryStore(engine, log)
