"""Road entries limited to a stretch, route-name matching, and agency reuse.

"Example Road A (First Street to Second Street)" claims only the part of the
road between those cross streets. The first half of this file is pure: parsing,
route matching, the pair choice, the tolerance test, precedence in choose_road,
the audit diff, the config-check response and the jurisdictions-file checker.
The second half runs against a throwaway PostGIS named by GIS_LAYERS_PG_URL and
skips without one; it drops the public schema, so never point it at a real
database. All names are made up.
"""

import json
import os
import pathlib

import pytest

rm = pytest.importorskip("app.services.road_matching")
pytest.importorskip("sqlalchemy")

parse = rm.parse_road_entry
matches = rm.road_matches

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "agencies_example.json"


# ---- parsing a road entry ----------------------------------------------------

def test_limits_are_read_from_the_text():
    entry = parse("Example Road A (First Street to Second Street)")
    assert (entry.name, entry.from_street, entry.to_street) == ("Example Road A", "First Street", "Second Street")
    assert entry.has_limits
    assert entry.label == "Example Road A (First Street to Second Street)"


@pytest.mark.parametrize("text", [
    "Example Road A (from First Street to Second Street)",
    "Example Road A (between First Street and Second Street)",
    "Example Road A (First Street - Second Street)",
    "Example Road A ( First Street  to  Second Street )",
])
def test_limit_spellings(text):
    assert parse(text).label == "Example Road A (First Street to Second Street)"


def test_a_plain_entry_has_no_limits():
    entry = parse("Example Road B")
    assert entry.name == "Example Road B" and not entry.has_limits


def test_a_hyphenated_name_is_not_read_as_limits():
    assert not parse("Smith-Jones Road").has_limits
    assert parse("Old Mill Rd (Smith-Jones Rd to Route 10)").from_street == "Smith-Jones Rd"


def test_structured_entries_become_the_same_text():
    entry = parse({"name": "Example Road C", "from_street": "First Street", "to_street": "Route 10"})
    assert entry.label == "Example Road C (First Street to Route 10)"
    # One limit alone bounds nothing: the whole road.
    assert not parse({"name": "Example Road C", "from_street": "First Street"}).has_limits
    assert parse({"name": ""}) is None and parse("  ") is None


def test_structured_entries_are_flattened_for_every_reader():
    assert rm._as_list([{"name": "Oak Rd", "from_street": "A St", "to_street": "B St"}, "Elm St", ""]) == [
        "Oak Rd (A St to B St)", "Elm St",
    ]


# ---- limits do not change which road an entry names ---------------------------

def test_limits_are_not_part_of_the_road_name():
    assert matches("Example Road A (First Street to Second Street)", "Example Rd A")
    assert rm.normalize_road_name("Oak Rd (Elm St to Route 10)") == rm.normalize_road_name("Oak Road")


def test_a_route_in_the_limits_does_not_claim_that_route():
    """The whole entry used to be compared, so the "Route 10" inside the limits
    made this entry claim Route 10 itself."""
    assert not matches("Oak Road (Elm Street to Route 10)", "Route 10")
    assert not matches("Oak Road (Elm Street to Route 10)", "State Highway 10")


# ---- numbered routes ----------------------------------------------------------

@pytest.mark.parametrize("configured,detected", [
    ("Route 9", "US Highway 9"),
    ("Route 500", "County Route 500"),
    ("Route 10", "State Highway 10"),
    ("Rt 10", "NJ 10"),
])
def test_a_bare_route_matches_its_number_in_any_system(configured, detected):
    assert matches(configured, detected) and matches(detected, configured)


def test_two_explicit_systems_stay_different_roads():
    assert not matches("CR 35", "NJ 35")
    assert not matches("US 9", "County Route 9")


def test_a_spur_is_a_different_road():
    assert rm.extract_route_key("Route 501 Spur") == "SR-501-SPUR"
    assert not matches("Route 501 Spur", "County Route 501")
    assert not matches("Route 501", "Route 501 Spur")
    assert matches("Route 501 Spur", "CR 501 Spur")


def test_the_first_route_named_wins():
    """A ramp leaving Route 10 for US 1 is read as Route 10."""
    assert rm.extract_route_key("FR NJ 10 EB to US 1 NB") == "SR-10"


# ---- pure decisions -----------------------------------------------------------

rl = pytest.importorskip("app.services.road_limits")


def test_the_closest_pair_of_crossings_is_chosen():
    lines = [{"index": 0, "length_m": 1000, "from": [0.1, 0.8], "to": [0.5]}]
    assert rl.choose_limit_pair(lines) == (0, 0.8, 0.5)


