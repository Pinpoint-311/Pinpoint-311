"""A report that could not reach the vendor is still owed to the vendor.

The push path's whole answer to a failed push was one row in
`integration_sync_logs`. That table is an audit trail -- nothing reads it back,
nothing retries from it -- so a twenty-minute vendor outage silently cost the
town every report filed during it, and the only trace was a line in a drawer
nobody opens.

These tests are about the four ways a backlog can be worse than none:

  * it retries forever, hammering a vendor whose credential was revoked;
  * it gives up quietly, which is the original bug with extra steps;
  * it double-pushes on replay, filing the same pothole twice;
  * it falls over on a deployment that has not run the migration yet, turning a
    vendor failure into a task crash.

The schedule tests drive the real `_record_dead_letter` against a session
stand-in that holds rows, so what is asserted is the attempt count and the
`next_attempt_at` the code actually computes -- not that a helper was called.
"""

from datetime import datetime, timedelta, timezone

import pytest

# pytest.ini sets asyncio_mode = auto, so the async tests below need no mark.


def tasks():
    pytest.importorskip("sqlalchemy.orm")
    pytest.importorskip("celery.app")
    import app.tasks.integrations as module
    return module


class Rows:
    """The rows a fake session holds, with the two lookups the code makes."""

    def __init__(self):
        self.items = []
        self.commits = 0
        self.rollbacks = 0
        self.raise_on_execute = None


class FakeResult:
    def __init__(self, items):
        self._items = items

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return self

    def all(self):
        return list(self._items)


class FakeDB:
    """Holds IntegrationDeadLetter instances and answers the module's queries.

    The filters are re-applied in Python rather than parsed out of the
    statement: what matters here is that a second failure for the same subject
    updates one row instead of inserting a second, and that is a fact about the
    rows, not about the SQL.
    """

    def __init__(self, rows: Rows):
        self.rows = rows

    async def execute(self, _statement):
        if self.rows.raise_on_execute:
            raise self.rows.raise_on_execute
        return FakeResult([i for i in self.rows.items if i.resolved_at is None])

    def add(self, item):
        self.rows.items.append(item)

    async def commit(self):
        self.rows.commits += 1

    async def rollback(self):
        self.rows.rollbacks += 1


def _open_items(rows):
    return [i for i in rows.items if i.resolved_at is None]


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------

async def test_a_failed_push_is_kept_rather_than_only_logged():
    module = tasks()
    rows = Rows()
    await module._record_dead_letter(
        FakeDB(rows), 3, "push", RuntimeError("vendor gateway timeout"),
        service_request_id=99)

    assert len(rows.items) == 1
    item = rows.items[0]
    assert item.integration_id == 3 and item.operation == "push"
    assert item.service_request_id == 99
    assert item.attempts == 1
    assert "gateway timeout" in item.last_error
    assert item.resolved_at is None
    assert rows.commits == 1


async def test_the_same_report_failing_twice_is_one_item_not_two():
    """One row per piece of work. Otherwise a vendor down for a day shows a
    backlog of ninety-six entries for one report."""
    module = tasks()
    rows = Rows()
    db = FakeDB(rows)
    for _ in range(3):
        await module._record_dead_letter(db, 3, "push", RuntimeError("still down"),
                                         service_request_id=99)
    assert len(rows.items) == 1
    assert rows.items[0].attempts == 3


async def test_the_wait_between_attempts_grows():
    module = tasks()
    rows = Rows()
    db = FakeDB(rows)
    waits = []
    for _ in range(4):
        before = datetime.now(timezone.utc)
        await module._record_dead_letter(db, 1, "push", RuntimeError("down"),
                                         service_request_id=1)
        waits.append(rows.items[0].next_attempt_at - before)

    assert waits == sorted(waits), "each wait should be at least the last"
    assert waits[0] < timedelta(minutes=10), "the first retry is soon — most failures are blips"
    assert waits[-1] > timedelta(hours=1), "a persistent failure should back off"


async def test_it_stops_calling_but_does_not_stop_caring():
    """The row must survive the last attempt. Deleting it here, or marking it
    resolved, is the original silent drop wearing a hat."""
    module = tasks()
    rows = Rows()
    db = FakeDB(rows)
    for _ in range(module.MAX_DEAD_LETTER_ATTEMPTS + 2):
        await module._record_dead_letter(db, 1, "push", RuntimeError("revoked key"),
                                         service_request_id=1)

    item = rows.items[0]
    assert item.next_attempt_at is None, "no further automatic attempt is scheduled"
    assert item.resolved_at is None, "but it is still owed, and still visible"
    assert item.attempts == module.MAX_DEAD_LETTER_ATTEMPTS + 2


