"""Tests for the block decision and the redirect log.

Blocking used to be evaluated only in the resident portal's JavaScript, so a
report taken by phone through manual intake, or POSTed straight at the Open311
endpoint, ignored road rules entirely. These pin the server-side decision that
closes that hole -- and, more importantly, pin that it fails open on every path
that could go wrong.
"""

import pytest

pytest.importorskip("sqlalchemy")
rb = pytest.importorskip("app.services.road_blocking")


class _Service:
    def __init__(self, mode="township", config=None, code="pothole", name="Pothole"):
        self.routing_mode = mode
        self.routing_config = config or {}
        self.service_code = code
        self.service_name = name


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _DB:
    """Enough AsyncSession for the code paths under test."""

    def __init__(self, status=None, boom=False, rows=None):
        self._status = status
        self._boom = boom
        self._rows = rows or []
        self.added = []
        self.committed = False

    async def execute(self, _q):
        if self._boom:
            raise RuntimeError("database unavailable")
        return _Result(self._status)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        pass


COUNTY = {
    "name": "Middlesex County",
    "roads": ["Cranbury Rd"],
    "message": "Call the county.",
    "contacts": [{"name": "County DPW", "phone": "555-0100"}],
}


# ---- whole-category redirects ----------------------------------------------

@pytest.mark.asyncio
async def test_third_party_category_blocks_regardless_of_location():
    """Nothing spatial about it: the whole service belongs to someone else."""
    service = _Service("third_party", {
        "third_party_name": "Water Authority",
        "message": "Water mains are handled by the authority.",
        "contacts": [{"name": "MCUA", "phone": "555-0199"}],
    })
    decision = await rb.evaluate(_DB(), service, None, None)
    assert decision.blocked is True
    assert decision.block_type == "category"
    assert decision.jurisdiction == "Water Authority"
    assert decision.contacts[0]["phone"] == "555-0199"


@pytest.mark.asyncio
async def test_category_block_has_a_message_even_when_unconfigured():
    """A resident must never see an empty redirect notice."""
    decision = await rb.evaluate(_DB(), _Service("third_party", {}), 40.3, -74.5)
    assert decision.blocked is True and decision.message


# ---- ordinary services -----------------------------------------------------

@pytest.mark.asyncio
async def test_township_mode_never_blocks():
    assert (await rb.evaluate(_DB(), _Service("township"), 40.3, -74.5)).blocked is False


@pytest.mark.asyncio
async def test_unknown_routing_mode_never_blocks():
    assert (await rb.evaluate(_DB(), _Service("something_new"), 40.3, -74.5)).blocked is False


@pytest.mark.asyncio
async def test_missing_routing_mode_never_blocks():
    service = _Service()
    service.routing_mode = None
    assert (await rb.evaluate(_DB(), service, 40.3, -74.5)).blocked is False


# ---- failing open ----------------------------------------------------------

@pytest.mark.asyncio
async def test_road_based_without_coordinates_does_not_block():
    """A report filed with no location cannot be on anyone's road."""
    service = _Service("road_based", {"jurisdictions": [COUNTY]})
    assert (await rb.evaluate(_DB(), service, None, None)).blocked is False


@pytest.mark.asyncio
async def test_database_failure_lets_the_report_through():
    """No road table, PostGIS missing, a query error -- none of these should
    stop someone reporting a pothole."""
    service = _Service("road_based", {"jurisdictions": [COUNTY]})
    assert (await rb.evaluate(_DB(boom=True), service, 40.3, -74.5)).blocked is False


@pytest.mark.asyncio
async def test_broken_service_object_lets_the_report_through():
    class Broken:
        @property
        def routing_mode(self):
            raise RuntimeError("boom")

    assert (await rb.evaluate(_DB(), Broken(), 40.3, -74.5)).blocked is False


# ---- the redirect log ------------------------------------------------------

@pytest.mark.asyncio
async def test_a_redirect_is_recorded():
    db = _DB()
    decision = rb.BlockDecision(
        blocked=True, block_type="road_based", jurisdiction="Middlesex County",
        road_name="Cranbury Rd",
    )
    await rb.record(db, decision, _Service(), 40.3, -74.5)
    assert len(db.added) == 1
    row = db.added[0]
    assert row.jurisdiction_name == "Middlesex County"
    assert row.road_name == "Cranbury Rd"
    assert row.block_type == "road_based"
    assert db.committed is True


@pytest.mark.asyncio
async def test_the_log_row_carries_no_personal_information():
    """A redirect is a count, not a record about a person. If these columns ever
    appear, the retention and export story changes completely."""
    from app.models import BlockedRequestLog

    columns = {c.name for c in BlockedRequestLog.__table__.columns}
    assert not columns & {"email", "phone", "first_name", "last_name", "description", "ip_address"}


def test_the_log_is_not_a_service_request():
    """It must never surface in a queue, a feed, an export or the public map."""
    from app.models import BlockedRequestLog, ServiceRequest

    assert BlockedRequestLog.__tablename__ != ServiceRequest.__tablename__
    assert BlockedRequestLog.__tablename__ == "blocked_request_log"


@pytest.mark.asyncio
async def test_nothing_is_recorded_when_nothing_was_blocked():
    db = _DB()
    await rb.record(db, rb.NOT_BLOCKED, _Service(), 40.3, -74.5)
    assert db.added == []


@pytest.mark.asyncio
async def test_a_logging_failure_does_not_raise():
    """Failing to count a redirect must not turn into a 500 on top of an
    already-unhappy resident interaction."""
    class Failing(_DB):
        async def commit(self):
            raise RuntimeError("disk full")

    await rb.record(
        Failing(), rb.BlockDecision(blocked=True, block_type="category"), _Service(), None, None
    )  # must not raise


# ---- corridor width --------------------------------------------------------

@pytest.mark.asyncio
async def test_corridor_width_comes_from_settings_when_present():
    class Status:
        corridor_metres = 8

    assert await rb._corridor_metres(_DB(status=Status())) == 8.0


@pytest.mark.asyncio
async def test_corridor_width_falls_back_to_the_default():
    from app.services.road_geometry import DEFAULT_CORRIDOR_METRES

    assert await rb._corridor_metres(_DB(boom=True)) == float(DEFAULT_CORRIDOR_METRES)
    assert await rb._corridor_metres(_DB(status=None)) == float(DEFAULT_CORRIDOR_METRES)
