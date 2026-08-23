"""What the outbound push owes a resident's report.

Four things that were each quietly wrong, and each invisible from outside:

  * the `IntegrationLink` was only durable once the *photos* had uploaded, so a
    failed attachment rolled back the link while the vendor's record survived --
    and the next attempt, finding no link, filed the same pothole again;
  * `due_date` read `getattr(sr, "due_datetime", None)` against a column
    ServiceRequest has never had, so every work order Pinpoint opened carried no
    deadline at all;
  * vendor error text reached `integration_sync_logs.detail` and
    `integration_links.sync_error` having passed through only the connector's
    own redaction, not the scrubber of record that strips URL query strings --
    and one of our auth styles puts the API key in the URL;
  * a stored row for a platform we no longer connect took a ValueError on every
    beat tick and wrote it to the activity trail as a failure nobody can fix.
"""

from datetime import datetime, timedelta, timezone

import pytest

BASE_NOW = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


def tasks():
    """The sync tasks module. Needs the ORM and Celery, which CI does not have."""
    pytest.importorskip("sqlalchemy.orm")
    pytest.importorskip("celery.app")
    import app.tasks.integrations as module
    return module


# ---------------------------------------------------------------------------
# 1. A platform we no longer connect must not become a daily failure
# ---------------------------------------------------------------------------

def test_the_retired_platform_is_gone_from_the_catalog():
    from app.integrations.registry import PLATFORM_CATALOG, RETIRED_PLATFORMS

    assert "civicplus" not in PLATFORM_CATALOG
    assert "civicplus" in RETIRED_PLATFORMS


def test_building_a_retired_connection_explains_the_way_forward():
    """A town with a stored row deserves the actual answer, not "unknown
    platform" -- SeeClickFix publishes a GeoReport v2 endpoint, so the generic
    Open311 connection still reaches it."""
    from app.integrations.registry import build_connector

    with pytest.raises(ValueError) as caught:
        build_connector("civicplus", {}, {})
    message = str(caught.value)
    assert "has been removed" in message
    assert "Open311" in message
    assert "kept so nothing is lost" in message


def test_an_unknown_platform_is_still_just_unknown():
    from app.integrations.registry import build_connector

    with pytest.raises(ValueError) as caught:
        build_connector("not-a-vendor", {}, {})
    assert "Unknown integration platform" in str(caught.value)


def test_the_sync_tasks_skip_a_row_they_cannot_build():
    module = tasks()

    class Row:
        def __init__(self, platform):
            self.platform = platform

    assert module._retired(Row("civicplus")) is True
    assert module._retired(Row("accela")) is False
    assert module._retired(Row("")) is True


@pytest.mark.asyncio
async def test_the_nightly_sweep_does_not_record_a_retired_row_as_broken():
    """Recording it would be true and permanent: three nights to `down`, then a
    digest email every morning about a connector that cannot be repaired."""
    from app.services import connector_verification

    class Row:
        platform = "civicplus"

    recorded = []

    class Health:
        @staticmethod
        async def record_failure(db, name, error, provider=None):
            recorded.append(("failure", name))

        @staticmethod
        async def record_unverifiable(db, name, detail, provider=None):
            recorded.append(("unverifiable", name))

    async def never_build(_integration):
        raise AssertionError("the sweep should not try to build a retired row")

    checked = await connector_verification.verify_integrations(
        None, integrations=[Row()], build=never_build,
        guard=never_build, health=Health(),
    )
    assert checked == {"govtech:civicplus": "retired"}
    assert recorded == []


def test_the_admin_list_names_a_retired_row_rather_than_hiding_it():
    """It has no catalog entry and therefore no card. Without this flag the row
    simply vanishes from the page while still sitting in the database."""
    pytest.importorskip("fastapi.routing")
    from app.api.integrations import _serialize

    class Row:
        id = 7
        platform = "civicplus"
        display_name = "CivicPlus"
        enabled = True
        sync_direction = "bidirectional"
        config = {}
        credentials = {"api_key": "x"}
        webhook_token = "tok"
        lookups_cache = {}
        lookups_fetched_at = None
        mapping_approved_at = None
        mapping_approved_by = None
        last_sync_at = None
        last_sync_status = None
        last_sync_error = None
        created_at = None

    body = _serialize(Row())
    assert body["retired"] is True
    assert "Open311" in body["retired_reason"]
    assert body["platform_name"] == "CivicPlus (SeeClickFix)"

    class Live(Row):
        platform = "accela"

    live = _serialize(Live())
    assert live["retired"] is False and live["retired_reason"] is None


