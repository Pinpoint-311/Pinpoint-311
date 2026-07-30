"""Stop calling a vendor that is clearly down.

The retry transport in app/integrations/base.py already handles a single call
going wrong: backoff, jitter, Retry-After, and it correctly refuses to retry a
non-idempotent request on a read timeout where the write may already have
landed. That is the right behaviour for one flaky call.

It is the wrong behaviour for a vendor that is properly down. Every report then
pays the whole retry budget -- three attempts and up to eight seconds of
backoff -- before failing anyway. A resident pressing submit waits through it,
and the worker pool fills with requests queued behind a service that is not
coming back this minute. The retries stop being resilience and become an
amplifier: an outage at the county turns into an outage in the town's own
intake.

So after enough consecutive failures the circuit opens and calls fail
immediately, with a message naming the vendor and when it will next be tried.
After a cooldown a single probe is allowed through; if it succeeds the circuit
closes, and if it fails the cooldown starts again.

State is per-process and in memory, deliberately. It is a latency guard, not a
correctness mechanism -- two workers independently discovering the same outage
costs one wasted probe each, which is not worth a shared store and the failure
modes that come with one. `connector_health` is where the durable record lives.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Consecutive failures before the circuit opens. Matched to
# connector_health.DOWN_AFTER on purpose: the point at which we stop calling a
# vendor and the point at which we tell the admin it is down should be the same
# moment, or the UI and the behaviour disagree.
FAIL_THRESHOLD = 3

# How long to stay open before allowing a probe. Long enough that a vendor
# rebooting is not hammered, short enough that a town does not sit broken after
# the vendor recovers.
COOLDOWN_SECONDS = 60.0

# Each subsequent failed probe doubles the wait, to this ceiling. A vendor down
# for hours should not get a probe every minute from every worker.
MAX_COOLDOWN_SECONDS = 15 * 60.0

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpen(RuntimeError):
    """Raised instead of making a call the circuit believes will fail.

    Carries `retry_after` so a caller can tell a resident something better than
    "try again later" -- and so the intake path can distinguish this from a
    genuine vendor error, which it should not, because to the report they are
    the same outcome.
    """

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(
            f"{name} is not responding and calls are paused for another "
            f"{int(retry_after)}s. The last few attempts all failed."
        )


@dataclass
class Circuit:
    name: str
    failures: int = 0
    opened_at: Optional[float] = None
    cooldown: float = COOLDOWN_SECONDS
    # Set while a probe is in flight, so concurrent callers do not all probe at
    # once the moment the cooldown elapses -- which would send a thundering herd
    # at a service that just came back.
    probing: bool = False


class Breaker:
    """A registry of circuits, one per connector.

    `clock` is injected so the time-dependent behaviour -- cooldown expiry,
    backoff growth -- is testable without sleeping.
    """

    def __init__(self, clock: Optional[Callable[[], float]] = None):
        import time

        self._clock = clock or time.monotonic
        self._circuits: Dict[str, Circuit] = {}
        self._lock = threading.Lock()

    def _circuit(self, name: str) -> Circuit:
        circuit = self._circuits.get(name)
        if circuit is None:
            circuit = Circuit(name=name)
            self._circuits[name] = circuit
        return circuit

    def state(self, name: str) -> str:
        with self._lock:
            return self._state(self._circuit(name))

    def _state(self, circuit: Circuit) -> str:
        if circuit.opened_at is None:
            return CLOSED
        return OPEN if (self._clock() - circuit.opened_at) < circuit.cooldown else HALF_OPEN

    def retry_after(self, name: str) -> float:
        with self._lock:
            circuit = self._circuit(name)
            if circuit.opened_at is None:
                return 0.0
            return max(0.0, circuit.cooldown - (self._clock() - circuit.opened_at))

    def check(self, name: str) -> None:
        """Raise CircuitOpen if this call should not be attempted.

        Half-open admits exactly one caller. Everyone else is refused until that
        probe reports back, so a recovering service is not hit by every request
        that queued up during the outage.
        """
        with self._lock:
            circuit = self._circuit(name)
            state = self._state(circuit)
            if state == CLOSED:
                return
            if state == HALF_OPEN and not circuit.probing:
                circuit.probing = True
                logger.info("[Breaker] %s: probing after cooldown", name)
                return
            raise CircuitOpen(name, max(0.0, circuit.cooldown - (self._clock() - circuit.opened_at)))

    def record_success(self, name: str) -> None:
        """Close the circuit and reset the backoff."""
        with self._lock:
            circuit = self._circuit(name)
            if circuit.opened_at is not None:
                logger.info("[Breaker] %s: recovered, closing circuit", name)
            circuit.failures = 0
            circuit.opened_at = None
            circuit.cooldown = COOLDOWN_SECONDS
            circuit.probing = False

    def record_failure(self, name: str) -> None:
        """Count a failure, opening or re-opening the circuit if warranted."""
        with self._lock:
            circuit = self._circuit(name)
            was_probing = circuit.probing
            circuit.probing = False
            circuit.failures += 1

            if was_probing:
                # The probe failed: the vendor is still down. Back off further
                # rather than probing again in another minute.
                circuit.cooldown = min(circuit.cooldown * 2, MAX_COOLDOWN_SECONDS)
                circuit.opened_at = self._clock()
                logger.warning("[Breaker] %s: probe failed, waiting %.0fs", name, circuit.cooldown)
                return

            if circuit.failures >= FAIL_THRESHOLD and circuit.opened_at is None:
                circuit.opened_at = self._clock()
                logger.warning("[Breaker] %s: %d consecutive failures, pausing calls for %.0fs",
                               name, circuit.failures, circuit.cooldown)

    def reset(self, name: Optional[str] = None) -> None:
        """Clear state. Used by tests, and by an admin pressing Test connection
        -- someone who has just fixed a credential should not wait out a
        cooldown earned by the broken one."""
        with self._lock:
            if name is None:
                self._circuits.clear()
            else:
                self._circuits.pop(name, None)

    def snapshot(self) -> Dict[str, str]:
        with self._lock:
            return {name: self._state(c) for name, c in self._circuits.items()}


# The process-wide instance. Imported directly rather than injected, because a
# breaker that a caller can forget to pass is a breaker that does nothing.
breaker = Breaker()


async def guard(name: str, call, *, db=None, provider: Optional[str] = None):
    """Run `call()` behind the circuit, recording the outcome to health.

    The one place the breaker and the durable health record are updated
    together, so the badge in the admin UI and the behaviour of the system
    cannot drift apart.

    CircuitOpen propagates rather than being swallowed: the caller has to decide
    what a paused vendor means for its own request, and silently returning None
    would make an outage indistinguishable from an empty result.
    """
    breaker.check(name)
    try:
        result = await call()
    except Exception as exc:
        breaker.record_failure(name)
        if db is not None:
            from app.services import connector_health
            await connector_health.record_failure(db, name, exc, provider=provider)
        raise
    breaker.record_success(name)
    if db is not None:
        from app.services import connector_health
        await connector_health.record_success(db, name, provider=provider)
    return result
