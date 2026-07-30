"""The daily sweep tests what is configured, and records what it finds.

"The credentials are stored" is a fact about our own database and stays true
forever. "The credentials work" is a fact about somebody else's service and
stops being true without anyone here doing anything -- a secret expires, a card
lapses, a departing employee's key is revoked.

Before this, the only ways to find out were an admin pressing Test at a moment
of their choosing, or a resident reporting that no email ever arrived.

The three behaviours worth pinning, because each is a way the sweep could be
actively worse than nothing:

  * an unconfigured capability is left alone, so a town that never set up text
    messages does not get an amber badge on something it switched off;
  * "cannot be checked from here" is not recorded as a failure, because a red
    badge that can never go green teaches people to ignore badges;
  * a check that raises is recorded rather than aborting the sweep, so one
    broken provider does not hide the state of the other seven.
"""

import asyncio

import pytest

# Deliberately no importorskip. The sweep's logic lives in a service that
# imports neither FastAPI nor Celery, precisely so these run in CI -- which
# installs four packages and would otherwise skip the whole file.
from app.services.connector_verification import verify_all


class FakeHealth:
    """Stands in for connector_health, recording what it was told."""

    def __init__(self):
        self.successes = []
        self.failures = []

    async def record_success(self, db, connector, provider=None):
        self.successes.append(connector)

    async def record_failure(self, db, connector, error, provider=None):
        self.failures.append((connector, str(error)))


@pytest.fixture
def sweep():
    """Drive verify_all with a chosen set of checks and configured capabilities."""
    health = FakeHealth()

    def run(checks, configured):
        async def is_configured(capability):
            return capability in configured
        summary = asyncio.run(
            verify_all(None, checks=checks, is_configured=is_configured, health=health))
        return summary, health

    return run


def ok(detail="fine"):
    async def check(db=None):
        return {"ok": True, "detail": detail}
    return check


def bad(detail="the key was rejected"):
    async def check(db=None):
        return {"ok": False, "detail": detail}
    return check


def unverifiable(detail="cannot be checked from here"):
    async def check(db=None):
        return {"ok": False, "detail": detail, "recorded": False}
    return check


def explodes(message="boom"):
    async def check(db=None):
        raise RuntimeError(message)
    return check


def test_a_working_connector_is_recorded_as_working(sweep):
    result, health = sweep({"maps": ok()}, configured={"maps"})
    assert result["checked"]["maps"] == "working"
    assert health.successes == ["maps"]
    assert health.failures == []
    assert result["failing"] == []


def test_a_broken_connector_is_recorded_with_the_providers_own_words(sweep):
    """A clerk searching the web for their error needs the real string, not our
    paraphrase of it."""
    result, health = sweep({"email": bad("535 authentication failed")}, configured={"email"})
    assert result["checked"]["email"] == "failing"
    assert result["failing"] == ["email"]
    assert health.failures == [("email", "535 authentication failed")]


def test_an_unconfigured_capability_is_left_alone(sweep):
    """The badge-noise case. Testing something a town deliberately switched off
    writes a failure, and a page full of amber badges for things nobody wanted
    is a page nobody reads."""
    called = []

    async def check(db=None):
        called.append(True)
        return {"ok": False, "detail": "not configured"}

    result, health = sweep({"sms": check}, configured=set())
    assert result["checked"]["sms"] == "not-configured"
    assert called == [], "the sweep tested a capability nobody configured"
    assert health.failures == []
    assert result["failing"] == []


def test_cannot_check_from_here_is_not_a_failure(sweep):
    """Apple MapKit, ACS and a generic HTTP gateway genuinely cannot be verified
    from the server. Recording those as failures produces a red badge that can
    never go green, whatever the town does."""
    result, health = sweep({"maps": unverifiable()}, configured={"maps"})
    assert result["checked"]["maps"] == "unverifiable"
    assert health.failures == []
    assert health.successes == []
    assert result["failing"] == []


def test_one_exploding_check_does_not_hide_the_others(sweep):
    """A sweep that aborts on the first raise reports nothing about the seven
    connectors after it, which is the state it was meant to replace."""
    result, health = sweep(
        {"ai": explodes("provider SDK blew up"), "maps": ok(), "email": bad()},
        configured={"ai", "maps", "email"},
    )
    assert result["checked"] == {"ai": "error", "maps": "working", "email": "failing"}
    assert result["failing"] == ["ai", "email"]
    assert health.successes == ["maps"]
    assert any("provider SDK blew up" in err for _, err in health.failures)


def test_an_unanswerable_configured_check_still_gets_tested():
    """If we cannot tell whether something is configured, test it. A missed
    check is worse than a redundant one, and the sweep must not propagate the
    error either way -- it runs unattended."""
    health = FakeHealth()

    async def cannot_tell(capability):
        raise RuntimeError("cannot reach the secret store")

    result = asyncio.run(verify_all(
        None, checks={"ai": explodes("provider SDK blew up")},
        is_configured=cannot_tell, health=health))
    assert result["checked"]["ai"] == "error"
    assert health.failures


def test_it_is_registered_to_run_daily():
    """A task nothing schedules is a task that never runs, and the failure mode
    is silence -- which is indistinguishable from everything being fine."""
    pytest.importorskip("celery")
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    entry = schedule.get("daily-connector-check")
    assert entry, f"not scheduled; have {sorted(schedule)}"
    assert entry["task"] == "app.tasks.connector_checks.verify_connectors"
    assert entry["schedule"] == 60 * 60 * 24
    assert "app.tasks.connector_checks" in celery_app.conf.include
