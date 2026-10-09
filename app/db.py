from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.models import Base

_url = make_url(settings.database_url)
if _url.get_backend_name() == "sqlite" and _url.database not in (None, ":memory:"):
    Path(_url.database).parent.mkdir(parents=True, exist_ok=True)

engine: AsyncEngine = create_async_engine(settings.database_url, echo=False)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# (table, column, DDL type) added after the initial release. `create_all` never
# alters existing tables, so we apply these idempotently on startup.
_ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("users", "quota_bytes", "BIGINT"),
]


def _apply_added_columns(sync_conn) -> None:  # type: ignore[no-untyped-def]
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    for table, column, ddl_type in _ADDED_COLUMNS:
        if table not in existing_tables:
            continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in columns:
            sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_apply_added_columns)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        yield session
