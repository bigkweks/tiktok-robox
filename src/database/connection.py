from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import get_settings
from src.database.models import Base

log = structlog.get_logger(__name__)

_engine = None
_session_factory = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        if "sqlite" in str(engine.url):
            from sqlalchemy import text
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
            await conn.execute(text("PRAGMA cache_size=10000"))
            await conn.execute(text("PRAGMA temp_store=MEMORY"))
        await conn.run_sync(Base.metadata.create_all)
        # Migrate: add new columns to existing tables if they don't exist yet
        if "sqlite" in str(engine.url):
            await _sqlite_add_column_if_missing(conn, "content", "carousel_caption", "TEXT")
            await _sqlite_add_column_if_missing(conn, "content", "used_fallback", "BOOLEAN DEFAULT 0")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "review_score", "FLOAT")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "review_summary", "TEXT")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "cover_hook", "TEXT")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "slide_captions", "TEXT")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "generation_id", "VARCHAR(40)")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "min_game_rating", "FLOAT")
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "exported_at", "DATETIME")
            await _sqlite_add_column_if_missing(conn, "games", "times_carouseled", "INTEGER DEFAULT 0")
            await _sqlite_add_column_if_missing(conn, "games", "last_carouseled_at", "DATETIME")
            # Multi-account support: account_id on carousel_posts
            await _sqlite_add_column_if_missing(conn, "carousel_posts", "account_id", "INTEGER REFERENCES accounts(id)")
    log.info("database.initialized")


async def _sqlite_add_column_if_missing(conn, table: str, column: str, col_type: str) -> None:
    from sqlalchemy import text
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    cols = {row[1] for row in result.fetchall()}
    if column not in cols:
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        log.info("database.column_added", table=table, column=column)


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        log.info("database.closed")
