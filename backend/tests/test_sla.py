"""Tests for SLA evaluation — the arithmetic behind a town's published
service-level performance, so the numbers can't silently drift."""

from datetime import datetime, timedelta, timezone

from app.services.sla import (
    classify,
    compliance_rate,
    hours_between,
    overall_summary,
    summarize_category,
)

NOW = datetime(2026, 7, 27, 12, 0, 0)


def _req(hours_ago: float, closed_after: float = None):
    """Build a request dict submitted `hours_ago`, optionally closed after N hours."""
    requested = NOW - timedelta(hours=hours_ago)
    closed = requested + timedelta(hours=closed_after) if closed_after is not None else None
    return {"requested_datetime": requested, "closed_datetime": closed}


# ---- opt-in behavior: no SLA configured is never a failure ------------------

def test_no_sla_configured_is_not_a_breach():
    assert classify(NOW - timedelta(days=30), None, None, NOW) == "no_sla"
    assert classify(NOW - timedelta(days=30), None, 0, NOW) == "no_sla"


# ---- closed requests -------------------------------------------------------

def test_closed_within_target_is_met():
    assert classify(NOW - timedelta(hours=10), NOW - timedelta(hours=2), 24, NOW) == "met"


def test_closed_after_target_is_breached():
    requested = NOW - timedelta(hours=50)
    closed = requested + timedelta(hours=40)
    assert classify(requested, closed, 24, NOW) == "breached"


def test_closed_exactly_at_target_counts_as_met():
    requested = NOW - timedelta(hours=30)
    closed = requested + timedelta(hours=24)
    assert classify(requested, closed, 24, NOW) == "met"


# ---- open requests ---------------------------------------------------------

def test_open_past_target_is_overdue():
    assert classify(NOW - timedelta(hours=30), None, 24, NOW) == "overdue"


def test_open_past_75_percent_is_at_risk():
    # 20h into a 24h target = 83% consumed.
    assert classify(NOW - timedelta(hours=20), None, 24, NOW) == "at_risk"


def test_open_early_is_on_track():
    assert classify(NOW - timedelta(hours=2), None, 24, NOW) == "on_track"


# ---- timezone safety (DB gives aware datetimes; utcnow() is naive) ---------

def test_mixed_timezone_awareness_does_not_raise():
    aware = (NOW - timedelta(hours=10)).replace(tzinfo=timezone.utc)
    assert classify(aware, None, 24, NOW) == "on_track"
    assert hours_between(aware, NOW) == 10.0


# ---- rates -----------------------------------------------------------------

def test_compliance_rate_math():
    assert compliance_rate(9, 1) == 90.0
    assert compliance_rate(0, 4) == 0.0
    assert compliance_rate(0, 0) is None  # nothing resolved yet -> unknown, not 0%


# ---- category summary ------------------------------------------------------

def test_summarize_category_counts_and_average():
    reqs = [
        _req(50, closed_after=10),   # met
        _req(50, closed_after=40),   # breached
        _req(30),                    # open, overdue (30h > 24h)
        _req(20),                    # open, at risk
        _req(1),                     # open, on track
    ]
    s = summarize_category("pothole", "Pothole", 24, reqs, NOW)
    assert s["resolved"] == 2
    assert s["met"] == 1
    assert s["breached"] == 1
    assert s["open_overdue"] == 1
    assert s["open_at_risk"] == 1
    assert s["open_on_track"] == 1
    assert s["compliance_rate"] == 50.0
    assert s["avg_resolution_hours"] == 25.0      # (10 + 40) / 2
    assert s["avg_vs_target_hours"] == 1.0        # 25 - 24, i.e. 1h over target


def test_summarize_category_with_no_requests_is_unknown_not_zero():
    s = summarize_category("tree", "Tree", 48, [], NOW)
    assert s["resolved"] == 0
    assert s["compliance_rate"] is None
    assert s["avg_resolution_hours"] is None


# ---- overall rollup --------------------------------------------------------

def test_overall_summary_aggregates_categories():
    cats = [
        summarize_category("a", "A", 24, [_req(50, 10), _req(50, 40)], NOW),
        summarize_category("b", "B", 24, [_req(50, 5), _req(30)], NOW),
    ]
    o = overall_summary(cats)
    assert o["categories_with_sla"] == 2
    assert o["met"] == 2
    assert o["breached"] == 1
    assert o["resolved"] == 3
    assert o["open_overdue"] == 1
    assert o["compliance_rate"] == 66.7
