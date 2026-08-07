"""Infrastructure raises the alarm through the same machinery as connectors.

Not a second alerting path beside the first. Two paths drift, and a town finds
out which one to trust the hard way -- so a filling disk escalates, digests and
mutes exactly like a revoked API key.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services import connector_alerts as A
from app.services import system_probes as P
from app.services.connector_verification import probe_system

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


class FakeHealth:
    """Stands in for the connector_health *store*, with its real signatures.

    `snapshot` is here because the alerting path reads it: a probe that records
    a failure and then hands an empty snapshot to the dispatcher would send
    nothing, which is the silence these tests exist to rule out.
    """

    def __init__(self):
        self.successes, self.failures = [], []

    async def record_success(self, db, connector, provider=None, detail=None):
        self.successes.append(connector)

    async def record_failure(self, db, connector, detail, provider=None):
        self.failures.append((connector, detail))

    async def snapshot(self, db):
        from app.services.connector_health import Health
        out = {}
        for connector, detail in self.failures:
            out[connector] = Health(connector=connector, status="down",
                                    consecutive_failures=3, last_error=detail)
        for connector in self.successes:
            out.setdefault(connector, Health(connector=connector, status="working"))
        return out


@pytest.mark.asyncio
async def test_a_filling_disk_is_recorded_as_a_failure():
    health = FakeHealth()
    await probe_system(None, readings={"system:disk": P.classify_disk(93)}, health=health)
    assert [c for c, _ in health.failures] == ["system:disk"]
    assert "stops accepting new reports" in health.failures[0][1]


@pytest.mark.asyncio
async def test_a_healthy_disk_is_recorded_as_a_success():
    health = FakeHealth()
    await probe_system(None, readings={"system:disk": P.classify_disk(20)}, health=health)
    assert health.successes == ["system:disk"]
    assert health.failures == []


@pytest.mark.asyncio
async def test_something_we_could_not_measure_is_not_recorded_either_way():
    """A probe that cannot read the disk must not write a failure. The same
    rule the connector sweep follows: unmeasurable is not broken, and a badge
    that can never clear is worse than none."""
    health = FakeHealth()
    out = await probe_system(None, readings={"system:disk": P.classify_disk(None)}, health=health)
    assert health.successes == [] and health.failures == []
    assert out["probes"]["system:disk"] == "unmeasured"


@pytest.mark.asyncio
async def test_one_failing_probe_does_not_stop_the_others():
    class Exploding(FakeHealth):
        async def record_failure(self, db, connector, detail):
            if connector == "system:disk":
                raise RuntimeError("boom")
            await super().record_failure(db, connector, detail)

    health = Exploding()
    await probe_system(None, health=health, readings={
        "system:disk": P.classify_disk(99),
        "system:backups": P.classify_backup(None, NOW),
    })
    assert [c for c, _ in health.failures] == ["system:backups"]


@pytest.mark.asyncio
async def test_the_probe_sends_the_email_itself():
    """A probe that records a full disk and does not send the email is the same
    silence it replaces, one layer further in.

    The dispatcher here has `connector_alerts.dispatch`'s real signature --
    `healths` is required. It used to be stubbed as `async def alerts(db)`,
    matching the *call site* rather than the collaborator, so the test passed
    while production raised TypeError on every run and no probe alert email had
    ever been sent.
    """
    calls = []

    async def dispatch(db, *, healths, **kwargs):
        calls.append(list(healths))
        return {"sent": True}

    out = await probe_system(None, readings={"system:disk": P.classify_disk(95)},
                             health=FakeHealth(), alerts=dispatch)
    assert len(calls) == 1, "the probe measured a full disk and told nobody"
    assert [h.connector for h in calls[0]] == ["system:disk"]
    assert out["probes"]["system:disk"] == "failing"


@pytest.mark.asyncio
async def test_the_real_dispatcher_can_be_called_the_way_the_probe_calls_it():
    """Pins the signature itself, so the two cannot drift apart again.

    The bug was not in either module -- it was in the contract between them, and
    that is exactly what a fake on both sides cannot catch. This drives the real
    `connector_alerts.dispatch` and only fakes the things that touch the world.
    """
    sent = []

    def send(**kwargs):  # NotificationService.send_email is synchronous
        sent.append(kwargs)
        return True

    async def dispatch(db, *, healths, **kwargs):
        return await A.dispatch(db, healths=healths, send=send,
                                recipients=["clerk@town.gov"], now=NOW, **kwargs)

    await probe_system(None, readings={"system:disk": P.classify_disk(97)},
                       health=FakeHealth(), alerts=dispatch)
    assert len(sent) == 1
    assert "Disk space" in sent[0]["subject"]


def test_the_email_calls_it_something_a_person_would_say():
    assert A.label("system:disk") == "Disk space"
    assert A.label("system:backups") == "Backups"
    assert "system:" not in A.label("system:cache")


def test_a_full_disk_escalates_like_any_other_failure():
    """Same rules, no special casing: new, then escalated, then reminders on
    the broken cadence."""
    assert A.decide(level=A.AT_RISK, previous_level=None, alerted_at=None, now=NOW) == "new"
    assert A.decide(level=A.BROKEN, previous_level=A.AT_RISK,
                    alerted_at=NOW - timedelta(hours=1), now=NOW) == "escalated"


def test_a_disk_alert_can_be_muted_like_any_other():
    """A town that knows the volume is being extended on Friday should be able
    to stop the daily mail without turning off everything else."""
    assert A.decide(level=A.BROKEN, previous_level=A.BROKEN,
                    alerted_at=NOW - timedelta(days=2), now=NOW,
                    muted_until=NOW + timedelta(days=2), muted_level=A.BROKEN) is None


def test_hourly_probing_does_not_mean_hourly_email():
    """The cadence is governed by how long something has been in a state, not
    by how often it is measured -- otherwise moving the probe to hourly would
    have turned one daily email into twenty-four."""
    for hours in (1, 6, 23):
        assert A.decide(level=A.BROKEN, previous_level=A.BROKEN,
                        alerted_at=NOW - timedelta(hours=hours), now=NOW) is None
    assert A.decide(level=A.BROKEN, previous_level=A.BROKEN,
                    alerted_at=NOW - timedelta(hours=25), now=NOW) == "reminder"
