"""Tests for what a road-data refresh tells an admin.

The design constraint being pinned is restraint. A monthly job that emails
"nothing changed" twelve times a year gets filtered, and then the message that
mattered gets filtered with it. So most of these assert silence.

The one alert that must never be missed is a rule whose road has vanished: the
rule still exists, the console still shows it, and it can never fire again.
"""

import pytest

ra = pytest.importorskip("app.services.road_alerts")

diff = ra.diff_road_names
build = ra.build_alerts


# ---- diffing ---------------------------------------------------------------

def test_no_change_produces_no_diff():
    changes = diff(["Main St", "Elm St"], ["Elm St", "Main St"])
    assert changes.is_empty


def test_new_and_removed_roads_are_reported():
    changes = diff(["Main St"], ["Main St", "Foxglove Ct"])
    assert changes.added == ["Foxglove Ct"]
    assert changes.removed == []


def test_a_renamed_spelling_is_not_a_change():
    """A publisher switching CRANBURY RD to Cranbury Road must not read as one
    road vanishing and another appearing -- that would fire a false alarm every
    time a source tidied its casing."""
    assert diff(["CRANBURY RD"], ["Cranbury Road"]).is_empty


def test_unnamed_segments_are_ignored():
    """They are numerous, they churn, and a clerk can do nothing with them."""
    changes = diff([None, "", "Main St"], [None, "Main St"])
    assert changes.is_empty


def test_counts_are_of_distinct_named_roads_not_segments():
    changes = diff(["Main St", "Main Street", "Elm St"], ["Main St"])
    assert changes.previous_count == 2
    assert changes.current_count == 1


# ---- which roads rules depend on -------------------------------------------

def test_configured_roads_collects_from_every_shape():
    configs = [
        {"jurisdictions": [{"name": "County", "roads": ["Cranbury Rd", "CR 516"]}]},
        {"exclusion_list": ["NJ 18"], "municipal_roads": ["Main St"]},
        {"inclusion_list": "Elm St, Oak Ave"},
    ]
    assert ra.configured_roads(configs) == {
        "Cranbury Rd", "CR 516", "NJ 18", "Main St", "Elm St", "Oak Ave",
    }


def test_configured_roads_tolerates_junk():
    assert ra.configured_roads([None, "not a dict", {}, {"jurisdictions": "nope"}]) == set()


def test_broken_rules_finds_a_road_that_vanished():
    assert ra.broken_rules(["Cranbury Rd"], ["Main St", "Elm St"]) == ["Cranbury Rd"]


def test_broken_rules_matches_leniently_before_crying_wolf():
    """"CR 516" still matching "County Route 516" is not broken."""
    assert ra.broken_rules(["CR 516"], ["County Route 516"]) == []


def test_no_available_roads_reports_nothing_broken():
    """Before the table is seeded every rule would look broken. Reporting them
    would train an admin to ignore the alert that matters."""
    assert ra.broken_rules(["Cranbury Rd"], []) == []


# ---- staying quiet ---------------------------------------------------------

def test_an_uneventful_refresh_says_nothing():
    assert build(changes=ra.RoadChanges(previous_count=900, current_count=900),
                 consecutive_failures=0, last_error=None, newly_broken_rules=[]) == []


def test_a_single_failure_says_nothing():
    """One failure is a service restarting or a transient 500."""
    assert build(changes=None, consecutive_failures=1, last_error="timeout",
                 newly_broken_rules=[]) == []


def test_two_failures_still_say_nothing():
    assert build(changes=None, consecutive_failures=2, last_error="timeout",
                 newly_broken_rules=[]) == []


# ---- speaking up -----------------------------------------------------------

def test_persistent_failure_is_reported():
    alerts = build(changes=None, consecutive_failures=3, last_error="404 Not Found",
                   newly_broken_rules=[])
    assert len(alerts) == 1
    assert alerts[0].severity == "error"
    assert "404" in alerts[0].body
    # Reassure that routing still works -- the fear on reading this is that the
    # town's map has broken, and it has not.
    assert "still" in alerts[0].body


def test_a_vanished_rule_road_is_the_loudest_alert():
    alerts = build(changes=None, consecutive_failures=0, last_error=None,
                   newly_broken_rules=["Cranbury Rd"])
    assert alerts[0].severity == "error"
    assert "Cranbury Rd" in alerts[0].body
    # Must say what now happens, not just that something is wrong.
    assert "town" in alerts[0].body.lower()


def test_broken_rules_are_reported_before_failures():
    """A broken rule is a live routing defect; a failing refresh is data going
    stale. The first one is worse."""
    alerts = build(changes=None, consecutive_failures=5, last_error="boom",
                   newly_broken_rules=["Cranbury Rd"])
    assert alerts[0].severity == "error" and "Cranbury Rd" in alerts[0].body


def test_new_roads_are_informational_and_say_what_happens_by_default():
    alerts = build(
        changes=ra.RoadChanges(added=["Foxglove Ct", "Heron Dr"], previous_count=900, current_count=902),
        consecutive_failures=0, last_error=None, newly_broken_rules=[],
    )
    assert len(alerts) == 1
    assert alerts[0].severity == "info"
    assert "Foxglove Ct" in alerts[0].body
    assert "No action is needed" in alerts[0].body


def test_a_huge_change_is_summarised_rather_than_listed():
    """Nobody reads three hundred street names."""
    alerts = build(
        changes=ra.RoadChanges(added=[f"Road {i}" for i in range(300)],
                               previous_count=900, current_count=1200),
        consecutive_failures=0, last_error=None, newly_broken_rules=[],
    )
    assert "300" in alerts[0].body
    assert "too many to list" in alerts[0].body


def test_a_collapse_is_a_warning_not_a_removal_list():
    """Losing most of the roads is a truncated response, not the town deleting
    its street network. Saying the data was kept is the reassuring part."""
    alerts = build(
        changes=ra.RoadChanges(removed=[f"Road {i}" for i in range(600)],
                               previous_count=900, current_count=300),
        consecutive_failures=0, last_error=None, newly_broken_rules=[],
    )
    assert len(alerts) == 1
    assert alerts[0].severity == "warning"
    assert "truncated" in alerts[0].body
    assert "previous data was kept" in alerts[0].body


def test_the_town_name_appears_in_every_subject():
    """These land in an inbox that may cover several deployments."""
    alerts = build(
        changes=ra.RoadChanges(added=["Foxglove Ct"], previous_count=1, current_count=2),
        consecutive_failures=3, last_error="x", newly_broken_rules=["Cranbury Rd"],
        township="Cranbury Township",
    )
    assert alerts and all("Cranbury Township" in a.subject for a in alerts)
