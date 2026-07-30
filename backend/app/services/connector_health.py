"""Track whether each integration is actually working.

The setup page's badges answered "are the credentials stored" -- a question
about our own database, which is always answerable and rarely the one being
asked. A clerk reading a green tick believes something stronger: that reports
are reaching the county and emails are going out. Those look identical right up
until a resident complains.

Three states, and the middle one is the point:

    working   a real call succeeded recently
    failing   a real call failed, and here is what the provider said
    unknown   nothing has called it, so we genuinely do not know

Collapsing `unknown` into either of the others is how an expired key survives
for a month. A connector nobody has exercised is not healthy; it is unobserved.
A manual Test button has the same weakness from the other side -- it proves the
credential worked once, at a moment chosen by the person least likely to be
surprised by the answer.

Nothing here raises. Health reporting that can break the thing it reports on is
worse than no health reporting, so every function swallows its own errors: a
failed write loses one data point, and losing a resident's report to a
bookkeeping bug would be indefensible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# How long a success stays meaningful. Past this a connector is reported as
# stale rather than working: the last real evidence is old enough that a key
# could have been revoked, a card could have expired, or a vendor could have
# changed a scope, and we would not know.
FRESH_FOR = timedelta(days=7)

# Failures before "failing" becomes "down". One failed call is a blip -- a
# timeout, a redeploy, a rate limit -- and paging a clerk for it teaches them to
# ignore the badge.
DOWN_AFTER = 3

ERROR_MAX_CHARS = 500

WORKING = "working"
FAILING = "failing"
DOWN = "down"
STALE = "stale"
UNKNOWN = "unknown"


@dataclass
class Health:
    """A connector's state, as the admin UI needs it."""

    connector: str
    status: str = UNKNOWN
    provider: Optional[str] = None
    last_success_at: Optional[datetime] = None
    last_error_at: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0

    @property
    def ok(self) -> bool:
        return self.status == WORKING

    def summary(self) -> str:
        """One line for a clerk, naming the provider's own words when failing."""
        if self.status == UNKNOWN:
            return "Not used yet — nothing has called this"
        if self.status == WORKING:
            return "Working"
        if self.status == STALE:
            return "No recent activity — last worked more than a week ago"
        detail = f" — {self.last_error}" if self.last_error else ""
        if self.status == DOWN:
            return f"Failing repeatedly ({self.consecutive_failures} in a row){detail}"
        return f"Last call failed{detail}"


def classify(row: Any, *, now: Optional[datetime] = None) -> str:
    """Derive the status from stored counters.

    Pure, so the interesting decisions -- when a blip becomes an outage, when a
    success goes stale -- are testable without a database.
    """
    now = now or datetime.now(timezone.utc)
    failures = getattr(row, "consecutive_failures", 0) or 0
    last_success = getattr(row, "last_success_at", None)
    last_error = getattr(row, "last_error_at", None)

    if failures >= DOWN_AFTER:
        return DOWN
    if failures > 0:
        return FAILING
    if last_success is None:
        # An error with no success ever is still a failure, not "unknown" --
        # something tried and could not.
        return FAILING if last_error else UNKNOWN

    if last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)
    return WORKING if (now - last_success) <= FRESH_FOR else STALE


def to_health(row: Any, *, now: Optional[datetime] = None) -> Health:
    return Health(
        connector=row.connector,
        status=classify(row, now=now),
        provider=getattr(row, "provider", None),
        last_success_at=getattr(row, "last_success_at", None),
        last_error_at=getattr(row, "last_error_at", None),
        last_error=getattr(row, "last_error", None),
        consecutive_failures=getattr(row, "consecutive_failures", 0) or 0,
        total_successes=getattr(row, "total_successes", 0) or 0,
        total_failures=getattr(row, "total_failures", 0) or 0,
    )


def clean_error(exc: Any) -> str:
    """The provider's message, trimmed and stripped of anything secret.

    Provider errors sometimes echo the request, and the request contains the
    credential. Storing that would put a key in a table the admin UI renders
    and the support process copy-pastes out of.
    """

    text = sanitize_for_log(str(exc)).strip()
    return text[:ERROR_MAX_CHARS] if text else "Unknown error"


async def _row(db, connector: str):
    from sqlalchemy import select

    from app.models import ConnectorHealth

    result = await db.execute(
        select(ConnectorHealth).where(ConnectorHealth.connector == connector)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = ConnectorHealth(connector=connector, consecutive_failures=0,
                              total_successes=0, total_failures=0)
        db.add(row)
    return row


async def record_success(db, connector: str, provider: Optional[str] = None) -> None:
    """A real call worked. Never raises."""
    try:
        now = datetime.now(timezone.utc)
        row = await _row(db, connector)
        row.provider = provider or row.provider
        row.last_attempt_at = now
        row.last_success_at = now
        # Reset, not decrement: the connector demonstrably works right now, and
        # carrying old failures forward would keep it amber after it recovered.
        row.consecutive_failures = 0
        row.last_error = None
        row.total_successes = (row.total_successes or 0) + 1
        await db.commit()
    except Exception as exc:
        logger.warning("[Health] could not record success for %s: %s",
                       sanitize_for_log(connector), exc)


async def record_failure(db, connector: str, error: Any,
                         provider: Optional[str] = None) -> None:
    """A real call failed. Never raises."""
    try:
        now = datetime.now(timezone.utc)
        row = await _row(db, connector)
        row.provider = provider or row.provider
        row.last_attempt_at = now
        row.last_error_at = now
        row.last_error = clean_error(error)
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.total_failures = (row.total_failures or 0) + 1
        await db.commit()
    except Exception as exc:
        logger.warning("[Health] could not record failure for %s: %s",
                       sanitize_for_log(connector), exc)


async def snapshot(db) -> Dict[str, Health]:
    """Every connector's health, keyed by connector name. Never raises."""
    try:
        from sqlalchemy import select

        from app.models import ConnectorHealth

        result = await db.execute(select(ConnectorHealth))
        return {r.connector: to_health(r) for r in result.scalars().all()}
    except Exception as exc:
        logger.warning("[Health] could not read connector health: %s", exc)
        return {}


def worst_first(healths: List[Health]) -> List[Health]:
    """Order for display: the ones needing attention at the top.

    `unknown` deliberately outranks `working`. A connector nobody has exercised
    is the one most likely to be quietly broken, and sorting it below the
    healthy ones buries exactly the thing worth looking at.
    """
    rank = {DOWN: 0, FAILING: 1, STALE: 2, UNKNOWN: 3, WORKING: 4}
    return sorted(healths, key=lambda h: (rank.get(h.status, 9), h.connector))