def test_every_loop_over_the_integration_rows_consults_the_skip():
    """Seven loops walk the stored rows -- push, status, pull, comment push,
    comment pull, assets, per-request refresh. A retired row reaching any one
    of them writes an unfixable error to the activity trail on that path's own
    schedule, and the six that still worked would hide the seventh."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/tasks/integrations.py").read_text()
    code = "\n".join(line.split("#")[0] for line in source.splitlines())
    blocks = [b for b in code.split("@celery_app.task") if "await build_connector_for(" in b]
    assert len(blocks) == 7, f"expected seven task loops, found {len(blocks)}"
    for block in blocks:
        name = block.split("def ", 1)[1].split("(", 1)[0]
        assert "_retired(" in block, f"{name} does not skip a retired row"


# ---------------------------------------------------------------------------
# 2. The due date a work-order system needs
# ---------------------------------------------------------------------------

class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeDB:
    """A session that answers one lookup. The due-date resolver's only database
    contact is fetching the ServiceDefinition for the report's category."""

    def __init__(self, service):
        self.service = service
        self.queries = 0

    async def execute(self, _statement):
        self.queries += 1
        return FakeResult(self.service)


class FakeService:
    def __init__(self, sla_hours):
        self.sla_hours = sla_hours


class FakeRequest:
    def __init__(self, requested=BASE_NOW, service_code="POTHOLE"):
        self.service_code = service_code
        self.requested_datetime = requested


@pytest.mark.asyncio
async def test_the_due_date_is_the_categorys_own_sla_counted_from_filing():
    module = tasks()
    db = FakeDB(FakeService(sla_hours=72))
    due = await module._due_date(db, FakeRequest())
    assert due == (BASE_NOW + timedelta(hours=72)).isoformat()


@pytest.mark.asyncio
async def test_a_category_with_no_sla_sends_no_deadline():
    """SLAs are opt-in per category. Inventing one would put a commitment in the
    vendor's system that the town never agreed to and somebody has to answer
    for -- worse than the null it replaces."""
    module = tasks()
    for service in (FakeService(sla_hours=None), FakeService(sla_hours=0), None):
        assert await module._due_date(FakeDB(service), FakeRequest()) is None


@pytest.mark.asyncio
async def test_a_naive_stored_timestamp_is_read_as_utc_not_local():
    module = tasks()
    naive = datetime(2026, 8, 5, 9, 0)
    due = await module._due_date(FakeDB(FakeService(24)), FakeRequest(requested=naive))
    assert due == datetime(2026, 8, 6, 9, 0, tzinfo=timezone.utc).isoformat()


@pytest.mark.asyncio
async def test_a_report_with_no_filing_time_asks_the_database_nothing():
    module = tasks()
    db = FakeDB(FakeService(24))
    assert await module._due_date(db, FakeRequest(requested=None)) is None
    assert db.queries == 0


def test_the_payload_carries_the_resolved_due_date_and_not_a_missing_column():
    """`due_datetime` exists only on the *inbound* ExternalRecord dataclass --
    it is what a vendor tells us. Reading it off a ServiceRequest was always
    None, which is why nobody noticed for as long as they did."""
    module = tasks()
    from app.models import ServiceRequest

    assert not hasattr(ServiceRequest, "due_datetime"), (
        "if this column is ever added, _due_date should prefer it"
    )
    payload = module._build_payload(
        _MinimalRequest(), {}, "Public Works", "2026-08-08T09:00:00+00:00")
    assert payload["due_date"] == "2026-08-08T09:00:00+00:00"
    assert payload["assigned_department"] == "Public Works"


