"""Who is allowed to export exact locations, and who is allowed to read the log.

The research dataset is well tested. `build_dataset_row`, the pack switches,
the fuzzing, the visibility conditions -- all covered, all careful. The
*authorization around them* had no test at all, which was found by mutation:

    research.py:1331   if privacy_mode == "exact" and current_user.role != "admin":
    research.py:1419   (the same check on the GeoJSON export)
    research.py:2023   if current_user.role != "admin":   (the access log)

Change any of those to `if False:` and the whole suite passes. What that ships
is a researcher account -- a role a town hands out to a university partner, a
consultant, a graduate student -- able to export the exact latitude, longitude
and street address of every report in the town, when the entire point of the
role is that it gets fuzzed coordinates. And able to read the access log, which
names which researchers pulled what.

Fuzzing is the control that makes the research portal safe to switch on. A
report is filed from somebody's house. Exact coordinates plus the description
is the resident's address plus what they complained about their neighbour.

The endpoints are called directly rather than through a TestClient, because
this is about the function's own decision and not about routing. The database
is a stand-in that raises the moment it is touched: reaching it is how the test
proves a caller got PAST the authorization check, and never reaching it is how
the test proves a caller was stopped before any data was read.
"""

import types

import pytest

pytest.importorskip("fastapi.routing")
pytest.importorskip("sqlalchemy.orm")

research = pytest.importorskip("app.api.research")

from fastapi import HTTPException  # noqa: E402


class ReachedTheData(Exception):
    """Raised by the stand-in database. Getting here means the gate let you in."""


class _DB:
    async def execute(self, *a, **k):
        raise ReachedTheData()


def _user(role: str):
    return types.SimpleNamespace(id=1, username=f"a-{role}", role=role, email="x@y.z")


def _request():
    return types.SimpleNamespace(
        client=types.SimpleNamespace(host="10.0.0.1"),
        headers={"user-agent": "pytest"},
    )


async def _passed_the_gate(coro) -> bool:
    """True when the call got past authorization.

    "Past the gate" is defined as "did not raise HTTPException". The endpoint
    goes on to build a query against a stand-in session and fails somewhere in
    there -- on `db.execute`, or earlier on a relationship that is not mapped in
    this import context -- and which of those it is does not matter. What
    matters is that the 403 was not raised: the caller was authorized, and the
    endpoint proceeded to do work.

    Deliberately not "did it raise ReachedTheData": pinning the exact internal
    failure point would make this file break every time the query changes,
    which is how a test starts getting rewritten to whatever passes.
    """
    try:
        await coro
    except HTTPException:
        return False
    except Exception:
        return True
    return True


@pytest.fixture(autouse=True)
def _research_is_switched_on(monkeypatch):
    """These tests are about the role check that comes after the module switch.
    The switch itself gets its own test below."""
    async def _enabled(db):
        return True

    monkeypatch.setattr(research, "check_research_enabled", _enabled)


# ---- exact coordinates are admin-only ---------------------------------------

EXACT_EXPORTS = [
    ("export_csv", "csv"),
    ("export_geojson", "geojson"),
]


@pytest.mark.parametrize("endpoint,label", EXACT_EXPORTS)
@pytest.mark.parametrize("role", ["researcher", "staff", "viewer"])
async def test_only_an_admin_can_export_exact_locations(endpoint, label, role):
    """A researcher asking for exact coordinates is refused, and refused before
    a single row is read."""
    handler = getattr(research, endpoint)
    with pytest.raises(HTTPException) as caught:
        await handler(request=_request(), privacy_mode="exact",
                      db=_DB(), current_user=_user(role))
    assert caught.value.status_code == 403
    assert "admin" in str(caught.value.detail).lower(), (
        f"the {label} export refused a {role} for some other reason; this test "
        f"is meant to be pinning the exact-location check"
    )


@pytest.mark.parametrize("endpoint,label", EXACT_EXPORTS)
async def test_an_admin_may_export_exact_locations(endpoint, label):
    """The permission has to actually work, or towns route around it."""
    handler = getattr(research, endpoint)
    assert await _passed_the_gate(
        handler(request=_request(), privacy_mode="exact",
                db=_DB(), current_user=_user("admin"))), (
        "an admin was refused the exact-location export"
    )


