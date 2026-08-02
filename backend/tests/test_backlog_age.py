"""The 500 that took the statistics page down.

`/system/advanced-statistics` returned 500 on every request. The cause:

    now = datetime.now(timezone.utc)          # aware
    age = now - row[0].replace(tzinfo=None)   # naive
    TypeError: can't subtract offset-naive and offset-aware datetimes

`now` had been `datetime.utcnow()`, which is naive, so stripping the tzinfo off
the database value made both sides agree. A sweep replaced every `utcnow()`
with `datetime.now(timezone.utc)` -- right on its own terms, and done to stop
naive values being written into timestamptz columns -- and left the two
`.replace(tzinfo=None)` calls behind. Neither line was inside a try block, so
the first open report in the table took out the whole endpoint.

Which is the actual lesson: this was a pure function of (timestamps, now)
living inline in a 600-line endpoint that the CI suite cannot import, because
importing it needs FastAPI and CI installs four packages. It sat where nothing
could test it, in a file too big to read, and shipped.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.backlog_age import (
    BUCKETS, as_utc, bucket_ages, bucket_for, empty_buckets,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def test_an_aware_now_and_a_naive_row_do_not_raise():
    """The regression, exactly. A `timestamptz` column normally hands back an
    aware value, but a naive one has to be survivable -- it is what SQLite
    returns, what a pre-migration row can hold, and what a JSON round-trip
    produces."""
    naive = datetime(2026, 8, 2, 6, 0)          # no tzinfo
    counts = bucket_ages([naive], NOW)
    assert counts["<1 day"] == 1


def test_the_two_forms_land_in_the_same_bucket():
    """Because a naive value is UTC by this codebase's convention. If it were
    read as local time the same report would move buckets depending on where
    the server is."""
    naive = datetime(2026, 7, 30, 12, 0)
    aware = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    assert bucket_ages([naive], NOW) == bucket_ages([aware], NOW)


def test_a_row_in_another_timezone_is_converted_not_stripped():
    """Stripping would read 08:00-04:00 as 08:00 UTC and make the report four
    hours younger than it is."""
    eastern = datetime(2026, 8, 2, 8, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert as_utc(eastern) == datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
    assert bucket_ages([eastern], NOW)["<1 day"] == 1


@pytest.mark.parametrize("age,expected", [
    (timedelta(0), "<1 day"),
    (timedelta(hours=23, minutes=59), "<1 day"),
    (timedelta(days=1), "1-3 days"),
    (timedelta(days=2, hours=23), "1-3 days"),
    (timedelta(days=3), "3-7 days"),
    (timedelta(days=6, hours=23), "3-7 days"),
    (timedelta(days=7), "1-2 weeks"),
    (timedelta(days=13, hours=23), "1-2 weeks"),
    (timedelta(days=14), ">2 weeks"),
    (timedelta(days=400), ">2 weeks"),
])
def test_the_boundaries_are_where_the_labels_say(age, expected):
    """Each edge is inclusive on the upper bucket. "1-3 days" starting at
    exactly 24h is what the label promises."""
    assert bucket_for(age) == expected


def test_a_future_timestamp_is_not_reported_as_ancient():
    """Clock skew between the app server and the database, or a record imported
    with a bad date. Counting it as two weeks old would overstate a backlog an
    administrator is judged on."""
    future = NOW + timedelta(hours=3)
    assert bucket_ages([future], NOW)["<1 day"] == 1
    assert bucket_ages([future], NOW)[">2 weeks"] == 0


def test_a_missing_timestamp_is_skipped_not_counted_as_old():
    counts = bucket_ages([None, NOW - timedelta(hours=2)], NOW)
    assert sum(counts.values()) == 1
    assert counts["<1 day"] == 1


def test_every_bucket_is_present_even_with_no_data():
    """The dashboard renders the keys directly; a missing one is a blank
    chart segment rather than a zero."""
    assert bucket_ages([], NOW) == empty_buckets()
    assert set(empty_buckets()) == set(BUCKETS)


def test_the_counts_add_up():
    moments = [
        NOW - timedelta(hours=1),
        NOW - timedelta(days=2),
        NOW - timedelta(days=5),
        NOW - timedelta(days=10),
        NOW - timedelta(days=30),
        NOW - timedelta(days=31),
    ]
    counts = bucket_ages(moments, NOW)
    assert counts == {"<1 day": 1, "1-3 days": 1, "3-7 days": 1, "1-2 weeks": 1, ">2 weeks": 2}
    assert sum(counts.values()) == len(moments)


def test_as_utc_leaves_none_alone():
    assert as_utc(None) is None


# ---- and the endpoint that had the bug ----

def test_the_statistics_endpoint_no_longer_strips_timezones():
    """The specific line. `.replace(tzinfo=None)` on a value about to be
    subtracted from an aware `now` is the bug, and it is a natural thing to
    write when a type error says the two do not match."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    assert "replace(tzinfo=None)" not in source, (
        "system.py is stripping tzinfo again; use backlog_age.as_utc, which "
        "normalises up to aware rather than down to naive"
    )


def test_the_endpoint_uses_the_shared_bucketing():
    """It had two copies of this loop -- the backlog chart and the SLA panel --
    with identical buckets and identical arithmetic, so the bug was present
    twice and had to be fixed twice."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app/api/system.py").read_text()
    assert source.count("bucket_ages(") >= 2
