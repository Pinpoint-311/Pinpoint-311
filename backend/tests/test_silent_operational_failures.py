"""Failures that reported success.

Every case in this file is one where something stopped working and nothing said
so. That is a worse class of bug than a crash: a crash gets fixed on the day it
happens, and these ran for months while the console showed green.

They are grouped by the thing that was silent, not by the module, because the
shape repeats -- a broad `except` sitting over a bug in the line above it,
turning "this code is wrong" into "the service is unavailable", which is a
sentence nobody investigates.
"""

import logging
import types
from datetime import datetime, timedelta, timezone

import pytest


# ===========================================================================
# Backup monitoring
# ===========================================================================
#
# Three places, one root cause: a naive datetime meeting an aware one.
#
#   backup_service.list_backups          TypeError on every parsed filename,
#                                        caught by the function's own except,
#                                        so an S3 bucket full of backups was
#                                        reported as `{"status": "error",
#                                        "backups": []}`
#   backup_service.cleanup_old_backups   same TypeError, caught per backup, so
#                                        the retention sweep deleted nothing,
#                                        forever, and returned success
#   proactive_health._backup_age_check   same again, so the check that would
#                                        have noticed either of the above could
#                                        never fire

backup_service = pytest.importorskip("app.services.backup_service")


class _FakeDB:
    """Enough of a session for the readings collector's own liveness probe."""

    async def execute(self, *a, **k):
        return types.SimpleNamespace(
            first=lambda: (1,), scalar=lambda: 1, scalars=lambda: types.SimpleNamespace(
                all=lambda: [], first=lambda: None))


def test_a_backup_filename_parses_to_an_aware_utc_datetime():
    """`strptime` returns naive. Everything it is compared against is aware."""
    parsed = backup_service.parse_backup_timestamp("db_backup_20260127_020000.sql.gpg")
    assert parsed is not None, "the standard backup filename no longer parses"
    assert parsed.tzinfo is not None, (
        "a parsed backup timestamp is naive; subtracting it from an aware `now` "
        "raises TypeError, which is what made list_backups report an empty bucket"
    )
    assert parsed == datetime(2026, 1, 27, 2, 0, 0, tzinfo=timezone.utc)


def test_the_age_of_a_parsed_backup_can_actually_be_computed():
    """The exact expression list_backups runs, in isolation. It raised."""
    parsed = backup_service.parse_backup_timestamp("db_backup_20260127_020000.sql.gpg")
    age = (datetime.now(timezone.utc) - parsed).days
    assert isinstance(age, int)


def test_a_backup_can_be_compared_against_a_retention_cutoff():
    """The expression cleanup_old_backups runs. It raised, per backup, caught,
    so nothing was ever deleted and the run reported success."""
    stored = backup_service.parse_backup_timestamp(
        "db_backup_20260127_020000.sql.gpg").isoformat()
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    revived = backup_service.as_utc(
        datetime.fromisoformat(stored.replace("Z", "+00:00")))
    assert revived < cutoff  # a 2026-01-27 backup is older than 30 days ago


def test_as_utc_leaves_an_already_aware_timestamp_alone():
    """S3's LastModified is aware. Stamping UTC over a real offset would move
    the timestamp."""
    aware = datetime(2026, 1, 27, 2, 0, tzinfo=timezone(timedelta(hours=5)))
    assert backup_service.as_utc(aware) is aware


def test_an_unparseable_backup_name_does_not_raise():
    assert backup_service.parse_backup_timestamp("not-a-backup.txt") is None


def test_the_backup_task_is_allowed_longer_than_the_global_limit():
    """`task_time_limit=300` applies to every task. pg_dump | gzip | gpg |
    upload over a municipal database does not fit in five minutes, and a hard
    kill does not run the task's own except -- so the backup stopped and not
    even the error log was written."""
    pytest.importorskip("celery.app")
    from app.core.celery_app import celery_app
    from app.tasks.service_requests import backup_database

    global_limit = celery_app.conf.task_time_limit
    # Read off the REGISTERED TASK, not off a module constant. A constant can be
    # defined and never wired to the decorator, which is exactly the mistake
    # this is guarding against -- and a test that reads the constant would call
    # that fixed.
    own_limit = backup_database.time_limit
    assert own_limit is not None, (
        f"backup_database declares no time_limit of its own, so it runs under "
        f"the global {global_limit}s and is killed part-way through the dump"
    )
    assert own_limit > global_limit, (
        f"backup_database's limit ({own_limit}s) is not above the global "
        f"{global_limit}s, so it is still killed part-way through the dump"
    )
    assert backup_database.soft_time_limit and backup_database.soft_time_limit < own_limit, (
        "there is no soft limit below the hard one, so the task is shot rather "
        "than given an exception it can catch and report"
    )


