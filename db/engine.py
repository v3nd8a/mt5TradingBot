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


def init_db() -> None:
    """Создать таблицы из SQLAlchemy моделей."""
    Base.metadata.create_all(sync_engine)
    logger.info("Database tables initialized")


def run_schema_migration() -> None:
    """Выполнить SQL schema файл если таблицы не существуют."""
    if not DB_SCHEMA_PATH.exists():
        logger.warning(f"Schema file not found: {DB_SCHEMA_PATH}")
        return

    with sync_engine.connect() as conn:
        with conn.begin():
            sql = DB_SCHEMA_PATH.read_text(encoding="utf-8")
            # Execute each statement separately
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    try:
                        conn.execute(text(stmt))
                    except Exception as e:
                        logger.debug(f"Schema stmt error (ignored): {e}")
    logger.info("Schema migration applied")


# ==================== Async session factory ====================

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ASYNC_DSN = settings.DB_DSN.replace("postgresql://", "postgresql+asyncpg://").replace("postgresql+psycopg2://", "postgresql+asyncpg://")
async_engine = create_async_engine(ASYNC_DSN, pool_size=5, max_overflow=10)
AsyncSessionLocal = async_sessionmaker(async_engine, class_=Session, expire_on_commit=False)


@asynccontextmanager
async def get_db_session() -> Session:
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
        logger.error(f"Database health check failed: {e}")
        return False
