"""How old the open reports are, bucketed.

Extracted from `/system/advanced-statistics`, where it existed twice -- once
for the backlog chart and once for the SLA panel -- with identical buckets and
identical arithmetic, and where it took the whole endpoint down with a 500.

The bug was a timezone mismatch:

    now = datetime.now(timezone.utc)          # aware
    age = now - row[0].replace(tzinfo=None)   # naive
    TypeError: can't subtract offset-naive and offset-aware datetimes

`now` used to be `datetime.utcnow()`, which is naive, so stripping the tzinfo
off the database value made both sides match. A sweep that replaced every
`utcnow()` with `datetime.now(timezone.utc)` -- correct on its own terms, and
done to stop naive values being written into timestamptz columns -- made `now`
aware and left the two `.replace(tzinfo=None)` calls behind. Both lines sat
outside any try block, so the first open report in the table 500'd the whole
statistics page.

The lesson is not "be careful with timezones". It is that this arithmetic was
inline in a 600-line endpoint that the test suite cannot import, because
importing it needs FastAPI and CI installs four packages. So it lived where
nothing could check it. It is a pure function of (timestamps, now) and belongs
somewhere a test can reach.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, Optional

# In order, oldest last. The labels are rendered directly, so they are part of
# the contract with the dashboard rather than an implementation detail.
BUCKETS = ("<1 day", "1-3 days", "3-7 days", "1-2 weeks", ">2 weeks")

_EDGES = (
    (timedelta(days=1), "<1 day"),
    (timedelta(days=3), "1-3 days"),
    (timedelta(days=7), "3-7 days"),
    (timedelta(days=14), "1-2 weeks"),
)


def as_utc(moment: Optional[datetime]) -> Optional[datetime]:
    """Coerce to an aware UTC datetime, whatever we were handed.

    Both directions matter. A `timestamptz` column comes back aware, but the
    same code runs against rows written before a column was migrated, against
    SQLite in a test, and against values that have been round-tripped through
    JSON. Treating a naive value as UTC is the assumption the rest of this
    codebase already makes -- every timestamp is stored in UTC and converted to
    the town's clock only for display.

    Note this normalises *up* to aware rather than stripping *down* to naive.
    Stripping is what broke: it is silent, it produces a value that looks fine
    on its own, and it fails only at the moment of arithmetic.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def bucket_for(age: timedelta) -> str:
    """Which bucket an age falls in. Negative ages count as the youngest.

    A timestamp in the future is not a real backlog age -- it is a clock skew
    between the app server and the database, or a record imported with a bad
    date. It should not be reported as two weeks old.
    """
    for edge, label in _EDGES:
        if age < edge:
            return label
    return BUCKETS[-1]


def empty_buckets() -> Dict[str, int]:
    return {label: 0 for label in BUCKETS}


def bucket_ages(moments: Iterable[Optional[datetime]],
                now: Optional[datetime] = None) -> Dict[str, int]:
    """Count timestamps into age buckets. Never raises on a mixed-tz input.

    Rows with no timestamp are skipped rather than counted as infinitely old:
    a request with no `requested_datetime` is a data problem, and inflating the
    ">2 weeks" bucket with it would quietly overstate the backlog an
    administrator is judged on.
    """
    now = as_utc(now) or datetime.now(timezone.utc)
    counts = empty_buckets()
    for moment in moments:
        stamped = as_utc(moment)
        if stamped is None:
            continue
        counts[bucket_for(now - stamped)] += 1
    return counts