def test_both_crossings_must_be_on_the_same_line():
    lines = [
        {"index": 0, "length_m": 1000, "from": [0.2], "to": []},
        {"index": 1, "length_m": 500, "from": [], "to": [0.7]},
    ]
    assert rl.choose_limit_pair(lines) is None
    assert rl.missing_side(lines) == rl.NOT_CONNECTED


def test_a_pair_at_one_point_bounds_nothing():
    assert rl.choose_limit_pair([{"index": 0, "length_m": 1000, "from": [0.5], "to": [0.5]}]) is None


def test_which_cross_street_is_missing():
    assert rl.missing_side([{"index": 0, "length_m": 9, "from": [], "to": [0.4]}]) == rl.FROM_NOT_FOUND
    assert rl.missing_side([{"index": 0, "length_m": 9, "from": [0.4], "to": []}]) == rl.TO_NOT_FOUND


def test_tolerance_at_each_end():
    # 1 km line, stretch 0.2..0.6; 25 m of slack is 0.025.
    assert rl.within_limits(0.4, 0.6, 0.2, 1000)
    assert rl.within_limits(0.62, 0.2, 0.6, 1000)
    assert rl.within_limits(0.18, 0.2, 0.6, 1000)
    assert not rl.within_limits(0.63, 0.2, 0.6, 1000)
    assert not rl.within_limits(0.1, 0.2, 0.6, 1000)
    assert rl.within_limits(None, 0.2, 0.6, 1000), "an unknown position never drops a match"


def test_cross_streets_ignore_a_directional_only_when_asked():
    known = ["East Elm Street", "Elm Street", "Example Road A", "Elmwood Avenue"]
    assert rl.cross_street_names("Elm Street", known) == ["Elm Street"]
    assert rl.cross_street_names("Elm Street", known, loose=True) == ["East Elm Street", "Elm Street"]
    assert rl.cross_street_names("Example Road A", known, exclude={"Example Road A"}) == []


def test_unresolved_limits_say_the_whole_road_is_claimed():
    res = rl.LimitResolution(entry="Example Road A (First Street to Second Street)", road="Example Road A",
                             from_street="First Street", to_street="Second Street", status=rl.FROM_NOT_FOUND)
    assert "Limits not found on the map, so the whole road is treated as theirs." in res.message
    assert "First Street was not found crossing Example Road A" in res.message
    assert res.as_dict()["resolved"] is False


def test_resolved_limits_report_their_length():
    res = rl.LimitResolution(entry="e", road="Example Road A", from_street="First Street",
                             to_street="Second Street", status=rl.RESOLVED, start=0.2, end=0.7,
                             line_length_m=3000)
    assert res.stretch_m == pytest.approx(1500)
    assert res.message == "Example Road A from First Street to Second Street: 1.5 km of road."


def test_limited_entries_come_from_every_agency_shape():
    config = {"third_party_contacts": [
        {"name": "County Road Department", "road_list": "Example Road A (First Street to Second Street), Example Road B"},
    ]}
    found = rl.limited_entries(config)
    assert [(a, e.label) for a, e in found] == [
        ("County Road Department", "Example Road A (First Street to Second Street)"),
    ]


# ---- precedence -----------------------------------------------------------------

rg = pytest.importorskip("app.services.road_geometry")


def _road(name, distance=5.0):
    return rg.RoadMatch(name=name, ref=None, distance_m=distance, segment_id=1,
                        source_feature_id="f1", highway_class="residential", fraction_along=0.5)


LIMITED = {"third_party_contacts": [
    {"name": "County Road Department", "road_list": "Example Road A (First Street to Second Street)"},
]}


def test_a_pin_inside_the_limits_is_the_agencys():
    road, claim = rg.choose_road([_road("Example Road A")], LIMITED)
    assert claim is not None and claim[0]["name"] == "County Road Department"


def test_a_pin_outside_the_limits_is_the_towns():
    outside = {"Example Road A (First Street to Second Street)"}
    road, claim = rg.choose_road([_road("Example Road A")], LIMITED, outside_limits=outside)
    assert claim is None


def test_outside_one_stretch_inside_another_of_the_same_road():
    config = {"third_party_contacts": [
        {"name": "County Road Department", "road_list": "Example Road A (First Street to Second Street)"},
        {"name": "State Highway Agency", "road_list": "Example Road A (Second Street to Route 10)"},
    ]}
    outside = {"Example Road A (First Street to Second Street)"}
    _, claim = rg.choose_road([_road("Example Road A")], config, outside_limits=outside)
    assert claim[0]["name"] == "State Highway Agency"


