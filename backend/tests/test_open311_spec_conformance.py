"""Two places this API answers a conformant GeoReport v2 client with a lie.

`status` and `service_code` are defined by the spec as comma-delimited lists --
"can be declared multiple times, comma delimited" -- and both list endpoints
compared the raw parameter to the column with `==`. So `?status=open,closed`,
which is the form a client copies straight out of the spec, matched the literal
string "open,closed" against a column that only ever holds one word. The
response was not an error. It was `[]`, which an integrator reads as "this town
has no open or closed reports", and which nothing in a log would contradict.

`GET /services.json` omitted the spec's `metadata` boolean while
`GET /services/{code}.json` hardcoded it to true. `metadata` is the flag that
tells a client whether the definition endpoint is worth calling; absent, it
defaults false, so a client that discovered services from the list built its
intake form without ever asking for the nine attributes waiting behind the
other endpoint. Two endpoints, opposite answers about the same service.

The filter tests below call the real handlers with a session that records the
SQLAlchemy statement, then compile it -- so what is asserted is the SQL that
would reach Postgres, not that a helper returned a list. A test that only
exercised the parser would have passed against the broken code too, because
the parser is the part that did not exist.
"""

import pytest

# Submodule guard, for the reason set out in test_migrate.py's header: with the
# dependencies absent, backend/app/ resolves as a namespace package and a guard
# on "app" would succeed while every import under it failed.
open311 = pytest.importorskip("app.api.open311")
pytest.importorskip("sqlalchemy.orm")

from fastapi import HTTPException  # noqa: E402  (after the guard, by design)


class _Result:
    """Whatever the handler asked for, there is none of it.

    Returning no rows is deliberate: these tests are about the WHERE clause the
    handler builds, and rows would only invite assertions on filtering that the
    database, not this code, performs.
    """

    def __init__(self, rows=(), scalar=None):
        self._rows = list(rows)
        self._scalar = scalar

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._scalar


class RecordingSession:
    """An AsyncSession stand-in that keeps every statement it was handed."""

    def __init__(self):
        self.statements = []

    async def execute(self, statement, *a, **kw):
        self.statements.append(statement)
        return _Result()


class _Admin:
    id = 1
    username = "admin"
    role = "admin"


class _DeadRedis:
    """Redis, as far as the listing is concerned: no cache, no crash.

    The public listing caches for 60s and would otherwise answer the second
    test from the first test's entry -- and a cached payload is exactly what
    must not decide whether the filter works.
    """

    async def get(self, key):
        return None

    async def setex(self, key, ttl, value):
        return None


def _sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


@pytest.fixture
def no_cache(monkeypatch):
    monkeypatch.setattr(open311, "redis_client", _DeadRedis())


# --------------------------------------------------------------------------
# The parser itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("open,closed", ["open", "closed"]),
        # Humans put a space after a comma, and a client that builds the query
        # by joining an array sometimes leaves a trailing one.
        ("open, closed", ["open", "closed"]),
        ("open,closed,", ["open", "closed"]),
        ("  open  ", ["open"]),
        # Nothing to filter on is not the same as filtering on nothing: an
        # empty parameter must mean "all", never "no results".
        ("", None),
        (",,", None),
        (None, None),
    ],
)
def test_a_comma_delimited_filter_is_split_the_way_a_client_writes_it(raw, expected):
    assert open311.parse_csv_filter(raw) == expected


def test_a_misspelt_status_is_an_error_and_not_an_empty_list():
    """Silence is indistinguishable from a town with no matching reports.

    This is the same failure the comma bug caused, so answering `[]` to
    `?status=opne` would have replaced one silent wrong answer with another.
    """
    with pytest.raises(HTTPException) as exc:
        open311.validated_statuses("open,opne,closd")
    assert exc.value.status_code == 400
    detail = str(exc.value.detail)
    assert "opne" in detail and "closd" in detail
    assert "open" not in detail.split(".")[0]  # the bad ones are named, not the good one


# --------------------------------------------------------------------------
# GET /requests.json  (staff)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_staff_list_accepts_a_comma_delimited_status():
    db = RecordingSession()
    await open311.list_requests(
        status_filter="open, closed",
        service_code=None,
        start_date=None,
        end_date=None,
        include_deleted=False,
        db=db,
        current_user=_Admin(),
    )
    sql = _sql(db.statements[-1])
    assert "IN ('open', 'closed')" in sql or "IN ('closed', 'open')" in sql, sql
    # The bug, stated as the thing that must not come back.
    assert "'open, closed'" not in sql
    assert "'open,closed'" not in sql


@pytest.mark.asyncio
async def test_the_staff_list_accepts_a_comma_delimited_service_code():
    db = RecordingSession()
    await open311.list_requests(
        status_filter=None,
        service_code="POTHOLE,STREETLIGHT",
        start_date=None,
        end_date=None,
        include_deleted=False,
        db=db,
        current_user=_Admin(),
    )
    sql = _sql(db.statements[-1])
    assert "'POTHOLE'" in sql and "'STREETLIGHT'" in sql, sql
    assert "'POTHOLE,STREETLIGHT'" not in sql


