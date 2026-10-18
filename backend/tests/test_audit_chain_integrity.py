"""The audit_logs hash chain verifies from stored data alone.

GET /api/audit/verify-integrity used to 500 on every call (a missing await),
and fixing only that would have reported tampering on every row: version 1
hashed a timestamp taken in Python while the row stored the database's own
now(), so no entry could be recomputed. These tests pin down chain version 2:
a clean chain verifies, every kind of edit is found at the row it happened to,
deleting from the middle or the tail is found, the legacy rows are reported
rather than flagged, and two writers cannot fork the chain.

The Postgres test at the bottom runs only when AUDIT_CHAIN_PG_URL points at a
throwaway database (it creates and drops tables there).
"""

import asyncio
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("geoalchemy2.types")   # app.models declares Geometry columns
pytest.importorskip("aiosqlite")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

models = pytest.importorskip("app.models")
audit_service = pytest.importorskip("app.services.audit_service")
audit_chain = pytest.importorskip("app.core.audit_chain")

AuditLog, AuditAnchor, User = models.AuditLog, models.AuditAnchor, models.User
AuditService = audit_service.AuditService
TABLES = [User.__table__, AuditLog.__table__, AuditAnchor.__table__]


def _make_engine(path):
    return create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)


async def _create(engine):
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: models.Base.metadata.create_all(c, tables=TABLES))


@pytest.fixture
async def maker():
    with tempfile.TemporaryDirectory() as d:
        engine = _make_engine(os.path.join(d, "audit.db"))
        await _create(engine)
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await engine.dispose()


async def _log(maker, n, **kw):
    async with maker() as db:
        for i in range(n):
            await AuditService.log_event(
                db, event_type=kw.get("event_type", "login_success"), success=True,
                username=f"user{i}", user_id=None, ip_address="198.51.100.7",
                user_agent="Mozilla/5.0", session_id=f"jti-{i}",
                details={"i": i, "nested": {"b": 1, "a": [1, 2]}},
            )


async def _sql(maker, stmt, **params):
    async with maker() as db:
        await db.execute(text(stmt), params)
        await db.commit()


async def _verify(maker, batch_size=3):
    async with maker() as db:
        return await AuditService.verify_integrity(db, batch_size=batch_size)


async def _anchor_now(maker):
    """What the nightly task records for audit_logs."""
    async with maker() as db:
        head = (await db.execute(text(
            "SELECT id, entry_hash FROM audit_logs ORDER BY id DESC LIMIT 1"))).first()
        count, legacy = (await db.execute(text(
            "SELECT count(*), sum(CASE WHEN chain_version = 1 THEN 1 ELSE 0 END) "
            "FROM audit_logs WHERE id <= :h"), {"h": head.id})).one()
        db.add(AuditAnchor(auth_head_id=head.id, auth_head_hash=head.entry_hash,
                           auth_entry_count=count, auth_legacy_count=legacy or 0))
        await db.commit()


# --------------------------------------------------------------------------
# A clean chain
# --------------------------------------------------------------------------

async def test_a_clean_chain_verifies_across_batches(maker):
    await _log(maker, 7)
    await _anchor_now(maker)
    await _log(maker, 2)
    r = await _verify(maker)
    assert r["integrity_valid"] is True, r["first_break"]
    assert r["total_entries"] == 9
    assert r["verified_entries"] == 9
    assert r["legacy_entries"] == 0
    assert r["anchors_checked"] == 1
    assert r["first_break"] is None


async def test_the_stored_timestamp_is_the_hashed_one(maker):
    await _log(maker, 1)
    async with maker() as db:
        row = (await db.execute(text("SELECT * FROM audit_logs"))).mappings().one()
    assert row["chain_version"] == 2
    assert row["previous_hash"] is None
    assert row["context_salt"] and row["context_digest"]


async def test_an_empty_table_verifies(maker):
    r = await _verify(maker)
    assert r["integrity_valid"] is True and r["total_entries"] == 0


