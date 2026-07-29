"""Tests for spatial road resolution and routing precedence.

The two failure directions are not symmetric and the tests are weighted
accordingly:

  * routing to the wrong agency costs a clerk one reassignment;
  * blocking a resident who should have been able to file turns a person away,
    and there is no override for them.

So most of what is pinned here is the fail-open behaviour and the precedence
rules that decide ties in the resident's favour.
"""

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("geoalchemy2")

rg = pytest.importorskip("app.services.road_geometry")

RoadMatch = rg.RoadMatch
choose_road = rg.choose_road
check_config = rg.check_config


def road(name, distance, *, ref=None, segment_id=1):
    return RoadMatch(
        name=name, ref=ref, distance_m=distance, segment_id=segment_id,
        source_feature_id=str(segment_id), highway_class="residential",
    )


COUNTY = {
    "name": "Middlesex County",
    "roads": ["Cranbury Rd", "CR 516"],
    "message": "County roads are maintained by Middlesex County.",
    "contacts": [{"name": "County DPW", "phone": "555-0100"}],
}
STATE = {"name": "NJDOT", "roads": ["NJ 18"], "message": "State highway.", "contacts": []}
CONFIG = {"jurisdictions": [COUNTY, STATE]}


# ---- the query -------------------------------------------------------------

def test_query_uses_indexed_distance_operators():
    """ST_DWithin does the index-accelerated cut-off and <-> keeps the GIST
    index in play for ordering. A plain ORDER BY ST_Distance would sort every
    road in town on every pin drop."""
    sql = str(rg.nearest_roads_query(40.3, -74.5, 20).compile(compile_kwargs={"literal_binds": True}))
    assert "ST_DWithin" in sql
    assert "<->" in sql
    assert "geography" in sql.lower()


def test_query_measures_in_metres_not_degrees():
    """Casting to geography is what makes the 20 in "20 metres" true. Without
    it the threshold would be 20 *degrees* and every pin would match."""
    sql = str(rg.nearest_roads_query(40.3, -74.5, 20).compile(compile_kwargs={"literal_binds": True}))
    assert sql.lower().count("geography") >= 2


# ---- fail open -------------------------------------------------------------

def test_no_roads_in_range_is_not_a_block():
    """The park-driveway case. A pin 30 m from anything is not on a road, so no
    road rule can reach it."""
    assert choose_road([], CONFIG) is None


def test_unlisted_road_is_municipal():
    assert choose_road([road("Elm St", 4.0)], CONFIG) == (road("Elm St", 4.0), None)


def test_empty_config_never_blocks():
    result = choose_road([road("Cranbury Rd", 3.0)], {})
    assert result is not None and result[1] is None


# ---- nearest wins ----------------------------------------------------------

def test_nearest_road_decides():
    """The corner-lot case: a pin on the residential street must not be
    attributed to the county road running parallel eighteen metres away."""
    result = choose_road([road("Elm St", 5.0), road("Cranbury Rd", 18.0)], CONFIG)
    assert result[0].name == "Elm St"
    assert result[1] is None


def test_nearest_road_blocks_when_claimed():
    result = choose_road([road("Cranbury Rd", 3.0), road("Elm St", 19.0)], CONFIG)
    assert result[0].name == "Cranbury Rd"
    assert result[1][0]["name"] == "Middlesex County"


def test_candidates_need_not_arrive_sorted():
    result = choose_road([road("Cranbury Rd", 18.0), road("Elm St", 2.0)], CONFIG)
    assert result[0].name == "Elm St"


def test_route_number_matches_when_name_does_not():
    result = choose_road([road("Some Local Name", 3.0, ref="County Route 516")], CONFIG)
    assert result[1] is not None and result[1][0]["name"] == "Middlesex County"


# ---- ties at intersections -------------------------------------------------

def test_town_wins_a_tie_at_an_intersection():
    """Both roads are within a couple of metres. The higher agency usually does
    own the intersection in practice, but being wrong that way turns a resident
    away while being wrong toward the town costs one reassignment."""
    result = choose_road([road("Cranbury Rd", 3.0), road("Elm St", 4.0)], CONFIG)
    assert result[0].name == "Elm St"
    assert result[1] is None


def test_tie_preference_can_be_turned_off():
    """A town that knows the county owns its intersections can say so."""
    result = choose_road(
        [road("Cranbury Rd", 3.0), road("Elm St", 4.0)], CONFIG, town_wins_ties=False
    )
    assert result[0].name == "Cranbury Rd"
    assert result[1][0]["name"] == "Middlesex County"


def test_a_clear_winner_is_not_a_tie():
    """Ten metres apart is not an intersection; the nearer road simply wins."""
    result = choose_road([road("Cranbury Rd", 3.0), road("Elm St", 14.0)], CONFIG)
    assert result[0].name == "Cranbury Rd"
    assert result[1] is not None


