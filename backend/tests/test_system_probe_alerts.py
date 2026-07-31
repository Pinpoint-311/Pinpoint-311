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
    def __init__(self):
        self.successes, self.failures = [], []
    async def record_success(self, db, connector):
        self.successes.append(connector)
    async def record_failure(self, db, connector, detail):
        self.failures.append((connector, detail))


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
    silence it replaces, one layer further in."""
    sent = []

    async def alerts(db):
        sent.append(True)

    await probe_system(None, readings={"system:disk": P.classify_disk(95)},
                       health=FakeHealth(), alerts=alerts)
    assert sent == [True]


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