# ===========================================================================
# The Redis probe imported a module that does not exist
# ===========================================================================

def test_there_is_no_module_called_app_core_redis_client():
    """The premise. connector_verification did `from app.core.redis_client
    import redis_client`; there is no such module and there never was."""
    import importlib.util

    assert importlib.util.find_spec("app.core.redis_client") is None, (
        "app.core.redis_client now exists -- if it was added deliberately, the "
        "probe should use it and this test should go"
    )


def test_the_cache_probe_does_not_import_a_module_that_does_not_exist():
    """What the bug cost: `system:cache` reported BROKEN on every sweep and
    emailed every administrator hourly about a perfectly healthy Redis, because
    the ModuleNotFoundError was caught by the same `except` that handles a real
    connection failure. A genuine Redis outage was indistinguishable from it.

    An import error is a fault in our code. It is not evidence about somebody
    else's service and must not be filed as one.
    """
    from pathlib import Path

    import app.services.connector_verification as cv

    source = Path(cv.__file__).read_text()
    # Comments describe the history; the check reads code.
    import re
    code = re.sub(r"#[^\n]*", "", source)
    assert "app.core.redis_client" not in code, (
        "the cache probe is importing app.core.redis_client again"
    )


async def test_an_unconfigured_cache_is_not_reported_as_broken(monkeypatch):
    """A town with no REDIS_URL has not made a mistake. An amber badge on
    something switched off is the noise that teaches people to ignore badges."""
    cv = pytest.importorskip("app.services.connector_verification")
    monkeypatch.delenv("REDIS_URL", raising=False)

    out = await cv._collect_readings(_FakeDB())
    cache = out["system:cache"]
    assert cache["ok"] is True
    assert cache.get("recorded") is False


async def test_a_configured_but_unreachable_cache_is_reported_as_broken(monkeypatch):
    """The other direction has to still work, or the fix has just made the
    probe permanently green -- which is the same non-signal, inverted."""
    cv = pytest.importorskip("app.services.connector_verification")
    pytest.importorskip("redis.asyncio")
    # A port nothing is listening on, with a short timeout.
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")

    out = await cv._collect_readings(_FakeDB())
    assert out["system:cache"]["ok"] is False


async def test_the_cache_failure_detail_never_carries_the_url(monkeypatch):
    """A Redis URL carries a password, and this string is stored in
    connector_health.last_error, rendered on the card, and put in the alert
    email."""
    cv = pytest.importorskip("app.services.connector_verification")
    pytest.importorskip("redis.asyncio")
    monkeypatch.setenv("REDIS_URL", "redis://:hunter2@127.0.0.1:1/0")

    out = await cv._collect_readings(_FakeDB())
    detail = str(out["system:cache"].get("detail", ""))
    assert "hunter2" not in detail
    assert "127.0.0.1" not in detail


# ===========================================================================
# Backup status is a dict, and the probe read it as a datetime
# ===========================================================================

async def test_the_backup_probe_understands_the_shape_it_is_given(monkeypatch):
    """`get_backup_status()["last_backup"]` is a DICT -- name, size, created_at,
    age_days. The probe treated it as a datetime, called .replace() on it, and
    the AttributeError went into an `except` that reports "backups unavailable".
    So the backup check read "unmeasured" no matter what the backups were doing.
    """
    cv = pytest.importorskip("app.services.connector_verification")

    recent = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    async def _status():
        return {
            "configured": True,
            "last_backup": {"name": "db_backup_x.sql.gpg", "size_bytes": 10,
                            "created_at": recent, "age_days": 0},
        }

    import app.services.backup_service as bs
    monkeypatch.setattr(bs, "get_backup_status", _status)

    out = await cv._collect_readings(_FakeDB())
    backups = out["system:backups"]
    assert backups.get("recorded") is not False, (
        "a town with a two-hour-old backup is still reported as unmeasured"
    )
    assert backups["ok"] is True


# ===========================================================================
# proactive_health's copy of the same datetime bug
# ===========================================================================

async def test_the_backup_freshness_check_can_actually_measure_freshness(monkeypatch):
    """It reported "unknown" on every sweep. The one check that verifies a
    town's backups are still running could never fire -- so a town whose
    backups stopped months ago looked exactly like a town whose backups were
    fine."""
    ph = pytest.importorskip("app.services.proactive_health")

    stale = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()

    async def _status():
        return {"configured": True,
                "last_backup": {"created_at": stale, "name": "x", "size_bytes": 1}}

    import app.services.backup_service as bs
    monkeypatch.setattr(bs, "get_backup_status", _status)

    check = await ph._backup_age_check()
    assert check["status"] != "unknown", (
        "the backup freshness check still cannot read a backup timestamp"
    )
    assert check["status"] == "critical", (
        f"a backup 100 hours old should be critical, got {check['status']}"
    )
    assert check["value"] and check["value"] > 90