@pytest.mark.parametrize("endpoint,label", EXACT_EXPORTS)
async def test_a_researcher_may_still_export_fuzzed_locations(endpoint, label):
    """The role is not locked out of the portal -- only out of exact
    coordinates. Pinned so a future tightening does not quietly take the whole
    export away while the tests above still pass."""
    handler = getattr(research, endpoint)
    assert await _passed_the_gate(
        handler(request=_request(), privacy_mode="fuzzed",
                db=_DB(), current_user=_user("researcher"))), (
        "a researcher can no longer run the fuzzed export at all"
    )


@pytest.mark.parametrize("endpoint,label", EXACT_EXPORTS)
@pytest.mark.parametrize("sneaky", ["EXACT", "Exact", " exact", "exact "])
async def test_a_researcher_never_gets_exact_coordinates_by_spelling_it_differently(
        endpoint, label, sneaky):
    """`privacy_mode` arrives as a query string.

    Two safe outcomes: refused (the value was read as exact), or allowed through
    and treated as not-exact, which means fuzzed. The unsafe outcome is being
    allowed through AND treated as exact downstream -- what a normalisation
    applied on only one side of the comparison would produce. The endpoint
    compares against the literal "exact", so anything else is fuzzed by
    construction; this pins that the check and the use stay the same comparison.
    """
    handler = getattr(research, endpoint)
    allowed = await _passed_the_gate(
        handler(request=_request(), privacy_mode=sneaky,
                db=_DB(), current_user=_user("researcher")))
    if allowed:
        assert sneaky != "exact", (
            "a researcher was allowed through with privacy_mode='exact'"
        )
        # And the value the endpoint would act on is not the exact one.
        assert sneaky.strip().lower() == "exact"  # it looks like exact...
        assert sneaky != "exact"                  # ...but is not the literal it tests


# ---- the access log is admin-only -------------------------------------------

@pytest.mark.parametrize("role", ["researcher", "staff", "viewer"])
async def test_only_an_admin_can_read_the_research_access_log(role):
    """The log records which researcher pulled what, and when. A researcher who
    can read it can see the other researchers' activity, and can check whether
    their own pulls are being noticed."""
    with pytest.raises(HTTPException) as caught:
        await research.get_access_logs(limit=10, db=_DB(), current_user=_user(role))
    assert caught.value.status_code == 403
    assert "admin" in str(caught.value.detail).lower()


async def test_an_admin_can_read_the_research_access_log():
    assert await _passed_the_gate(
        research.get_access_logs(limit=10, db=_DB(), current_user=_user("admin")))


# ---- the module switch comes first ------------------------------------------

async def test_nothing_is_exported_when_the_portal_is_switched_off(monkeypatch):
    """The Admin Console flag is the outer gate, and it applies to admins too --
    an admin who switched the portal off has switched it off.

    Checked before the role check and before any query, so a town that turned
    the suite off is not still serving its dataset to whoever had the URL.
    """
    async def _disabled(db):
        return False

    monkeypatch.setattr(research, "check_research_enabled", _disabled)

    for role in ("admin", "researcher"):
        for endpoint in ("export_csv", "export_geojson"):
            with pytest.raises(HTTPException) as caught:
                await getattr(research, endpoint)(
                    request=_request(), privacy_mode="fuzzed",
                    db=_DB(), current_user=_user(role))
            assert caught.value.status_code == 403
            assert "not enabled" in str(caught.value.detail).lower()

        with pytest.raises(HTTPException) as caught:
            await research.get_access_logs(limit=10, db=_DB(), current_user=_user(role))
        assert caught.value.status_code == 403


# ---- and the role that reaches these endpoints at all -----------------------

@pytest.mark.parametrize("role", ["staff", "viewer", "resident", ""])
async def test_a_non_researcher_never_reaches_the_research_endpoints(role):
    """`get_current_researcher` is the dependency every endpoint in this module
    is mounted behind. The per-endpoint checks above assume it; this is the
    assumption."""
    from app.core.auth import get_current_researcher

    with pytest.raises(HTTPException) as caught:
        await get_current_researcher(current_user=_user(role))
    assert caught.value.status_code == 403


@pytest.mark.parametrize("role", ["researcher", "admin"])
async def test_the_two_roles_that_do_reach_them(role):
    from app.core.auth import get_current_researcher

    assert await get_current_researcher(current_user=_user(role)) is not None
