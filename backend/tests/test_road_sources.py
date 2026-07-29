"""Tests for parsing road data out of whatever a state publisher returns.

None of these endpoints were reachable from the machine this was written on, so
the parsing is pinned against fixtures shaped like the real responses. That is
the honest limit of what can be verified here: the shapes are from the ArcGIS
GeoJSON spec and the NENA-STA-006 field list, not from a live call.
scripts/validate_road_sources.py exists to close the rest of that gap from a
networked machine.
"""

import pytest

rs = pytest.importorskip("app.services.road_sources")

parse = rs.parse_arcgis_features
should_keep = rs.should_keep


def feature(props, coords, geom_type="LineString"):
    return {"type": "Feature", "properties": props, "geometry": {"type": geom_type, "coordinates": coords}}


LINE = [[-74.5, 40.3], [-74.49, 40.31]]


# ---- NENA schema -----------------------------------------------------------

def test_nena_name_is_reassembled_from_its_parts():
    """NENA splits a name across eight fields. Reading St_Name alone gives
    "Main", which matches nothing a clerk would ever type."""
    segments = parse({"features": [feature(
        {"RCL_NGUID": "abc-1", "St_PreDir": "North", "St_Name": "Main", "St_PosTyp": "Street"},
        LINE,
    )]}, schema="nena")
    assert len(segments) == 1
    assert segments[0].name == "North Main Street"


def test_nena_name_omits_absent_parts_without_leaving_gaps():
    segments = parse({"features": [feature(
        {"RCL_NGUID": "abc-2", "St_Name": "Cranbury", "St_PosTyp": "Road",
         "St_PreDir": "", "St_PosDir": None},
        LINE,
    )]}, schema="nena")
    assert segments[0].name == "Cranbury Road"


def test_nena_identity_uses_the_stable_guid():
    """Clerk corrections key to this, so it has to be the publisher's own id and
    not a row number that shifts on every refresh."""
    segments = parse({"features": [feature({"RCL_NGUID": "NJ-9911", "St_Name": "Elm"}, LINE)]},
                     schema="nena")
    assert segments[0].source_feature_id == "NJ-9911"


# ---- other publishers ------------------------------------------------------

def test_tiger_style_fullname_is_found():
    segments = parse({"features": [feature({"LINEARID": "1104", "FULLNAME": "Cranbury Rd"}, LINE)]},
                     schema="tiger")
    assert segments[0].name == "Cranbury Rd"
    assert segments[0].source_feature_id == "1104"


def test_declared_field_map_wins_over_guessing():
    segments = parse(
        {"features": [feature({"OBJECTID": 7, "CompleteStreetName": "Real Name", "NAME": "Decoy"}, LINE)]},
        schema="custom", field_map={"name": "CompleteStreetName"},
    )
    assert segments[0].name == "Real Name"


def test_field_names_are_matched_case_insensitively():
    """Publishers disagree on casing for the same conceptual field."""
    segments = parse({"features": [feature({"objectid": 3, "fullname": "Elm St"}, LINE)]}, schema="custom")
    assert segments[0].name == "Elm St"


def test_unknown_schema_falls_back_to_candidate_fields():
    segments = parse({"features": [feature({"FID": 1, "StreetName": "Oak Ave"}, LINE)]}, schema="custom")
    assert segments[0].name == "Oak Ave"


def test_missing_name_is_kept_not_dropped():
    """An unnamed road can never match a clerk's list, so it can never cause a
    block -- but it can win "nearest road", which is what stops a pin on an
    unnamed service road being attributed to the county road twenty metres off."""
    segments = parse({"features": [feature({"OBJECTID": 5}, LINE)]}, schema="custom")
    assert len(segments) == 1
    assert segments[0].name is None


# ---- geometry --------------------------------------------------------------

def test_multilinestring_becomes_separate_segments():
    """A road arriving in pieces is exactly what the model expects; flattening
    the parts into one line would invent connections that do not exist."""
    segments = parse({"features": [feature(
        {"OBJECTID": 9, "FULLNAME": "Split Rd"},
        [[[-74.5, 40.3], [-74.49, 40.31]], [[-74.48, 40.32], [-74.47, 40.33]]],
        geom_type="MultiLineString",
    )]}, schema="custom")
    assert len(segments) == 2
    assert {s.source_feature_id for s in segments} == {"9", "9:1"}


def test_degenerate_one_point_line_is_dropped():
    """There is nothing to measure a distance against."""
    assert parse({"features": [feature({"OBJECTID": 1}, [[-74.5, 40.3]])]}, schema="custom") == []


def test_non_line_geometry_is_ignored():
    """A point layer here means we recorded the wrong layer id -- usually
    address points. Skip rather than storing unusable rows."""
    segments = parse({"features": [feature({"OBJECTID": 1}, [-74.5, 40.3], geom_type="Point")]},
                     schema="custom")
    assert segments == []


def test_empty_response_parses_to_nothing():
    assert parse({"features": []}, schema="custom") == []
    assert parse({}, schema="custom") == []


# ---- ingest filter ---------------------------------------------------------

@pytest.mark.parametrize("cls", ["footway", "path", "steps", "cycleway", "driveway", "parking_aisle"])
def test_non_road_classes_are_excluded(cls):
    seg = rs.FetchedSegment("1", "x", None, cls, LINE)
    assert should_keep(seg) is False


@pytest.mark.parametrize("cls", ["residential", "secondary", "primary", "tertiary", "unclassified"])
def test_real_road_classes_are_kept(cls):
    assert should_keep(rs.FetchedSegment("1", "x", None, cls, LINE)) is True


def test_unclassified_none_is_kept():
    """Most publishers do not tag a highway class at all; dropping those would
    empty the table for every non-OSM source."""
    assert should_keep(rs.FetchedSegment("1", "x", None, None, LINE)) is True


# ---- normalisation ---------------------------------------------------------

def test_segment_exposes_normalised_names_for_matching():
    seg = rs.FetchedSegment("1", "North Main Street", "County Route 516", "residential", LINE)
    assert seg.name_norm == "n main st"
    assert seg.ref_norm


# ---- the source ladder -----------------------------------------------------

def test_known_state_resolves_to_its_own_source():
    assert rs.resolve_source("NJ")["schema"] == "nena"


def test_lowercase_state_code_still_resolves():
    assert rs.resolve_source("nj")["url"] == rs.resolve_source("NJ")["url"]


def test_unknown_state_falls_back_to_tiger():
    """No town is ever left without roads because its state has no entry."""
    for code in ("WY", "ZZ", "", None):
        assert rs.resolve_source(code) is rs.STATE_ROAD_SOURCES["DEFAULT"]


def test_entry_without_a_url_falls_back():
    """Registry rows exist whose layer id was never pinned down. Attempting one
    would 404; falling through gets the town working roads instead."""
    import app.services.road_sources_registry as registry
    incomplete = {k for k, v in registry.STATE_ROAD_SOURCES.items() if not v.get("url")}
    for code in incomplete:
        assert rs.resolve_source(code) is registry.STATE_ROAD_SOURCES["DEFAULT"]