async def test_rows_built_directly_are_chained_too(maker):
    """system.py constructs AuditLog itself rather than via AuditService."""
    await _log(maker, 2)
    async with maker() as db:
        db.add(AuditLog(event_type="version_deployed", success=True, username="admin",
                        details={"to_sha": "abc1234", "steps": ("a", "b")}))
        await db.commit()
    r = await _verify(maker)
    assert r["integrity_valid"] is True, r["first_break"]
    assert r["verified_entries"] == 3


# --------------------------------------------------------------------------
# Tampering
# --------------------------------------------------------------------------

@pytest.mark.parametrize("column,value", [
    ("username", "someone_else"),
    ("event_type", "logout"),
    ("success", 0),
    ("details", '{"i": 99}'),
    ("timestamp", "2020-01-01 00:00:00.000000"),
    ("ip_address", "203.0.113.66"),
    ("user_agent", "curl/8"),
])
async def test_editing_one_field_is_detected_at_that_row(maker, column, value):
    await _log(maker, 6)
    await _sql(maker, f"UPDATE audit_logs SET {column} = :v WHERE id = 4", v=value)
    r = await _verify(maker)
    assert r["integrity_valid"] is False
    assert r["first_break"]["id"] == 4
    assert r["verified_entries"] == 3


async def test_editing_a_row_and_its_hash_breaks_the_next_link(maker):
    await _log(maker, 5)
    await _sql(maker, "UPDATE audit_logs SET entry_hash = :h WHERE id = 2", h="f" * 64)
    r = await _verify(maker)
    assert r["first_break"]["id"] == 2
    assert r["first_break"]["stored_hash_prefix"] == "f" * 12


async def test_deleting_a_middle_row_is_detected(maker):
    await _log(maker, 6)
    await _sql(maker, "DELETE FROM audit_logs WHERE id = 3")
    r = await _verify(maker)
    assert r["integrity_valid"] is False
    assert r["first_break"]["id"] == 4
    assert "link" in r["first_break"]["reason"]
    assert r["first_break"]["expected_hash_prefix"] != r["first_break"]["stored_hash_prefix"]


async def test_truncating_the_tail_is_detected_via_the_anchor(maker):
    await _log(maker, 6)
    await _anchor_now(maker)
    await _sql(maker, "DELETE FROM audit_logs WHERE id >= 5")
    r = await _verify(maker)
    assert r["integrity_valid"] is False
    assert r["first_break"]["id"] == 6
    assert "truncated" in r["first_break"]["reason"]


async def test_truncating_and_rewriting_the_tail_is_detected_via_the_anchor(maker):
    await _log(maker, 6)
    await _anchor_now(maker)
    await _sql(maker, "DELETE FROM audit_logs WHERE id >= 5")
    await _log(maker, 3)       # ids 7.. on SQLite's rowid reuse, or 5..; either way
    r = await _verify(maker)
    assert r["integrity_valid"] is False


async def test_ip_redaction_by_retention_is_not_tampering(maker):
    await _log(maker, 3)
    async with maker() as db:
        db.add(AuditLog(event_type="login_success", success=True, username="old",
                        ip_address="198.51.100.1", user_agent="UA",
                        timestamp=datetime.now(timezone.utc) - timedelta(days=200)))
        await db.commit()
    # What purge_old_ip_addresses does to a row past the 90-day window.
    await _sql(maker, "UPDATE audit_logs SET ip_address = NULL, user_agent = NULL, "
                      "context_salt = NULL WHERE username = 'old'")
    r = await _verify(maker)
    assert r["integrity_valid"] is True, r["first_break"]
    assert r["redacted_context_entries"] == 1


def test_the_retention_purge_removes_the_salt_with_the_ip():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app/tasks/service_requests.py").read_text()
    block = src[src.index("def purge_old_ip_addresses"):]
    block = block[:block.index("@celery_app.task")]
    assert "context_salt=None" in block


async def test_redacting_a_recent_ip_is_flagged(maker):
    await _log(maker, 3)
    await _sql(maker, "UPDATE audit_logs SET ip_address = NULL, user_agent = NULL, "
                      "context_salt = NULL WHERE id = 2")
    r = await _verify(maker)
    assert r["first_break"]["id"] == 2
    assert "retention" in r["first_break"]["reason"]