@pytest.mark.asyncio
async def test_a_single_status_still_filters_to_that_one_status():
    """The overwhelmingly common call, and the one already in production."""
    db = RecordingSession()
    await open311.list_requests(
        status_filter="in_progress",
        service_code=None,
        start_date=None,
        end_date=None,
        include_deleted=False,
        db=db,
        current_user=_Admin(),
    )
    sql = _sql(db.statements[-1])
    assert "'in_progress'" in sql
    assert "'open'" not in sql and "'closed'" not in sql


@pytest.mark.asyncio
async def test_the_staff_list_rejects_a_status_it_does_not_know():
    db = RecordingSession()
    with pytest.raises(HTTPException) as exc:
        await open311.list_requests(
            status_filter="open,pending",
            service_code=None,
            start_date=None,
            end_date=None,
            include_deleted=False,
            db=db,
            current_user=_Admin(),
        )
    assert exc.value.status_code == 400
    assert "pending" in str(exc.value.detail)


# --------------------------------------------------------------------------
# GET /public/requests
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_public_list_accepts_a_comma_delimited_status(no_cache):
    db = RecordingSession()
    await open311.list_public_requests(
        status="open,closed", service_code=None, limit=None, offset=0, db=db
    )
    sql = _sql(db.statements[-1])
    assert "IN ('open', 'closed')" in sql or "IN ('closed', 'open')" in sql, sql
    assert "'open,closed'" not in sql


@pytest.mark.asyncio
async def test_the_public_list_accepts_a_comma_delimited_service_code(no_cache):
    db = RecordingSession()
    await open311.list_public_requests(
        status=None, service_code="POTHOLE, GRAFFITI", limit=None, offset=0, db=db
    )
    sql = _sql(db.statements[-1])
    assert "'POTHOLE'" in sql and "'GRAFFITI'" in sql, sql
    assert "'POTHOLE, GRAFFITI'" not in sql


@pytest.mark.asyncio
async def test_the_public_list_rejects_an_unknown_status_before_reading_the_cache(no_cache):
    """Validated first, so the 400 does not depend on who called before you."""
    db = RecordingSession()
    with pytest.raises(HTTPException) as exc:
        await open311.list_public_requests(
            status="nonsense", service_code=None, limit=None, offset=0, db=db
        )
    assert exc.value.status_code == 400
    assert "nonsense" in str(exc.value.detail)
    assert db.statements == [], "the settings row was read before the parameter was checked"


@pytest.mark.asyncio
async def test_the_same_query_written_two_ways_shares_one_cache_entry(monkeypatch):
    """`open,closed` and `closed, open` are the same question.

    Keying on the raw string would give them separate 60-second entries, which
    is not a correctness bug on its own -- but it is the reason the key is
    built from the parsed values, and a later edit that reverts to the raw
    string would go unnoticed without this.
    """
    keys = []

    class _KeySpy(_DeadRedis):
        async def get(self, key):
            keys.append(key)
            return None

    monkeypatch.setattr(open311, "redis_client", _KeySpy())
    for raw in ("open,closed", "closed, open"):
        await open311.list_public_requests(
            status=raw, service_code=None, limit=None, offset=0, db=RecordingSession()
        )
    assert keys[0] == keys[1], keys


# --------------------------------------------------------------------------
# GET /services.json
# --------------------------------------------------------------------------

class _Service:
    service_code = "POTHOLE"
    service_name = "Pothole"
    description = "Report a pothole"
    is_active = True
    routing_mode = "township"
    translations = {}
    departments = []


class _ServiceSession(RecordingSession):
    """One active service, answered to both a list read and a by-code read."""

    async def execute(self, statement, *a, **kw):
        self.statements.append(statement)
        return _Result([_Service()], scalar=_Service())


@pytest.mark.asyncio
async def test_the_services_list_tells_a_client_whether_to_fetch_the_definition():
    services = await open311.list_open311_services(db=_ServiceSession())
    assert services, "fixture produced no services"
    for s in services:
        assert "metadata" in s, (
            "GET /services.json omits the spec's `metadata` flag, so a client "
            "defaults it false and never calls the definition endpoint"
        )
        assert isinstance(s["metadata"], bool)


@pytest.mark.asyncio
async def test_the_list_and_the_definition_agree_about_metadata():
    """The two endpoints disagreeing is the actual defect.

    Whatever the list claims about a service, `GET /services/{code}.json` has
    to back it up -- and it does, unconditionally, for every active service.
    Pinned against each other rather than against the literal `True`, so the
    day service definitions become optional this fails on the list that forgot
    to learn it instead of passing on a hardcode.
    """
    listed = (await open311.list_open311_services(db=_ServiceSession()))[0]
    defined = await open311.get_service_definition(
        service_code="POTHOLE", db=_ServiceSession()
    )

    assert listed["metadata"] == defined["metadata"]
    # And the claim is true: `metadata: true` means "there are attributes here".
    if listed["metadata"]:
        assert defined["attributes"], "list advertises metadata the definition does not have"
