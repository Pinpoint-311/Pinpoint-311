"""Service-level agreement (SLA) evaluation.

SLAs are opt-in per service category: a category with `sla_hours` set has a
target time from submission to closure; a category with NULL has no SLA and is
simply excluded from SLA reporting (never counted as failing).

All functions here are pure so the arithmetic that produces a town's published
performance numbers is unit-tested and can't drift.

Statuses
--------
    "met"        closed within the target
    "breached"   closed after the target
    "overdue"    still open, already past the target
    "at_risk"    still open, past AT_RISK_FRACTION of the target but not yet over
    "on_track"   still open, comfortably within the target
    "no_sla"     the category has no SLA configured
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# An open request is flagged "at risk" once it has consumed this fraction of its
# target — early enough that staff can still act before it breaches.
AT_RISK_FRACTION = 0.75


def _naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalize to naive UTC.

    Request timestamps come from a timezone-aware DB column while `utcnow()` is
    naive; subtracting one from the other raises TypeError. Normalizing both
    sides keeps the arithmetic safe regardless of which form we're handed.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def hours_between(start: Optional[datetime], end: Optional[datetime]) -> Optional[float]:
    """Elapsed hours between two datetimes, or None if either is missing."""
    start, end = _naive_utc(start), _naive_utc(end)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 3600.0


def classify(
    requested_at: Optional[datetime],
    closed_at: Optional[datetime],
    sla_hours: Optional[int],
    now: Optional[datetime] = None,
) -> str:
    """Classify one request against its category's SLA target."""
    if not sla_hours or sla_hours <= 0:
        return "no_sla"
    if requested_at is None:
        return "no_sla"

    if closed_at is not None:
        elapsed = hours_between(requested_at, closed_at)
        if elapsed is None:
            return "no_sla"
        return "met" if elapsed <= sla_hours else "breached"

    # Still open — measure against the clock.
    reference = now or datetime.now(timezone.utc)
    age = hours_between(requested_at, reference)
    if age is None:
        return "no_sla"
    if age > sla_hours:
        return "overdue"
    if age >= sla_hours * AT_RISK_FRACTION:
        return "at_risk"
    return "on_track"


def compliance_rate(met: int, breached: int) -> Optional[float]:
    """Percent of *resolved* requests that met the target (None if none yet)."""
    total = met + breached
    if total == 0:
        return None
    return round(met / total * 100, 1)


def summarize_category(
    service_code: str,
    service_name: str,
    sla_hours: Optional[int],
    requests: Iterable[Dict[str, Any]],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate SLA performance for one service category.

    `requests` items need "requested_datetime" and "closed_datetime" keys.
    """
    counts = {"met": 0, "breached": 0, "overdue": 0, "at_risk": 0, "on_track": 0}
    resolution_hours: List[float] = []

    for r in requests:
        status = classify(r.get("requested_datetime"), r.get("closed_datetime"), sla_hours, now)
        if status in counts:
            counts[status] += 1
        if r.get("closed_datetime") is not None:
            elapsed = hours_between(r.get("requested_datetime"), r.get("closed_datetime"))
            if elapsed is not None:
                resolution_hours.append(elapsed)

    avg_resolution = round(sum(resolution_hours) / len(resolution_hours), 1) if resolution_hours else None
    rate = compliance_rate(counts["met"], counts["breached"])

    return {
        "service_code": service_code,
        "service_name": service_name,
        "sla_hours": sla_hours,
        "resolved": counts["met"] + counts["breached"],
        "met": counts["met"],
        "breached": counts["breached"],
        "open_overdue": counts["overdue"],
        "open_at_risk": counts["at_risk"],
        "open_on_track": counts["on_track"],
        "compliance_rate": rate,
        "avg_resolution_hours": avg_resolution,
        # How the average compares to the promise — negative is ahead of target.
        "avg_vs_target_hours": (
            round(avg_resolution - sla_hours, 1) if (avg_resolution is not None and sla_hours) else None
        ),
    }


def overall_summary(categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll per-category summaries up into headline numbers."""
    met = sum(c["met"] for c in categories)
    breached = sum(c["breached"] for c in categories)
    return {
        "categories_with_sla": len(categories),
        "resolved": met + breached,
        "met": met,
        "breached": breached,
        "open_overdue": sum(c["open_overdue"] for c in categories),
        "open_at_risk": sum(c["open_at_risk"] for c in categories),
        "compliance_rate": compliance_rate(met, breached),
    }