class _MinimalRequest:
    """Only what `_build_payload` reads."""
    service_request_id = "REQ-1"
    service_code = "POTHOLE"
    service_name = "Pothole"
    description = "d"
    address = "12 Main St"
    lat = 40.0
    long = -74.0
    status = "open"
    requested_datetime = BASE_NOW
    media_urls = []
    matched_asset = None
    custom_fields = {}
    manual_priority_score = None
    priority = 5
    assigned_to = None
    closed_datetime = None
    closed_substatus = None
    completion_message = None
    completion_photo_url = None
    updated_datetime = None
    source = "portal"
    preferred_language = "en"


# ---------------------------------------------------------------------------
# 3. Nothing stored or shown carries a credential
# ---------------------------------------------------------------------------

def test_a_url_borne_key_does_not_survive_into_the_activity_trail():
    """`auth_style=query` on the generic connector puts the API key in the URL,
    and httpx bakes the full URL into its own error strings. The connector's own
    redaction only covers bodies it quoted itself."""
    module = tasks()
    import httpx

    error = httpx.HTTPStatusError(
        "Server error '500' for url "
        "'https://api.vendor.test/v1/requests?api_key=live-secret-9f3a&limit=100'",
        request=None, response=None,
    )
    cleaned = module._safe_error(error)
    assert "live-secret-9f3a" not in cleaned
    assert "api.vendor.test" in cleaned, "the host is what support needs"


def test_a_key_echoed_in_a_body_does_not_survive_either():
    module = tasks()
    from app.integrations.base import ConnectorError

    error = ConnectorError(
        "Vendor create failed: HTTP 400 — rejected token=abcdef123456 field=service_code")
    cleaned = module._safe_error(error)
    assert "abcdef123456" not in cleaned
    assert "service_code" in cleaned


def test_the_error_paths_that_write_to_the_database_all_scrub():
    """Source-level, because the alternative is one test per call site and a
    new one silently unprotected the day somebody adds a sixth."""
    from pathlib import Path

    source = Path(__file__).resolve().parents[1] / "app/tasks/integrations.py"
    code = "\n".join(line.split("#")[0] for line in source.read_text().splitlines())
    assert "str(e)[:1000]" not in code, "an unscrubbed error is being stored"
    for stored in ("sync_error=", "last_sync_error="):
        for line in code.splitlines():
            if stored in line and "=None" not in line and "= None" not in line:
                assert "_safe_error" in line, line.strip()


def test_the_test_button_does_not_hand_the_browser_a_raw_vendor_string():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/services/connector_verification.py").read_text()
    block = source[source.index("async def check_integration_now"):]
    code = "\n".join(line.split("#")[0] for line in block.splitlines())
    assert '"detail": str(exc)' not in code
    assert code.count('clean_error(exc)') >= 3


# ---------------------------------------------------------------------------
# 4. One report, one ticket
# ---------------------------------------------------------------------------

def test_the_link_is_committed_before_the_photos_are_pushed():
    """The vendor's record exists the moment `push_request` returns. If the
    transaction that records the link can still be rolled back after that, a
    photo-upload failure loses the link while the record survives -- and the
    "already linked?" check at the top of the loop finds nothing next time.

    Read from the source because the ordering *is* the invariant: the two calls
    are three lines apart and swapping them reintroduces the duplicate."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/tasks/integrations.py").read_text()
    block = source[source.index("def push_request_to_integrations"):]
    block = block[:block.index("@celery_app.task", 1)]
    code = "\n".join(line.split("#")[0] for line in block.splitlines())

    add_link = code.index("db.add(link)")
    first_commit = code.index("await db.commit()", add_link)
    push_docs = code.index("await _push_documents(")
    assert first_commit < push_docs, (
        "the link must be durable before anything else in the iteration can fail"
    )


def test_the_tasks_no_longer_advertise_a_retry_they_never_perform():
    """`max_retries=3` with no `self.retry` call is a policy an admin can read
    and believe. Retrying is done by RetryTransport and the circuit breaker,
    which can do it without re-pushing to the vendors that already succeeded."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1]
              / "app/tasks/integrations.py").read_text()
    code = "\n".join(line.split("#")[0] for line in source.splitlines())
    assert "max_retries=" not in code
    assert "self.retry" not in code
    assert "bind=True" not in code
