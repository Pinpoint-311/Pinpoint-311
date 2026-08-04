"""When a record becomes eligible for retention, in one place.

There were three answers to that question at one point and they disagreed.
Two came from the same pair of inputs -- a state "minimum" the product had
invented and a town override -- combined one way in `calculate_retention_date`
and the other way in `get_records_for_archival`, so a 30-day override in a
state we had guessed at seven years selected seven years of records in one and
thirty days of records in the other.

Both inputs are gone. There is one number now, the period the municipality
configured, and no arithmetic to get wrong. What remains here is a single
definition of the cutoff it implies, kept pure so the preview an administrator
confirms against and the sweep that runs at 3am cannot drift apart -- which is
the whole point of showing a preview.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def retention_cutoff(retention_days: int,
                     now: Optional[datetime] = None) -> datetime:
    """Records closed before this moment are eligible."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(days=retention_days)


def as_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """Naive values are UTC by this codebase's convention. See backlog_age."""
    if moment is None:
        return None
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def describe_record(record: Any, *, cutoff: datetime,
                    now: Optional[datetime] = None) -> Dict[str, Any]:
    """One row of the preview, in the terms an administrator is deciding in.

    Age is measured from the closing date, not from submission: retention runs
    from when a matter concluded, and a report open for two years is not two
    years overdue for archival.
    """
    now = as_utc(now) or datetime.now(timezone.utc)
    closed = as_utc(getattr(record, "closed_datetime", None))
    cutoff = as_utc(cutoff)

    age_days = (now - closed).days if closed else None
    over_by = (cutoff - closed).days if closed else None

    return {
        "service_request_id": getattr(record, "service_request_id", None),
        "service_name": getattr(record, "service_name", None),
        "address": getattr(record, "address", None),
        "closed_datetime": closed.isoformat() if closed else None,
        "age_days": age_days,
        # How long past eligibility it already is. A list where everything is
        # "over by 1 day" reads very differently from one where the oldest is
        # over by four years, and it is the difference between a policy that
        # has been running and one about to catch up on a decade at once.
        "days_past_retention": over_by,
    }


def summarise(rows: List[Dict[str, Any]], *, total: int,
              retention_days: int, cutoff: datetime) -> Dict[str, Any]:
    """The headline above the list.

    `total` is separate from `len(rows)` on purpose: the list is capped for the
    page, and a preview that shows fifty rows out of four thousand while
    implying fifty is the answer is exactly the kind of quiet undercount this
    screen exists to prevent.
    """
    ages = [r["age_days"] for r in rows if r["age_days"] is not None]
    return {
        "total": total,
        "showing": len(rows),
        "truncated": total > len(rows),
        "retention_days": retention_days,
        "cutoff": as_utc(cutoff).isoformat(),
        "oldest_age_days": max(ages) if ages else None,
        "newest_age_days": min(ages) if ages else None,
    }