def test_tie_between_two_outside_agencies_goes_to_the_nearer():
    """When every tied road belongs to someone else the town cannot absorb it,
    so the nearer road decides -- deterministically, not by dict order."""
    assert choose_road([road("NJ 18", 3.0), road("Cranbury Rd", 4.0)], CONFIG)[1][0]["name"] == "NJDOT"
    assert choose_road([road("Cranbury Rd", 3.0), road("NJ 18", 4.0)], CONFIG)[1][0]["name"] == "Middlesex County"


# ---- municipal override ----------------------------------------------------

def test_town_claimed_road_wins_even_when_not_nearest():
    """A town-maintained stretch of an otherwise county road."""
    config = {"jurisdictions": [COUNTY], "municipal_roads": ["Cranbury Rd"]}
    result = choose_road([road("Cranbury Rd", 12.0), road("Elm St", 3.0)], config)
    assert result[0].name == "Cranbury Rd"
    assert result[1] is None


def test_legacy_exclusion_list_still_blocks():
    legacy = {"exclusion_list": ["CR 516"], "third_party_message": "Call the county."}
    result = choose_road([road("County Route 516", 3.0)], legacy)
    assert result[1] is not None
    assert result[1][0]["message"] == "Call the county."


# ---- config conflicts ------------------------------------------------------

KNOWN = ["Cranbury Rd", "Elm St", "NJ 18", "Main St"]


def test_same_road_claimed_by_two_jurisdictions_is_an_error():
    config = {"jurisdictions": [
        {"name": "County", "roads": ["Cranbury Rd"]},
        {"name": "NJDOT", "roads": ["Cranbury Rd"]},
    ]}
    errors = [i for i in check_config(config, KNOWN) if i.severity == "error"]
    assert len(errors) == 1
    assert errors[0].kind == "road_claimed_twice"
    assert "County" in errors[0].message and "NJDOT" in errors[0].message


def test_road_matching_nothing_is_a_warning():
    """The most common real misconfiguration: a typo that fires never, silently."""
    config = {"jurisdictions": [{"name": "County", "roads": ["Cramberry Rd"]}]}
    warnings = [i for i in check_config(config, KNOWN) if i.severity == "warning"]
    assert len(warnings) == 1
    assert warnings[0].kind == "road_matches_nothing"


def test_valid_config_produces_no_errors_or_warnings():
    config = {"jurisdictions": [{"name": "County", "roads": ["Cranbury Rd"]}]}
    assert [i for i in check_config(config, KNOWN) if i.severity in ("error", "warning")] == []


def test_municipal_override_is_informational_not_an_error():
    config = {"jurisdictions": [COUNTY], "municipal_roads": ["Cranbury Rd"]}
    issues = check_config(config, KNOWN)
    assert [i.severity for i in issues if i.kind == "municipal_override"] == ["info"]
    assert not [i for i in issues if i.severity == "error"]


def test_no_known_roads_suppresses_typo_warnings():
    """Before the road table is seeded we cannot tell a typo from a real road,
    and crying wolf would train clerks to ignore the warning."""
    config = {"jurisdictions": [{"name": "County", "roads": ["Anything At All"]}]}
    assert [i for i in check_config(config, []) if i.kind == "road_matches_nothing"] == []


# ---- parallel corridors ----------------------------------------------------

def test_intersection_overlap_is_not_flagged():
    """Every crossing overlaps. Flagging them all would be pure noise."""
    overlaps = [{"road_a": "Main St", "road_b": "Cranbury Rd", "overlap_length_m": 25}]
    assert rg.parallel_overlap_flags(overlaps, corridor_m=20) == []


def test_parallel_corridors_are_flagged():
    overlaps = [{"road_a": "NJ 18", "road_b": "Service Rd", "overlap_length_m": 400}]
    flags = rg.parallel_overlap_flags(overlaps, corridor_m=20)
    assert len(flags) == 1
    assert flags[0].kind == "parallel_corridors"
    assert "400" in flags[0].message


def test_overlap_threshold_scales_with_corridor_width():
    """A narrow corridor makes a given overlap relatively longer, so the same
    geometry is ambiguous at 8 m that was fine at 20 m."""
    overlaps = [{"road_a": "A", "road_b": "B", "overlap_length_m": 30}]
    assert rg.parallel_overlap_flags(overlaps, corridor_m=20) == []
    assert len(rg.parallel_overlap_flags(overlaps, corridor_m=8)) == 1


# ---- clerk corrections from the coverage map --------------------------------