async def test_a_fresh_backup_reads_as_ok(monkeypatch):
    ph = pytest.importorskip("app.services.proactive_health")

    fresh = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()

    async def _status():
        return {"configured": True, "last_backup": {"created_at": fresh}}

    import app.services.backup_service as bs
    monkeypatch.setattr(bs, "get_backup_status", _status)

    assert (await ph._backup_age_check())["status"] == "ok"


# ===========================================================================
# A failed alert email must not permanently silence the alert
# ===========================================================================

def test_the_alert_state_is_not_recorded_before_the_send():
    """`health_alert_state` is what makes an alert fire only on a transition
    into a worse status. It was written and committed BEFORE the email went
    out, so once "disk is critical" was recorded, disk was never a transition
    again -- and if the send then failed, ten minutes of SMTP trouble bought a
    permanent silence. The admin was never told and never would be, because the
    database said they already had been.

    services/connector_alerts.py:463-481 already had this right: `remember()`
    runs only after a delivery succeeded, and says why.

    Read as source because the surrounding function needs a database, a mail
    provider and Celery. What is pinned is the ORDER of two statements, which
    is exactly what the bug was.
    """
    import re
    from pathlib import Path

    source = Path("app/tasks/service_requests.py").read_text()
    body = source[source.index("def proactive_health_scan"):]
    body = body[:body.index("\n@celery_app.task", 1)] if "\n@celery_app.task" in body[1:] else body

    send = body.index("notification_service.send_email")

    # EVERY write to the alert state before the send is checked, not just the
    # last one. Adding an early write back while leaving the correct one in
    # place reintroduces the bug exactly, and "the last write is after the send"
    # would not notice.
    #
    # One write before the send is legitimate: the no-escalations path, which
    # records "nothing is wrong" and returns without sending anything. It is
    # recognised by the return that immediately follows it.
    writes = [m.start() for m in re.finditer(r"settings\.health_alert_state\s*=", body)]
    assert writes, "the health alert state is never recorded at all"

    for at in writes:
        if at > send:
            continue
        following = body[at:at + 300]
        assert '"status": "ok"' in following, (
            "the health alert state is written before the alert email is sent. "
            "Once a check is recorded as critical it is no longer a transition, "
            "so if the send then fails the admin is never told -- and never will "
            "be, because the database says they already were. See "
            "services/connector_alerts.py:463-481, which does this correctly."
        )

    after = [at for at in writes if at > send]
    assert after, "nothing records the alert state after a successful send"

    # And a delivery check sits between the send and that write.
    assert "delivered" in body[send:after[-1]], (
        "nothing between the send and the state write checks whether anything "
        "was actually delivered"
    )


# ===========================================================================
# The statistics export lazy-loaded a relationship on an async session
# ===========================================================================

async def test_the_statistics_export_eager_loads_the_department():
    """`req.assigned_department.name` on an AsyncSession instance is a lazy load
    and raises MissingGreenlet, so GET /api/export/statistics 500ed on any
    non-empty dataset -- every deployment that has ever received a report. The
    frontend has a live button for it.

    The identical hazard is documented twenty lines above it in the same file,
    on get_requests_for_export.
    """
    pytest.importorskip("fastapi.routing")
    data_export = pytest.importorskip("app.api.data_export")
    from sqlalchemy.orm import selectinload
    from app.models import ServiceRequest

    captured = {}

    class _DB:
        async def execute(self, statement, *a, **k):
            captured.setdefault("statements", []).append(statement)
            raise _Stop()

    class _Stop(Exception):
        pass

    with pytest.raises(_Stop):
        await data_export.export_statistics(
            start_date=None, end_date=None, format="json",
            db=_DB(), current_user=types.SimpleNamespace(role="admin", username="a"))

    statement = captured["statements"][0]
    options = getattr(statement, "_with_options", ())
    assert options, (
        "the statistics query has no loader options at all, so reading "
        "req.assigned_department.name will raise MissingGreenlet"
    )
    # The Load object's repr does not name the attribute; its path does.
    paths = " ".join(str(getattr(opt, "path", "")) for opt in options)
    assert "assigned_department" in paths, (
        f"the statistics query does not eager-load assigned_department: {paths}"
    )
    # Sanity: the option we expect is constructible the same way.
    assert selectinload(ServiceRequest.assigned_department) is not None


# ===========================================================================
# A silent fallback that changes who gets turned away
# ===========================================================================