async def test_limits_that_cannot_be_checked_fall_back_to_the_whole_road(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("no postgis")

    monkeypatch.setattr(rl, "entries_outside", boom)

    class DB:
        def begin_nested(self):
            class Ctx:
                async def __aenter__(self_):
                    return None

                async def __aexit__(self_, *exc):
                    return False
            return Ctx()

    outside = await rg._outside_limits(DB(), LIMITED, [_road("Example Road A")], 40.0, -74.0, 20)
    assert outside == set()


# ---- config-check ---------------------------------------------------------------

pytest.importorskip("fastapi")


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _NamesDB:
    async def execute(self, *_a, **_k):
        return _Rows([("Example Road A",), ("First Street",)])


async def test_config_check_reports_each_limit_and_warns_on_the_unresolved(monkeypatch):
    from app.api import roads

    async def fake_resolve(db, entry, known_names=None, use_cache=True):
        ok = entry.to_street == "Second Street"
        return rl.LimitResolution(
            entry=entry.label, road=entry.name, from_street=entry.from_street, to_street=entry.to_street,
            status=rl.RESOLVED if ok else rl.TO_NOT_FOUND,
            start=0.1 if ok else None, end=0.4 if ok else None, line_length_m=1000 if ok else None,
        )

    monkeypatch.setattr(rl, "resolve_limits", fake_resolve)
    config = {"third_party_contacts": [{
        "name": "County Road Department",
        "road_list": "Example Road A (First Street to Second Street), Example Road A (Second Street to Third Street)",
    }]}
    out = await roads.config_check(roads.ConfigCheckRequest(routing_config=config), db=_NamesDB(), _=None)

    assert [(l["entry"], l["resolved"]) for l in out["limits"]] == [
        ("Example Road A (First Street to Second Street)", True),
        ("Example Road A (Second Street to Third Street)", False),
    ]
    assert out["limits"][0]["stretch_m"] == 300
    assert out["limits"][0]["agency"] == "County Road Department"
    warnings = [i for i in out["issues"] if i["kind"] == "road_limits_unresolved"]
    assert len(warnings) == 1 and "whole road is treated as theirs" in warnings[0]["message"]
    assert out["can_save"] is True, "an unresolved limit warns, it does not block saving"


# ---- audit of agency changes ----------------------------------------------------

def test_the_audit_names_agencies_added_removed_and_changed():
    from app.api.services import _agency_changes

    before = {"third_party_contacts": [
        {"name": "County Road Department", "road_list": "Example Road B"},
        {"name": "Old Agency", "road_list": "Example Road D"},
    ]}
    after = {"third_party_contacts": [
        {"name": "County Road Department", "road_list": "Example Road B, Example Road C"},
        {"name": "State Highway Agency", "road_list": "Route 10, Route 20"},
    ]}
    assert _agency_changes(before, after) == {
        "agencies_added": [{"name": "State Highway Agency", "roads": 2}],
        "agencies_removed": ["Old Agency"],
        "agencies_changed": ["County Road Department"],
    }
    assert _agency_changes(after, after) == {}
    assert _agency_changes(None, {"third_party_contacts": "junk"}) == {}


# ---- the jurisdictions-file checker ---------------------------------------------

def test_the_checker_reads_the_import_format():
    from app.cli.check_jurisdictions import load_agencies

    agencies = load_agencies(json.loads(FIXTURE.read_text()))
    assert [a["name"] for a in agencies] == ["County Road Department", "State Highway Agency"]
    assert agencies[0]["roads"] == [
        "Example Road A (First Street to Second Street)", "Example Road B",
        "Example Road C (First Street to Route 10)",
    ]
    with pytest.raises(ValueError):
        load_agencies({"agencies": []})
    with pytest.raises(ValueError):
        load_agencies({"agencies": [{"roads": ["x"]}]})


def test_the_checker_match_table():
    from app.cli.check_jurisdictions import load_agencies, match_rows

    agencies = load_agencies(json.loads(FIXTURE.read_text()))
    known = ["Example Rd A", "Example Road B", "State Highway 10", "First Street", "County Route 20"]
    rows = {r["entry"]: r for r in match_rows(agencies, known)}
    assert rows["Example Road A (First Street to Second Street)"]["matches"] == ["Example Rd A"]
    assert rows["Example Road A (First Street to Second Street)"]["has_limits"] is True
    assert rows["Route 10"]["matches"] == ["State Highway 10"]
    assert rows["Route 20 Spur"]["matches"] == [], "a spur is not the mainline"
    assert rows["Example Road C (First Street to Route 10)"]["matches"] == []


# ===========================================================================
# PostGIS
# ===========================================================================

PG_URL = os.environ.get("GIS_LAYERS_PG_URL")
pg = pytest.mark.skipif(not PG_URL, reason="needs a throwaway PostGIS (GIS_LAYERS_PG_URL)")

# A made-up grid near (40.0, -74.0). Example Road A runs east-west along
# lat 40.000 from lng -74.020 to -74.000 in two segments that meet at -74.010.
# First Street crosses it at -74.015, Second Street at -74.005; Third Street
# stops 10 m short of it at -74.0175 (a T-junction the publisher did not snap).
# Example Road B is a separate piece of road with the same name gap far north.
SEGMENTS = [
    ("a1", "Example Road A", [(-74.020, 40.000), (-74.010, 40.000)]),
    ("a2", "Example Road A", [(-74.010, 40.000), (-74.000, 40.000)]),
    ("f1", "First Street", [(-74.015, 39.995), (-74.015, 40.005)]),
    ("s1", "Second Street", [(-74.005, 39.995), (-74.005, 40.005)]),
    ("t1", "Third Street", [(-74.0175, 40.00009), (-74.0175, 40.005)]),
    ("x1", "Elsewhere Lane", [(-73.900, 40.100), (-73.890, 40.100)]),
]


@pytest.fixture
async def pgdb():
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app import models

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        await conn.run_sync(models.Base.metadata.create_all)
        for fid, name, coords in SEGMENTS:
            wkt = "LINESTRING(" + ", ".join(f"{x} {y}" for x, y in coords) + ")"
            await conn.execute(text(
                "INSERT INTO road_segments (source_id, source_feature_id, name, name_norm, geom) "
                "VALUES ('test', :fid, :name, :norm, ST_GeomFromText(:wkt, 4326))"
            ), {"fid": fid, "name": name, "norm": rm.normalize_road_name(name), "wkt": wkt})
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    rl.clear_cache()
    async with maker() as session:
        yield session
    await engine.dispose()


@pg
async def test_limits_resolve_between_two_crossings(pgdb):
    res = await rl.resolve_limits(pgdb, parse("Example Road A (First Street to Second Street)"), use_cache=False)
    assert res.status == rl.RESOLVED, res.message
    # 0.01 degrees of longitude at lat 40 is about 852 m.
    assert res.stretch_m == pytest.approx(852, abs=15)
    assert res.as_dict()["stretch_geojson"]["type"] == "LineString"


@pg
async def test_a_point_is_checked_against_the_stretch(pgdb):
    res = await rl.resolve_limits(pgdb, parse("Example Road A (First Street to Second Street)"), use_cache=False)
    inside = await rl.point_within(pgdb, res, 40.00005, -74.010, radius_m=20)
    near_end = await rl.point_within(pgdb, res, 40.0, -74.0048, radius_m=20)   # ~17 m past Second St
    past = await rl.point_within(pgdb, res, 40.0, -74.002, radius_m=20)        # ~255 m past
    before = await rl.point_within(pgdb, res, 40.0, -74.019, radius_m=20)
    assert (inside, near_end, past, before) == (True, True, False, False)


@pg
async def test_a_cross_street_that_stops_short_still_counts(pgdb):
    res = await rl.resolve_limits(pgdb, parse("Example Road A (Third Street to First Street)"), use_cache=False)
    assert res.status == rl.RESOLVED, res.message
    assert res.stretch_m == pytest.approx(213, abs=15)


@pg
async def test_a_missing_cross_street_falls_back_and_says_so(pgdb):
    res = await rl.resolve_limits(pgdb, parse("Example Road A (Nowhere Road to Second Street)"), use_cache=False)
    assert res.status == rl.FROM_NOT_FOUND
    assert await rl.point_within(pgdb, res, 40.0, -74.002, radius_m=20) is None
    unknown = await rl.resolve_limits(pgdb, parse("Missing Road (First Street to Second Street)"), use_cache=False)
    assert unknown.status == rl.ROAD_NOT_FOUND


@pg
async def test_a_cross_street_that_never_meets_the_road(pgdb):
    res = await rl.resolve_limits(pgdb, parse("Example Road A (First Street to Elsewhere Lane)"), use_cache=False)
    assert res.status == rl.TO_NOT_FOUND


@pg
async def test_spatial_resolution_honours_the_limits(pgdb):
    config = {"third_party_contacts": [{
        "name": "County Road Department", "phone": "555-0300",
        "road_list": "Example Road A (First Street to Second Street)",
    }]}
    inside = await rg.resolve_jurisdiction_spatial(pgdb, config, 40.00005, -74.010)
    outside = await rg.resolve_jurisdiction_spatial(pgdb, config, 40.00005, -74.002)
    assert inside is not None and inside.name == "County Road Department"
    assert outside is None, "the rest of the road stays with the town"


@pg
async def test_unresolvable_limits_claim_the_whole_road_at_runtime(pgdb):
    config = {"third_party_contacts": [{
        "name": "County Road Department", "road_list": "Example Road A (Nowhere Road to Second Street)",
    }]}
    match = await rg.resolve_jurisdiction_spatial(pgdb, config, 40.00005, -74.002)
    assert match is not None and match.name == "County Road Department"
