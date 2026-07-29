import logging
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from app.core.config import get_settings

settings = get_settings()

# Async engine for FastAPI endpoints
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Sync engine for non-async contexts (encryption, health checks)
# Convert asyncpg URL to psycopg2
sync_db_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
sync_engine = create_engine(
    sync_db_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()


async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Create any table the migrations did not, and complain if that happens.

    This used to be the *only* way the schema was created, which is why upgrades
    silently half-worked: create_all adds missing tables and will not touch an
    existing one, so a new column never appeared. Migrations now run in the
    entrypoint before the API starts (app/db/migrate.py).

    It is kept because it is the belt to the migrations' braces -- and because
    creating anything here now means the two descriptions of the schema have
    drifted apart again. A model was added without a migration. That is worth a
    loud warning rather than a silent fix: the silent fix is what let the drift
    accumulate in the first place, and a developer's laptop is where it should
    be caught, not a town's server.
    """
    from sqlalchemy import inspect

    async with engine.begin() as conn:
        before = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))
        await conn.run_sync(Base.metadata.create_all)
        after = set(await conn.run_sync(lambda c: inspect(c).get_table_names()))

    created = sorted(after - before)
    if created:
        logging.getLogger(__name__).warning(
            "[schema] created %d table(s) that no migration describes: %s. "
            "Add an Alembic revision for these -- create_all cannot alter an "
            "existing table, so the next change to them will not apply.",
            len(created), ", ".join(created),
        )