async def test_a_credential_in_the_vendors_error_does_not_reach_the_backlog():
    """`last_error` is rendered in the admin UI like every other stored error,
    so it goes through the same scrubber."""
    module = tasks()
    import httpx

    rows = Rows()
    error = httpx.HTTPStatusError(
        "Server error '500' for url "
        "'https://api.vendor.test/v1/requests?api_key=live-secret-9f3a'",
        request=None, response=None)
    await module._record_dead_letter(FakeDB(rows), 1, "push", error, service_request_id=1)
    assert "live-secret-9f3a" not in rows.items[0].last_error


async def test_a_deployment_without_the_table_yet_degrades_instead_of_crashing():
    """Recording the backlog must never be the reason a push task dies. The old
    log-only behaviour is the floor, not an exception."""
    module = tasks()
    rows = Rows()
    rows.raise_on_execute = RuntimeError(
        'relation "integration_dead_letters" does not exist')
    await module._record_dead_letter(FakeDB(rows), 1, "push", RuntimeError("x"),
                                     service_request_id=1)
    assert rows.rollbacks == 1


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------

async def test_a_push_that_finally_lands_closes_the_item():
    module = tasks()
    rows = Rows()
    db = FakeDB(rows)
    await module._record_dead_letter(db, 3, "push", RuntimeError("down"),
                                     service_request_id=99)
    await module._clear_dead_letter(db, 3, "push", service_request_id=99)

    item = rows.items[0]
    assert item.resolved_at is not None
    assert item.resolution == "succeeded"
    assert item.next_attempt_at is None
    assert _open_items(rows) == []


async def test_clearing_something_that_was_never_owed_is_a_no_op():
    """Every successful push calls this, and almost all of them have no backlog
    entry. It must not cost a write."""
    module = tasks()
    rows = Rows()
    await module._clear_dead_letter(FakeDB(rows), 3, "push", service_request_id=99)
    assert rows.commits == 0


async def test_clearing_survives_a_missing_table_too():
    module = tasks()
    rows = Rows()
    rows.raise_on_execute = RuntimeError("no such table")
    await module._clear_dead_letter(FakeDB(rows), 3, "push", service_request_id=99)
    assert rows.rollbacks == 1


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

def test_replay_reuses_the_real_push_tasks_rather_than_a_second_copy():
    """The replay path is only safe because the push tasks are idempotent --
    they skip an integration the report is already linked to. A private
    reimplementation here would not inherit that, and would be the thing that
    files the second ticket."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/tasks/integrations.py").read_text()
    block = source[source.index("def retry_integration_dead_letters"):]
    block = block[:block.index("@celery_app.task", 1)]
    code = "\n".join(line.split("#")[0] for line in block.splitlines())

    for task_name in ("push_request_to_integrations", "push_status_to_integrations",
                      "push_comment_to_integrations"):
        assert f"{task_name}(" in code, f"replay does not go through {task_name}"
    assert "connector." not in code, "replay must not talk to a connector itself"
    assert "resolution" not in code, (
        "replay must not close a row; the push path does that when it lands"
    )


def test_the_comment_push_checks_the_marker_before_posting_again():
    """A replay re-runs the whole task, which walks every link on the request --
    including the platform that already took the comment. Without this check the
    resident sees the same sentence twice on the vendor's side."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/tasks/integrations.py").read_text()
    block = source[source.index("def push_comment_to_integrations"):]
    block = block[:block.index("@celery_app.task", 1)]
    code = "\n".join(line.split("#")[0] for line in block.splitlines())

    guard = code.index("_comment_fp(comment.content) in set(link.pushed_comment_ids")
    push = code.index("await connector.push_comment(")
    assert guard < push, "the echo marker must be checked before the vendor call"


