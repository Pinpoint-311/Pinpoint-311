"""Tests for pausing calls to a vendor that is down.

The retry transport handles one flaky call well. It handles a real outage
badly: every report then pays three attempts and up to eight seconds of backoff
before failing anyway, a resident waits through all of it, and the worker pool
fills with requests queued behind a service that is not coming back this
minute. Retries stop being resilience and become an amplifier -- an outage at
the county becomes an outage in the town's own intake.

`clock` is injected throughout so none of this needs to sleep.
"""

import pytest

from app.services.circuit_breaker import (
    CLOSED,
    COOLDOWN_SECONDS,
    FAIL_THRESHOLD,
    HALF_OPEN,
    MAX_COOLDOWN_SECONDS,
    OPEN,
    Breaker,
    CircuitOpen,
)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def b(clock):
    return Breaker(clock=clock)


# ---- staying out of the way when things work ---------------------------------

def test_an_unknown_connector_is_closed(b):
    assert b.state("accela") == CLOSED
    b.check("accela")  # must not raise


def test_occasional_failures_below_the_threshold_do_not_open(b):
    """Timeouts and rate limits happen. Pausing a vendor for one is worse than
    the retry it would have cost."""
    for _ in range(FAIL_THRESHOLD - 1):
        b.record_failure("accela")
    assert b.state("accela") == CLOSED
    b.check("accela")


def test_a_success_resets_the_count(b):
    """Two failures an hour apart with successes between are not an outage."""
    b.record_failure("accela")
    b.record_failure("accela")
    b.record_success("accela")
    b.record_failure("accela")
    assert b.state("accela") == CLOSED


# ---- opening -----------------------------------------------------------------

def test_it_opens_after_consecutive_failures(b):
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    assert b.state("accela") == OPEN


def test_an_open_circuit_refuses_immediately(b):
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    with pytest.raises(CircuitOpen):
        b.check("accela")


def test_the_refusal_names_the_vendor_and_when_it_will_retry(b):
    """A resident-facing message needs to be better than "try again later", and
    an operator reading a log needs to know which vendor."""
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("tyler")
    try:
        b.check("tyler")
        pytest.fail("expected CircuitOpen")
    except CircuitOpen as exc:
        assert exc.name == "tyler"
        assert exc.retry_after > 0
        assert "tyler" in str(exc)


def test_one_circuit_does_not_affect_another(b):
    """A county outage must not stop email going out."""
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    assert b.state("accela") == OPEN
    assert b.state("email") == CLOSED
    b.check("email")


# ---- recovering ---------------------------------------------------------------

def test_after_the_cooldown_it_allows_a_probe(b, clock):
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    clock.advance(COOLDOWN_SECONDS + 1)
    assert b.state("accela") == HALF_OPEN
    b.check("accela")  # the probe is admitted


def test_only_one_caller_probes_at_a_time(b, clock):
    """Everything that queued during the outage would otherwise hit a
    recovering service at once."""
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    clock.advance(COOLDOWN_SECONDS + 1)
    b.check("accela")
    with pytest.raises(CircuitOpen):
        b.check("accela")


def test_a_successful_probe_closes_the_circuit(b, clock):
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    clock.advance(COOLDOWN_SECONDS + 1)
    b.check("accela")
    b.record_success("accela")
    assert b.state("accela") == CLOSED
    b.check("accela")


def test_a_failed_probe_backs_off_further(b, clock):
    """A vendor down for hours should not be probed every minute."""
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    first = b.retry_after("accela")

    clock.advance(COOLDOWN_SECONDS + 1)
    b.check("accela")
    b.record_failure("accela")

    assert b.state("accela") == OPEN
    assert b.retry_after("accela") > first


def test_the_backoff_is_capped(b, clock):
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    for _ in range(20):
        clock.advance(MAX_COOLDOWN_SECONDS + 1)
        try:
            b.check("accela")
        except CircuitOpen:
            # Expected on most iterations; this loop is driving the cooldown
            # upward, and whether any single probe is admitted is not the point.
            pass
        b.record_failure("accela")
    assert b.retry_after("accela") <= MAX_COOLDOWN_SECONDS


def test_recovery_resets_the_backoff(b, clock):
    """A vendor that had a bad afternoon must not carry a 15-minute cooldown
    into next week."""
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    clock.advance(COOLDOWN_SECONDS + 1)
    b.check("accela")
    b.record_failure("accela")          # probe failed, cooldown doubled
    clock.advance(MAX_COOLDOWN_SECONDS)
    b.check("accela")
    b.record_success("accela")

    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    assert b.retry_after("accela") == pytest.approx(COOLDOWN_SECONDS, abs=1)


def test_reset_clears_a_cooldown(b):
    """An admin who has just fixed a credential should not wait out a cooldown
    earned by the broken one."""
    for _ in range(FAIL_THRESHOLD):
        b.record_failure("accela")
    b.reset("accela")
    assert b.state("accela") == CLOSED


# ---- guard() -------------------------------------------------------------------

@pytest.mark.asyncio
async def test_guard_returns_the_value_and_closes_on_success():
    from app.services import circuit_breaker as cb
    cb.breaker.reset()

    async def call():
        return "delivered"

    assert await cb.guard("accela", call) == "delivered"
    assert cb.breaker.state("accela") == CLOSED


@pytest.mark.asyncio
async def test_guard_reraises_the_original_error():
    """The caller needs the vendor's actual failure, not a wrapper."""
    from app.services import circuit_breaker as cb
    cb.breaker.reset()

    async def call():
        raise ValueError("422 missing parcel id")

    with pytest.raises(ValueError, match="parcel id"):
        await cb.guard("accela", call)


@pytest.mark.asyncio
async def test_guard_opens_the_circuit_after_repeated_failures():
    from app.services import circuit_breaker as cb
    cb.breaker.reset()

    async def call():
        raise RuntimeError("connection refused")

    for _ in range(FAIL_THRESHOLD):
        with pytest.raises(RuntimeError):
            await cb.guard("accela", call)

    # The next attempt is refused without calling the vendor at all.
    calls = []

    async def counted():
        calls.append(1)
        raise RuntimeError("connection refused")

    with pytest.raises(CircuitOpen):
        await cb.guard("accela", counted)
    assert calls == [], "an open circuit must not reach the vendor"


def test_the_threshold_matches_the_health_service():
    """The moment we stop calling a vendor and the moment we tell the admin it
    is down have to be the same, or the badge and the behaviour disagree."""
    from app.services import connector_health as ch
    assert FAIL_THRESHOLD == ch.DOWN_AFTER