async def test_a_failed_corridor_read_is_logged(caplog):
    """road_blocking._corridor_metres had a bare `except Exception: pass`. What
    it discarded is the town's own corridor width, and falling back to the
    default changes which residents are redirected to the county instead of
    being allowed to file. A town that widened its corridor because the default
    was turning people away would silently get the default back."""
    rb = pytest.importorskip("app.services.road_blocking")

    class _Broken:
        async def execute(self, *a, **k):
            raise RuntimeError("road_data_status is not there")

    with caplog.at_level(logging.WARNING):
        value = await rb._corridor_metres(_Broken())

    assert value == float(rb.DEFAULT_CORRIDOR_METRES)
    assert any("corridor" in r.message.lower() or "corridor" in r.getMessage().lower()
               for r in caplog.records), (
        "the corridor width fell back to the default with nothing in the log; "
        "block/allow decisions changed and no operator can tell why"
    )


# ===========================================================================
# Retention promised a photo cleanup that did not exist
# ===========================================================================

scrub = pytest.importorskip("app.services.retention_scrub")


def test_a_purge_clears_the_completion_photo():
    """`completion_photo_url` was not in the scrub catalog at all -- not under
    "media", not anywhere -- so a full PURGE, which selects every field in the
    catalog, left the staff completion photo in the column and reachable
    through the unauthenticated /api/uploads mount. It is a photograph taken at
    the resident's address."""
    record = types.SimpleNamespace(
        media_urls=["/api/uploads/a.jpg"],
        completion_photo_url="/api/uploads/b.jpg",
    )
    cleared = scrub.apply_scrub(record, scrub.fields_for_mode(scrub.PURGE))
    assert "media" in cleared
    assert record.media_urls == []
    assert record.completion_photo_url is None, (
        "a full purge left the completion photo URL in place"
    )


def test_the_catalog_no_longer_promises_a_cleanup_that_does_not_run():
    """The entry said "The files themselves are removed by the storage cleanup
    that follows". There was no storage cleanup. A town may have relied on that
    sentence to answer a records request."""
    media = next(f for f in scrub.SCRUB_FIELDS if f["id"] == "media")
    assert "storage cleanup that follows" not in media["detail"]
    assert "deleted from disk" in media["detail"]


@pytest.mark.parametrize("url,expected", [
    ("/api/uploads/abc123.jpg", ["abc123.jpg"]),
    ("http://town.example/api/uploads/abc123.jpg", ["abc123.jpg"]),
    ("/api/uploads/abc123.jpg?v=2", ["abc123.jpg"]),
    # Not ours: nothing local to delete.
    ("https://cdn.example/photo.jpg", []),
    ("data:image/jpeg;base64,AAAA", []),
    # Path traversal in a database value must not become a path to unlink.
    ("/api/uploads/../../etc/passwd", []),
    ("/api/uploads/sub/dir/x.jpg", []),
    ("/api/uploads/", []),
])
def test_only_bare_local_upload_names_are_ever_returned(url, expected):
    record = types.SimpleNamespace(media_urls=[url], completion_photo_url=None)
    assert scrub.upload_filenames(record) == expected


def test_both_photo_columns_are_collected():
    record = types.SimpleNamespace(
        media_urls=["/api/uploads/one.jpg", "/api/uploads/two.jpg"],
        completion_photo_url="/api/uploads/done.jpg",
    )
    assert scrub.upload_filenames(record) == ["one.jpg", "two.jpg", "done.jpg"]


def test_the_files_are_actually_deleted(tmp_path, monkeypatch):
    """The cleanup that was being promised, doing the thing."""
    service = pytest.importorskip("app.services.retention_service")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))

    kept = tmp_path / "someone-elses.jpg"
    kept.write_bytes(b"x")
    for name in ("one.jpg", "done.jpg"):
        (tmp_path / name).write_bytes(b"x")

    removed = service.delete_upload_files(["one.jpg", "done.jpg"])

    assert sorted(removed) == ["done.jpg", "one.jpg"]
    assert not (tmp_path / "one.jpg").exists()
    assert not (tmp_path / "done.jpg").exists()
    assert kept.exists(), "the cleanup deleted a file it was not given"


def test_the_cleanup_cannot_be_walked_out_of_the_upload_directory(tmp_path, monkeypatch):
    """A URL is data from the database. It must never be able to name a path
    outside UPLOAD_DIR."""
    service = pytest.importorskip("app.services.retention_service")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    (tmp_path / "uploads").mkdir()

    victim = tmp_path / "important.db"
    victim.write_bytes(b"x")

    service.delete_upload_files(["../important.db", "/etc/passwd"])
    assert victim.exists(), "retention deleted a file outside the upload directory"


def test_a_missing_file_is_not_an_error(tmp_path, monkeypatch):
    """The promise is that the photo is not reachable. An already-deleted file
    satisfies it, and raising here would abort a retention run over nothing."""
    service = pytest.importorskip("app.services.retention_service")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    assert service.delete_upload_files(["never-existed.jpg"]) == ["never-existed.jpg"]
