"""Availability, and the honest limits of measuring it from inside.

There is a real time series here: a background task samples each dependency
every five minutes, writes a row, and keeps thirty days. `/uptime/stats`
divides healthy samples by total samples. That part works.

What it cannot do is measure the backend's own availability, and the shape of
the arithmetic hides that rather than admitting it. The sampler runs *inside*
the process it is reporting on, so when the backend is down it does not record
"down" -- it records nothing at all. Six hours of outage leaves a six-hour hole,
and a percentage computed as healthy/total over the samples that exist comes
back at 100%. The worse the outage, the fewer samples disagree with it.

So the denominator has to be time, not rows. This module computes how many
samples a period *should* contain and reports coverage next to the percentage.
A figure of "100% across 12 of an expected 288 checks" is a different claim from
"100% across 288", and a page that cannot tell them apart is worse than one with
no number on it, because somebody will put the first in a report to a council.

None of this makes an in-process sampler into an uptime monitor. Measuring your
own availability from inside yourself has a floor, and the honest name for what
this produces is dependency availability: whether Auth0, KMS and the rest
answered, during the windows we were up to ask.

Pure. The samples are passed in.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

# How often the background sampler runs. The expected-sample count is derived
# from this, so the two cannot drift apart without the coverage figure noticing.
SAMPLE_INTERVAL = timedelta(minutes=5)

# Below this, the percentage is not reported as a headline figure. Not a
# judgement about the service -- a statement that we did not watch it enough to
# have an opinion.
MIN_COVERAGE_PERCENT = 50.0

# A check outcome that means "this is fine".
#
# One tuple, because there were two and they disagreed. The background sampler
# counted "disabled" as healthy; the manual "Check now" button did not. So
# pressing the button on the health page recorded a switched-off service as
# *down* and dented its uptime -- the act of looking at the number made the
# number worse.
HEALTHY_STATUSES = ("healthy", "configured", "fallback", "disabled")


def uptime_status(check_status: str) -> str:
    """Normalise a health-check result into what gets stored."""
    return "healthy" if check_status in HEALTHY_STATUSES else "down"


def expected_samples(hours: float, interval: timedelta = SAMPLE_INTERVAL) -> int:
    seconds = interval.total_seconds()
    if seconds <= 0:
        return 0
    return max(1, int((hours * 3600) / seconds))


def summarise(
    *,
    total: int,
    healthy: int,
    hours: float,
    interval: timedelta = SAMPLE_INTERVAL,
    min_coverage: float = MIN_COVERAGE_PERCENT,
) -> Dict[str, Any]:
    """One service over one period, with the caveat attached to the number.

    `reliable` is False when too little of the period was actually sampled. The
    percentage is still returned -- hiding it would be its own kind of lie --
    but nothing should print it as a headline without the coverage beside it.
    """
    expected = expected_samples(hours, interval)
    coverage = min(100.0, (total / expected * 100)) if expected else 0.0
    percent = (healthy / total * 100) if total else 0.0
    missing = max(0, expected - total)
    return {
        "uptime_percent": round(percent, 2),
        "checks": total,
        "healthy": healthy,
        "expected_checks": expected,
        # The gap. If the backend was down, its own outage is in here rather
        # than in `uptime_percent`, which is exactly the point.
        "missed_checks": missing,
        "coverage_percent": round(coverage, 1),
        "reliable": coverage >= min_coverage and total > 0,
    }


def describe(summary: Dict[str, Any]) -> str:
    """A sentence that does not overstate what was measured."""
    if not summary.get("checks"):
        return "Not measured over this period."
    if not summary.get("reliable"):
        return (
            f"{summary['uptime_percent']:.1f}% across {summary['checks']} of an expected "
            f"{summary['expected_checks']} checks — too little of the period was sampled "
            f"to draw a conclusion. Missing checks usually mean the server itself was down."
        )
    if summary.get("missed_checks"):
        return (
            f"{summary['uptime_percent']:.1f}% of {summary['checks']} checks. "
            f"{summary['missed_checks']} expected checks did not run."
        )
    return f"{summary['uptime_percent']:.1f}% of {summary['checks']} checks."
