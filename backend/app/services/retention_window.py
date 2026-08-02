"""When a record becomes eligible for retention, in one place.

There were two answers to that question and they disagreed.

`calculate_retention_date` honoured a town's override only when it was
*longer* than the state minimum -- correct, because the minimum is a legal
floor and a records retention schedule is not something a clerk can shorten by
typing a smaller number into a settings box.

`get_records_for_archival` built its cutoff with

    retention_days = override_days if override_days else policy[...]

which takes the override whatever it is. So an override of 30 days in a state
with a seven-year minimum selected seven years of records for scrubbing, and
the function whose name says it calculates the retention date was not the one
deciding.

Nobody would notice from the outside. The run reports how many records it
archived, and that number is equally plausible either way.

This module is the single answer, and it is pure, so the preview an
administrator confirms against and the sweep that runs at 3am cannot drift
apart -- which is the whole point of showing a preview.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


def effective_retention_days(policy_days: int, override_days: Optional[int]) -> int:
    """The retention period actually in force.

    An override lengthens and never shortens. A town keeping records longer
    than the state requires is its own business; keeping them for less is not
    a setting, it is a violation, and the place to stop it is here rather than
    in a form validator somebody can bypass with a PUT.
    """
    if override_days and override_days > policy_days:
        return override_days
    return policy_days


def retention_cutoff(policy_days: int, override_days: Optional[int] = None,
                     now: Optional[datetime] = None) -> datetime:
    """Records closed before this moment are eligible."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now - timedelta(days=effective_retention_days(policy_days, override_days))


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