# --------------------------------------------------------------------------
# Legacy rows
# --------------------------------------------------------------------------

async def _legacy_rows(maker, n):
    for i in range(n):
        await _sql(
            maker,
            "INSERT INTO audit_logs (event_type, success, username, timestamp, previous_hash, "
            "entry_hash, chain_version) VALUES ('login_success', 1, :u, :t, :p, :h, 1)",
            u=f"legacy{i}", t="2025-01-01 00:00:00", p=None if i == 0 else f"{i - 1:064d}",
            h=f"{i:064d}",
        )


async def test_legacy_rows_are_reported_not_flagged(maker):
    await _legacy_rows(maker, 4)
    await _log(maker, 3)
    r = await _verify(maker)
    assert r["integrity_valid"] is True, r["first_break"]
    assert r["legacy_entries"] == 4
    assert r["verified_entries"] == 3
    assert r["first_verified_id"] == 5
    async with maker() as db:
        link = (await db.execute(text("SELECT previous_hash FROM audit_logs WHERE id = 5"))).scalar()
    assert link == f"{3:064d}", "the first v2 entry links to the last legacy row's stored hash"


async def test_the_legacy_boundary_is_tamper_evident(maker):
    await _legacy_rows(maker, 3)
    await _log(maker, 2)
    await _sql(maker, "UPDATE audit_logs SET entry_hash = :h WHERE id = 3", h="e" * 64)
    r = await _verify(maker)
    assert r["first_break"]["id"] == 4


async def test_marking_a_v2_row_legacy_does_not_hide_an_edit(maker):
    await _legacy_rows(maker, 2)
    await _log(maker, 4)
    await _sql(maker, "UPDATE audit_logs SET chain_version = 1, username = 'x' WHERE id = 5")
    r = await _verify(maker)
    assert r["first_break"]["id"] == 5
    assert "legacy" in r["first_break"]["reason"]


async def test_growing_the_legacy_segment_is_caught_by_the_anchor(maker):
    await _legacy_rows(maker, 2)
    await _log(maker, 4)
    await _anchor_now(maker)
    # Downgrade the first v2 row: it now looks like part of the legacy segment.
    await _sql(maker, "UPDATE audit_logs SET chain_version = 1, username = 'x' WHERE id = 3")
    r = await _verify(maker)
    assert r["integrity_valid"] is False


# --------------------------------------------------------------------------
# The endpoint
# --------------------------------------------------------------------------

async def test_the_verify_endpoint_no_longer_500s(maker):
    api = pytest.importorskip("app.api.audit")
    await _legacy_rows(maker, 1)
    await _log(maker, 2)
    async with maker() as db:
        body = await api.verify_audit_log_integrity(db=db, _=None)
    assert body["integrity_valid"] is True
    assert body["verified_entries"] == 2 and body["legacy_entries"] == 1
    assert "intact" in body["message"]

    await _sql(maker, "UPDATE audit_logs SET username = 'x' WHERE id = 3")
    async with maker() as db:
        body = await api.verify_audit_log_integrity(db=db, _=None)
    assert body["integrity_valid"] is False
    assert body["first_break"]["id"] == 3
    assert "entry 3" in body["message"]


def test_the_verify_endpoint_is_admin_only():
    import inspect
    api = pytest.importorskip("app.api.audit")
    from app.core.auth import get_current_admin
    sig = inspect.signature(api.verify_audit_log_integrity)
    assert any(getattr(p.default, "dependency", None) is get_current_admin
               for p in sig.parameters.values())


# --------------------------------------------------------------------------
# The nightly anchor
# --------------------------------------------------------------------------

