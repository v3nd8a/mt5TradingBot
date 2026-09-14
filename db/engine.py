"""Движок базы данных — SQLAlchemy + пул соединений."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session

from config.settings import settings, DB_SCHEMA_PATH
from db.models import Base

logger = logging.getLogger("db_logger")

# ==================== Sync engine (for Alembic / migrations) ====================

sync_engine = create_engine(settings.DB_DSN, pool_size=5, max_overflow=10)


def init_db() -> bool:
    """Создать таблицы из SQLAlchemy моделей."""
    try:
        Base.metadata.create_all(sync_engine)
        logger.info("Database tables initialized")
        return True
    except Exception as e:
        logger.warning(f"Database initialization deferred (PostgreSQL may be offline): {e}")
        return False


def _split_sql_statements(sql: str) -> list[str]:
    """Split raw SQL text into individual statements, respecting quotes and comments.

    Handles:
    - Single-quoted strings ('...'  can contain ';')
    - Double-quoted identifiers ("..." can contain ';')
    - -- line comments (everything after '--' on a line)
    - /* */ block comments (may span multiple lines)
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)

    while i < n:
        ch = sql[i]

        # -- line comment: skip to end of line
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue

        # /* */ block comment: skip to closing */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i < n - 1 and not (sql[i] == "*" and sql[i + 1] == "/"):
                i += 1
            i += 2  # skip */
            continue

        # single-quoted string literal
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'" and i + 1 < n and sql[i + 1] == "'":
                    current.append("''")  # escaped quote ''
                    i += 2
                elif sql[i] == "'":
                    i += 1
                    break
                else:
                    current.append(sql[i])
                    i += 1
            continue

        # double-quoted identifier / string
        if ch == '"':
            i += 1
            while i < n and sql[i] != '"':
                current.append(sql[i])
                i += 1
            if i < n:
                current.append('"')  # closing quote
                i += 1
            continue

        # semicolon — possible statement boundary
        if ch == ";":
            candidate = "".join(current).strip()
            if candidate:
                statements.append(candidate)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # trailing statement without semicolon
    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)

    return statements


def run_schema_migration() -> None:
    """Выполнить SQL schema файл если таблицы не существуют."""
    if not DB_SCHEMA_PATH.exists():
        logger.warning(f"Schema file not found: {DB_SCHEMA_PATH}")
        return

    try:
        with sync_engine.connect() as conn:
            with conn.begin():
                sql = DB_SCHEMA_PATH.read_text(encoding="utf-8")
                for stmt in _split_sql_statements(sql):
                    try:
                        conn.execute(text(stmt))
                    except Exception as e:
                        logger.debug(f"Schema stmt error (ignored): {e}")
        logger.info("Schema migration applied")
    except Exception as e:
        logger.warning(f"Schema migration skipped (database not connected): {e}")


# ==================== Async session factory ====================

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

ASYNC_DSN = settings.DB_DSN.replace("postgresql://", "postgresql+asyncpg://").replace("postgresql+psycopg2://", "postgresql+asyncpg://")
async_engine = create_async_engine(ASYNC_DSN, pool_size=5, max_overflow=10)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_db_session():
    """Контекстный менеджер сессии БД."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def health_check() -> bool:
    """Проверка доступности базы данных."""
    try:
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database health check passed")
        return True
    except Exception as e:
        logger.warning(f"Database health check failed (PostgreSQL unavailable): {e}")
        return False