def test_a_switched_off_stretch_cannot_be_claimed():
    """The clerk saw on the map that this piece is not really the county's."""
    config = {"jurisdictions": [COUNTY], "excluded_segments": ["7"]}
    result = choose_road([road("Cranbury Rd", 3.0, segment_id=7)], config)
    assert result[0].name == "Cranbury Rd"
    assert result[1] is None  # town handles it


def test_a_switched_off_stretch_can_still_be_the_nearest_road():
    """It is excluded from the county's rule, not deleted. The town is still
    responsible for it, and it must still beat a farther road."""
    config = {"jurisdictions": [COUNTY], "excluded_segments": ["7"]}
    result = choose_road(
        [road("Cranbury Rd", 3.0, segment_id=7), road("Elm St", 18.0, segment_id=8)], config
    )
    assert result[0].name == "Cranbury Rd"
    assert result[1] is None


def test_other_stretches_of_the_same_road_still_block():
    """Switching off one block must not disable the whole rule."""
    config = {"jurisdictions": [COUNTY], "excluded_segments": ["7"]}
    result = choose_road([road("Cranbury Rd", 3.0, segment_id=9)], config)
    assert result[1] is not None and result[1][0]["name"] == "Middlesex County"


def test_exclusions_key_on_the_publisher_feature_id():
    """Not our row id, which changes on every monthly refresh and would orphan
    every correction a clerk has made."""
    config = {"jurisdictions": [COUNTY], "excluded_segments": ["NJ-RCL-99"]}
    match = RoadMatch(name="Cranbury Rd", ref=None, distance_m=3.0, segment_id=412,
                      source_feature_id="NJ-RCL-99", highway_class="secondary")
    assert choose_road([match], config)[1] is None


def test_a_malformed_exclusion_list_is_ignored():
    for junk in ("not a list", 5, None, {}):
        config = {"jurisdictions": [COUNTY], "excluded_segments": junk}
        assert choose_road([road("Cranbury Rd", 3.0)], config)[1] is not None


# ---- trimming a rule along a road -------------------------------------------

def road_at(name, distance, fraction, *, segment_id=1):
    return RoadMatch(
        name=name, ref=None, distance_m=distance, segment_id=segment_id,
        source_feature_id=str(segment_id), highway_class="secondary",
        fraction_along=fraction,
    )


TRIMMED = {"jurisdictions": [COUNTY], "segment_trims": {"1": {"start": 0.0, "end": 0.4}}}


def test_a_pin_inside_the_trim_still_blocks():
    result = choose_road([road_at("Cranbury Rd", 3.0, 0.2)], TRIMMED)
    assert result[1] is not None and result[1][0]["name"] == "Middlesex County"


def test_a_pin_past_the_trim_is_the_towns():
    """The clerk dragged the rule back because the data ran the segment straight
    through the point where responsibility actually changes."""
    result = choose_road([road_at("Cranbury Rd", 3.0, 0.8)], TRIMMED)
    assert result[0].name == "Cranbury Rd"
    assert result[1] is None


def test_an_untrimmed_segment_of_the_same_road_is_unaffected():
    """Trimming one segment must not quietly narrow the whole rule."""
    result = choose_road([road_at("Cranbury Rd", 3.0, 0.9, segment_id=2)], TRIMMED)
    assert result[1] is not None


def test_an_unmeasurable_position_does_not_block_the_match():
    """A missing measurement is a data gap, not evidence the pin is outside the
    trim. Treating it as outside would hand the resident to the wrong agency."""
    result = choose_road([road_at("Cranbury Rd", 3.0, None)], TRIMMED)
    assert result[1] is not None


@pytest.mark.parametrize("junk", ["nope", 5, None, {"1": "bad"}, {"1": [1]}])
def test_a_malformed_trim_never_disables_a_rule(junk):
    config = {"jurisdictions": [COUNTY], "segment_trims": junk}
    assert choose_road([road_at("Cranbury Rd", 3.0, 0.5)], config)[1] is not None


def test_trim_endpoints_are_clamped_and_ordered():
    """Dragging past either end, or dragging the handles across each other, is
    normal and must not produce a rule that matches nothing."""
    t = rg.Trim(1.4, -0.3)
    assert (t.start, t.end) == (0.0, 1.0)
    assert rg.Trim(0.8, 0.2).start == 0.2


def test_a_full_length_trim_is_not_stored():
    """It is the default; keeping it would grow the config for no effect."""
    assert rg.parse_trims({"segment_trims": {"1": {"start": 0, "end": 1}}}) == {}


def test_a_zero_length_trim_is_ignored_rather_than_matching_nothing():
    """Dragging both handles together should not silently create a rule that can
    never fire -- that is the invisible-misconfiguration failure again."""
    assert rg.parse_trims({"segment_trims": {"1": {"start": 0.5, "end": 0.5}}}) == {}