def test_the_nightly_anchor_records_the_auth_chain(monkeypatch):
    tasks = pytest.importorskip("app.tasks.service_requests")
    with tempfile.TemporaryDirectory() as d:
        engine = _make_engine(os.path.join(d, "audit.db"))
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def setup():
            await _create(engine)
            async with engine.begin() as conn:
                await conn.run_sync(lambda c: models.Base.metadata.create_all(
                    c, tables=[models.RequestAuditLog.__table__]))
            await _legacy_rows(maker, 1)
            await _log(maker, 3)
        asyncio.run(setup())

        monkeypatch.setattr(tasks, "SessionLocal", maker)
        out = tasks.anchor_audit_chain.run()
        assert out["status"] == "anchored", out
        assert out["auth_head_id"] == 4 and out["auth_count"] == 4
        assert tasks.anchor_audit_chain.run()["status"] == "unchanged"

        async def check():
            async with maker() as db:
                a = (await db.execute(text("SELECT * FROM audit_anchors"))).mappings().one()
            assert a["auth_legacy_count"] == 1 and a["auth_entry_count"] == 4
            assert a["head_hash"] is None          # no request-audit rows yet
            await _sql(maker, "DELETE FROM audit_logs WHERE id = 4")
            r = await _verify(maker)
            assert r["integrity_valid"] is False and "truncated" in r["first_break"]["reason"]
        asyncio.run(check())
        asyncio.run(engine.dispose())


# --------------------------------------------------------------------------
# Concurrency
# --------------------------------------------------------------------------

class _FakeSession:
    """Just enough of a Session for the before_flush listener."""

    def __init__(self, dialect, new):
        self.new = new
        self.statements = []
        self._dialect = dialect

    def get_bind(self):
        class _B:
            pass
        b = _B()
        b.dialect = _B()
        b.dialect.name = self._dialect
        return b

    def execute(self, stmt, params=None):
        self.statements.append((str(stmt), params))

        class _R:
            def scalar(self_inner):
                return "a" * 64
        return _R()


@pytest.mark.parametrize("dialect,locks", [("postgresql", True), ("sqlite", False)])
def test_the_chain_lock_is_taken_before_the_previous_hash_is_read(dialect, locks):
    row = AuditLog(event_type="login_success", success=True)
    s = _FakeSession(dialect, [row])
    models._auth_audit_hash_chain(s, None, None)
    sqls = [st for st, _ in s.statements]
    if locks:
        assert "pg_advisory_xact_lock" in sqls[0]
        assert s.statements[0][1] == {"k": audit_chain.CHAIN_LOCK_KEY}
        assert "audit_logs" in sqls[1]
    else:
        assert not any("pg_advisory" in q for q in sqls)
    assert row.previous_hash == "a" * 64 and row.chain_version == 2
    assert row.entry_hash == audit_chain.compute_hash(row, "a" * 64)


PG_URL = os.environ.get("AUDIT_CHAIN_PG_URL")


@pytest.mark.skipif(not PG_URL, reason="needs a throwaway Postgres (AUDIT_CHAIN_PG_URL)")
async def test_concurrent_writers_do_not_fork_the_chain_on_postgres():
    engine = create_async_engine(PG_URL, pool_size=20, max_overflow=20)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: models.Base.metadata.drop_all(c, tables=TABLES[::-1]))
            await conn.run_sync(lambda c: models.Base.metadata.create_all(c, tables=TABLES))
        maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async def writer(w):
            async with maker() as db:
                for i in range(10):
                    await AuditService.log_event(
                        db, event_type="login_success", success=True, username=f"w{w}-{i}",
                        ip_address="198.51.100.2", user_agent="UA", details={"w": w, "i": i})

        await asyncio.gather(*(writer(w) for w in range(16)))
        async with maker() as db:
            prevs = (await db.execute(text("SELECT previous_hash FROM audit_logs"))).scalars().all()
            r = await AuditService.verify_integrity(db, batch_size=37)
        assert len(prevs) == 160
        assert len(set(prevs)) == 160, "two entries link to the same predecessor: the chain forked"
        assert r["integrity_valid"] is True, r["first_break"]
        assert r["verified_entries"] == 160
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(lambda c: models.Base.metadata.drop_all(c, tables=TABLES[::-1]))
        await engine.dispose()
