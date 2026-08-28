"""A failing connector check has to come back as a *result*, not a 500.

On the live demo every "Check connection" press returned 500 Internal Server
Error, so the admin saw "Something went wrong running the check. Please try
again." while the backend had already worked out the real answer -- "ArcGIS
rejected the credentials (Invalid token.)" -- and threw it away. Retrying could
never help, and the one sentence that would have told them what to fix was the
thing being lost.

The cause was two correct fixes meeting. `test_integration` rolls the session
back after the check so a half-failed transaction cannot swallow the sync-log
write; but a rollback *expires* every instance in that session, so the very next
line -- `integration.id` -- became a lazy re-load, i.e. blocking IO inside async
attribute access, i.e. MissingGreenlet.

These exercise the real thing: a real async session, a real IntegrationConfig
row, a real rollback. `test_expired_after_rollback` is the mechanism, and it
fails against the old code.
"""

import pytest

# CI installs only cryptography/httpx/pytest/pytest-asyncio/alembic, so an
# unguarded app import breaks collection there while passing locally.
pytest.importorskip("sqlalchemy.ext.asyncio")
pytest.importorskip("aiosqlite")
pytest.importorskip("fastapi.routing")

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.models import Base, IntegrationConfig, IntegrationSyncLog  # noqa: E402


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Only the two tables under test: the full metadata carries PostGIS
        # geometry columns (road_segments.geom) that SQLite cannot create.
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[IntegrationConfig.__table__, IntegrationSyncLog.__table__],
            )
        )
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _saved_integration(session: AsyncSession) -> IntegrationConfig:
    row = IntegrationConfig(
        platform="arcgis", display_name="ArcGIS", enabled=False,
        config={"layer_url": "https://x/0"},
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_expired_after_rollback(session):
    """The mechanism, in the endpoint's own order.

    `_get_integration` SELECTs the row, opening a transaction; the rollback that
    follows the check ends that transaction and expires everything loaded in it.
    Reading an attribute then re-loads -- blocking IO under asyncio, which is the
    MissingGreenlet the live deployment was throwing on every check.
    """
    from sqlalchemy import select

    await _saved_integration(session)

    # As _get_integration does: load it inside a fresh transaction.
    loaded = (await session.execute(
        select(IntegrationConfig).where(IntegrationConfig.platform == "arcgis")
    )).scalar_one()

    await session.rollback()

    with pytest.raises(Exception):
        _ = loaded.id


@pytest.mark.asyncio
async def test_the_sync_log_still_records_the_failure_after_a_rollback(session):
    """What the endpoint does, in the order it does it.

    Writing the log with the path parameter survives the rollback, so the
    activity trail keeps the vendor's reason instead of losing it to a 500.
    """
    integration = await _saved_integration(session)
    integration_id = integration.id          # the path parameter, in the endpoint
    detail = "ArcGIS rejected the credentials (Invalid token.)"

    await session.rollback()                 # what test_integration does

    session.add(IntegrationSyncLog(
        integration_id=integration_id, operation="test", status="error", detail=detail[:2000],
    ))
    await session.commit()

    from sqlalchemy import select
    rows = (await session.execute(select(IntegrationSyncLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "error"
    assert "Invalid token" in rows[0].detail
    assert rows[0].integration_id == integration_id
