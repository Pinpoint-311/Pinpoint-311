"""Tests for the road seed/refresh task's safety logic.

The fetch itself needs a network and a database, neither of which exists here.
What is pinned instead is everything that decides *whether to apply* a fetch --
which is where the damage would be done. A bad swap silently switches road
routing off for an entire town, and nobody notices until a county road stops
being blocked.
"""

import pytest

rd = pytest.importorskip("app.tasks.road_data")

should_swap = rd.should_swap
bbox = rd.boundary_bbox
refresh_day = rd.refresh_day_of_month


# ---- refusing a bad swap ---------------------------------------------------

def test_empty_fetch_never_replaces_existing_roads():
    """An empty response is nearly always a truncated or erroring request, not a
    town that genuinely deleted all its roads."""
    ok, reason = should_swap(1200, 0)
    assert ok is False and "no roads" in reason


def test_drastic_shrink_is_refused():
    ok, reason = should_swap(1000, 400)
    assert ok is False and "refusing" in reason


def test_small_shrink_is_allowed():
    """Roads do genuinely get removed; only a collapse is suspicious."""
    assert should_swap(1000, 950)[0] is True


def test_growth_is_allowed():
    assert should_swap(1000, 1400)[0] is True


def test_first_ever_seed_is_allowed():
    """Nothing to lose, so nothing to protect."""
    assert should_swap(0, 500)[0] is True


def test_first_seed_of_an_empty_result_is_still_refused():
    """Storing zero roads would leave the town looking seeded but resolve every
    pin as off-road -- worse than having no table at all, because it looks fine."""
    assert should_swap(0, 0)[0] is False


# ---- refresh day spreading -------------------------------------------------

def test_refresh_day_is_stable_for_a_town():
    assert refresh_day("Cranbury Township") == refresh_day("Cranbury Township")


def test_refresh_day_differs_between_towns():
    """Every deployment refreshing on the 1st would put all of them on the
    publisher's doorstep at once."""
    days = {refresh_day(n) for n in
            ["Cranbury", "Edison", "Princeton", "Montclair", "Hoboken", "Trenton", "Camden"]}
    assert len(days) > 1


def test_refresh_day_is_always_a_real_day_in_every_month():
    """29-31 would silently skip February."""
    for name in ["a", "bb", "Township of Anything", "", "Ω"]:
        assert 1 <= refresh_day(name) <= 28


def test_missing_township_name_still_produces_a_day():
    assert 1 <= refresh_day(None) <= 28


# ---- boundary envelope -----------------------------------------------------

def test_bbox_of_a_simple_polygon():
    boundary = {"geometry": {"coordinates": [[[-74.5, 40.3], [-74.4, 40.4], [-74.45, 40.35]]]}}
    assert bbox(boundary) == (-74.5, 40.3, -74.4, 40.4)


def test_bbox_handles_a_bare_geometry():
    """Boundaries arrive both as a Feature and as a naked geometry."""
    assert bbox({"coordinates": [[[-74.5, 40.3], [-74.4, 40.4]]]}) == (-74.5, 40.3, -74.4, 40.4)


def test_bbox_handles_multipolygon_nesting():
    boundary = {"geometry": {"type": "MultiPolygon", "coordinates": [
        [[[-74.5, 40.3], [-74.4, 40.4]]],
        [[[-74.7, 40.1], [-74.6, 40.2]]],
    ]}}
    assert bbox(boundary) == (-74.7, 40.1, -74.4, 40.4)


def test_bbox_of_nothing_is_none():
    """No boundary means no fetch envelope, which the caller reports rather than
    querying an entire state by accident."""
    assert bbox({}) is None
    assert bbox({"geometry": {"coordinates": []}}) is None


# ---- scheduling ------------------------------------------------------------

def test_refresh_is_registered_on_the_beat_schedule():
    from app.core.celery_app import celery_app

    assert "monthly-road-refresh" in celery_app.conf.beat_schedule
    assert "app.tasks.road_data" in celery_app.conf.include


def test_road_tasks_get_a_longer_time_limit_than_the_global():
    """The global limit is 300 s; a large township's fetch can exceed that and
    would be killed partway through."""
    from app.core.celery_app import celery_app

    assert celery_app.conf.task_time_limit <= 300
    assert rd.seed_roads.time_limit > 300
    assert rd.refresh_roads_monthly.time_limit > 300