def test_only_enabled_connections_are_replayed():
    """A town that switched a connection off has said stop. Draining its backlog
    at it anyway is the opposite of what the switch means."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/tasks/integrations.py").read_text()
    block = source[source.index("def retry_integration_dead_letters"):]
    block = block[:block.index("@celery_app.task", 1)]
    assert "IntegrationConfig.enabled == True" in block
    assert "next_attempt_at.isnot(None)" in block, (
        "a stalled item must not be picked up by the automatic loop"
    )


def test_the_replay_runs_on_the_beat():
    pytest.importorskip("celery.app")
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    entry = schedule["retry-integration-dead-letters"]
    assert entry["task"] == "app.tasks.integrations.retry_integration_dead_letters"
    # Faster than the first backoff step, or every early attempt is rounded up
    # to the beat interval.
    first_step_seconds = tasks().DEAD_LETTER_BACKOFF_HOURS[0] * 3600
    assert entry["schedule"] <= max(first_step_seconds * 2, 600)


# ---------------------------------------------------------------------------
# What the admin sees
# ---------------------------------------------------------------------------

def test_discarding_requires_a_reason():
    """"This report never reached the county and we chose not to send it" is a
    decision about a public record. It needs a name and a sentence against it,
    which is the whole difference between this and the silent drop."""
    pytest.importorskip("fastapi.routing")
    from app.api.integrations import BacklogDiscard
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        BacklogDiscard()
    with pytest.raises(ValidationError):
        BacklogDiscard(reason="")
    assert BacklogDiscard(reason="Duplicate of REQ-42, filed by hand.").reason


def test_the_backlog_endpoints_are_admin_only():
    pytest.importorskip("fastapi.routing")
    from app.api import integrations as api

    paths = {r.path: r for r in api.router.routes if hasattr(r, "path")}
    for path in ("/{integration_id}/backlog",
                 "/{integration_id}/backlog/{item_id}/retry",
                 "/{integration_id}/backlog/{item_id}/discard"):
        assert path in paths, f"{path} is not registered"
    # The dependency itself, rather than the path list: a route that lost its
    # guard would still be registered.
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "app/api/integrations.py").read_text()
    block = text[text.index('@router.get("/{integration_id}/backlog")'):
                 text.index('@router.get("/{integration_id}/logs")')]
    assert block.count("Depends(get_current_admin)") == 3
    assert "get_current_staff" not in block


def test_a_discard_leaves_the_row_behind():
    """Deleted rows answer no questions later. A discard is an event in the
    record, not an erasure of one."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "app/api/integrations.py").read_text()
    block = text[text.index("async def discard_backlog_item"):
                 text.index('@router.get("/{integration_id}/logs")')]
    code = "\n".join(line.split("#")[0] for line in block.splitlines())
    assert "db.delete" not in code
    assert 'item.resolution = "discarded"' in code
    assert "item.resolved_by" in code and "item.resolution_note" in code
    assert "IntegrationSyncLog(" in code, "a discard belongs in the activity trail"


def test_the_model_and_the_migration_agree():
    """The table is created by Alembic on one deployment and by create_all on
    another. A column in only one of them is a column that exists on half the
    towns."""
    from pathlib import Path

    pytest.importorskip("sqlalchemy.orm")
    from app.models import IntegrationDeadLetter

    versions = Path(__file__).resolve().parents[1] / "alembic/versions"
    migration = "\n".join(p.read_text() for p in versions.glob("*.py")
                          if "integration_dead_letters" in p.read_text())
    assert migration, "no migration creates integration_dead_letters"
    for column in IntegrationDeadLetter.__table__.columns:
        assert f"'{column.name}'" in migration, f"{column.name} is not in the migration"


def test_the_migration_chains_onto_the_previous_head():
    from pathlib import Path
    import re

    versions = Path(__file__).resolve().parents[1] / "alembic/versions"
    sources = {p.name: p.read_text() for p in versions.glob("*.py")}
    mine = next(t for t in sources.values() if "integration_dead_letters" in t)
    down = re.search(r"^down_revision[^=]*=\s*'([^']+)'", mine, re.M).group(1)
    assert any(re.search(rf"^revision[^=]*=\s*'{down}'", t, re.M) for t in sources.values()), (
        f"down_revision {down} names no existing revision"
    )
    mine_rev = re.search(r"^revision[^=]*=\s*'([^']+)'", mine, re.M).group(1)
    others = [t for t in sources.values() if "integration_dead_letters" not in t]
    assert not any(re.search(rf"^down_revision[^=]*=\s*'{mine_rev}'", t, re.M) for t in others), (
        "something already chains onto this revision — rebase rather than fork the chain"
    )
