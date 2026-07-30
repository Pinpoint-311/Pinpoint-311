"""Roads follow the boundary, whichever way the boundary arrived.

Three endpoints accept a town boundary: an uploaded GeoJSON file, a Census
lookup, and the built-in search. Only the search one persisted it and fetched
roads. The other two loaded the shape into an in-memory helper and returned
"success" -- so the boundary was gone on the next restart and no road was ever
fetched for it.

Nothing said so, which is why this survived. The map drew, because the browser
still had the file it had just uploaded. The roads were missing only later, when
a resident's report could not be matched to a street.

Underneath that was a second, quieter bug. The state was worked out by looking
for a state name in the boundary's *name*. That works for the built-in search,
whose names come from OpenStreetMap and read "Montclair, Essex County, New
Jersey, United States". It does not work for a file a town uploads, which is
called `montclair.geojson` and whose properties are a FIPS code. Those resolved
to no state and fell back to the national TIGER layer -- roads appeared, so it
looked fine, but they were not the state's own NG911 centrelines, which are the
ones that know the street names and recent subdivisions.

The lookup is injected here rather than called for real -- a test suite that
needs the internet is a test suite that fails on a train. What the live service
actually returns is pinned separately, as a recorded response, so the parser is
checked against the real thing without the tests depending on reaching it.
"""

from pathlib import Path

import pytest

import asyncio

from app.services.boundary_geo import (
    boundary_centre,
    resolve_state,
    state_from_name,
)

GIS = Path(__file__).resolve().parents[1] / "app/api/gis.py"


def poly(w, s, e, n):
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def collection(geometry, properties=None):
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": geometry, "properties": properties or {}}],
    }


MONTCLAIR_NJ = poly(-74.23, 40.79, -74.19, 40.83)


# ---------------------------------------------------------------------------
# The state comes from the coordinates
# ---------------------------------------------------------------------------

def says(code):
    """A stand-in for the Census lookup that always answers `code`."""
    async def lookup(lon, lat):
        return code
    return lookup


async def unreachable(lon, lat):
    """What an air-gapped deployment, or a Census outage, looks like."""
    return None


def resolved(boundary, saved=None, lookup=None):
    return asyncio.run(resolve_state(boundary, saved, lookup=lookup or says("NJ")))


def test_an_uploaded_file_with_no_state_in_it_resolves_from_its_coordinates():
    """The bug. A county GIS export carries a FIPS code and nothing a name match
    can use, so this used to fall through to the national layer."""
    uploaded = collection(MONTCLAIR_NJ, {"NAME": "Montclair", "GEOID": "3400946260"})
    assert resolved(uploaded) == "NJ"


def test_the_search_path_resolves_the_same_way():
    """Both routes in must end up at the same state. Before, only this one did,
    and only because its name happened to contain "New Jersey"."""
    osm = collection(MONTCLAIR_NJ, {"name": "Montclair, Essex County, New Jersey, United States"})
    uploaded = collection(MONTCLAIR_NJ, {"GEOID": "3400946260"})
    assert resolved(osm) == resolved(uploaded) == "NJ"


def test_coordinates_beat_a_misleading_name():
    """A name is a label. If the file says Texas and the shape is in New Jersey,
    the shape is where the town is."""
    misnamed = collection(MONTCLAIR_NJ, {"name": "Austin, Texas, United States"})
    assert resolved(misnamed) == "NJ"


def test_coordinates_beat_a_stale_saved_setting():
    """A saved state can be left over from a boundary the town has replaced, and
    nothing clears it when the boundary changes."""
    assert resolved(collection(MONTCLAIR_NJ), saved="TX") == "NJ"


def test_the_name_is_used_when_the_lookup_cannot_be_reached():
    """An air-gapped deployment still gets the right answer for a boundary whose
    name carries the state -- which is every boundary from the search."""
    osm = collection(MONTCLAIR_NJ, {"name": "Montclair, Essex County, New Jersey, United States"})
    assert asyncio.run(resolve_state(osm, None, lookup=unreachable)) == "NJ"


def test_the_saved_setting_is_the_last_resort():
    plain = collection(MONTCLAIR_NJ, {"GEOID": "3400946260"})
    assert asyncio.run(resolve_state(plain, "nj", lookup=unreachable)) == "NJ"


def test_nothing_to_go_on_is_none_rather_than_a_guess():
    """It used to return the string "DEFAULT", which was then truncated into a
    two-character column as "DE" -- so the roads page told towns their road
    source was Delaware.

    None is the honest answer, and it costs a town only the better local road
    layer: the national fallback covers every state. A guessed neighbour would
    hand it the wrong streets.
    """
    plain = collection(MONTCLAIR_NJ, {"GEOID": "3400946260"})
    assert asyncio.run(resolve_state(plain, None, lookup=unreachable)) is None
    assert asyncio.run(resolve_state(None, None, lookup=unreachable)) is None
    # A full state name in the settings column is not a two-letter code and
    # must never be passed to one.
    assert asyncio.run(resolve_state(None, "New Jersey", lookup=unreachable)) is None


def test_a_lookup_that_raises_does_not_take_the_seeding_down():
    async def explodes(lon, lat):
        raise RuntimeError("census unreachable")

    osm = collection(MONTCLAIR_NJ, {"name": "Montclair, New Jersey"})
    assert asyncio.run(resolve_state(osm, None, lookup=explodes)) == "NJ"


def test_the_lookup_is_asked_about_the_middle_of_the_boundary():
    seen = []

    async def record(lon, lat):
        seen.append((round(lon, 3), round(lat, 3)))
        return "NJ"

    asyncio.run(resolve_state(collection(MONTCLAIR_NJ), None, lookup=record))
    assert seen == [(-74.21, 40.81)]


def test_an_explicit_centre_is_preferred_over_the_bounding_box():
    """The search path stores the centre it was given. For an L-shaped town the
    box centre can sit outside the town; the stored one does not."""
    boundary = collection(MONTCLAIR_NJ)
    boundary["center"] = {"lat": 40.80, "lng": -74.22}
    assert boundary_centre(boundary) == (-74.22, 40.80)


def test_state_names_are_still_recognised():
    assert state_from_name(collection(MONTCLAIR_NJ, {"name": "Trenton, New Jersey"})) == "NJ"
    assert state_from_name(collection(MONTCLAIR_NJ, {"name": "montclair.geojson"})) is None


def test_no_bounding_box_table_survives():
    """A bbox test was tried and got eleven of twenty-six real towns wrong,
    Montclair included -- state boxes overlap most where being wrong matters.
    A plausible wrong state is worse here than none."""
    source = (Path(__file__).resolve().parents[1] / "app/services/boundary_geo.py").read_text()
    assert "STATE_BBOX" not in source


def test_default_never_reaches_the_state_column():
    source = (Path(__file__).resolve().parents[1] / "app/tasks/road_data.py").read_text()
    assert '(state_code or "")[:2]' not in source, (
        "truncating whatever arrived turns DEFAULT into DE"
    )


# ---------------------------------------------------------------------------
# Every boundary path persists and seeds
# ---------------------------------------------------------------------------

def test_all_three_boundary_endpoints_go_through_one_helper():
    """Uploading a file, picking a Census place and using the search all have to
    end the same way: stored in settings, roads fetched. They did not."""
    source = GIS.read_text()
    assert "async def persist_boundary" in source
    # Once per endpoint: upload, census, search.
    assert source.count("await persist_boundary(") == 3, (
        "a boundary endpoint is not going through the shared helper"
    )


def test_the_helper_stores_the_boundary_and_fetches_roads():
    source = GIS.read_text()
    helper = source[source.index("async def persist_boundary"):source.index("def normalize_boundary")]
    assert "settings.township_boundary = boundary_data" in helper, "the boundary is not persisted"
    assert "await db.commit()" in helper
    assert "seed_roads" in helper, "roads are not fetched for the new boundary"


def test_seeding_still_happens_without_a_celery_worker():
    """A deployment with no worker should end up with roads rather than
    silently not. Queuing is an optimisation, not the mechanism."""
    source = GIS.read_text()
    helper = source[source.index("async def persist_boundary"):source.index("def normalize_boundary")]
    assert "seed_roads_for_boundary" in helper, "no inline fallback when the queue is unavailable"


def test_the_old_in_memory_only_upload_is_gone():
    """`upload_boundary` used to load the shape into a helper object and return
    success, which is indistinguishable from having saved it."""
    source = GIS.read_text()
    upload = source[source.index("async def upload_boundary"):source.index("async def check_point_in_boundary")]
    assert "persist_boundary" in upload, "an uploaded boundary is still not stored"


# ---------------------------------------------------------------------------
# Reading the lookup's answer without knowing its field names
# ---------------------------------------------------------------------------

def test_the_state_code_is_found_whatever_the_field_is_called():
    """The Census service could not be reached from where this was written --
    the sandbox's egress policy refuses that host -- so the exact attribute name
    is the one thing here that went unconfirmed.

    Getting it wrong would fail in the worst way available: the lookup returns
    nothing every time, the caller quietly falls back to the name match,
    uploaded boundaries keep getting the national road layer, and every test in
    this file still passes. That is the bug this change exists to fix,
    reintroduced one level down.

    So the parser does not depend on the name. These are the shapes Census
    services actually return.
    """
    from app.services.boundary_geo import state_code_in

    assert state_code_in({"STUSAB": "NJ", "NAME": "New Jersey", "GEOID": "34"}) == "NJ"
    assert state_code_in({"STUSPS": "NJ", "NAME": "New Jersey", "STATEFP": "34"}) == "NJ"
    assert state_code_in({"STATE_ABBR": "NJ", "NAME": "New Jersey"}) == "NJ"
    # Field named nothing we anticipated.
    assert state_code_in({"abbrev_2": "NJ", "GEOID": "34"}) == "NJ"
    # Abbreviation absent entirely; the full name still resolves.
    assert state_code_in({"NAME": "New Jersey", "GEOID": "34", "ALAND": 19047825962}) == "NJ"
    assert state_code_in({"stusps": "nj"}) == "NJ"


def test_a_state_whose_code_is_an_english_word_still_works():
    """OK and IN and OR are real abbreviations. Validating against the known set
    is what lets the parser search widely without inventing answers."""
    from app.services.boundary_geo import state_code_in

    assert state_code_in({"STUSPS": "OK", "NAME": "Oklahoma"}) == "OK"
    assert state_code_in({"STUSPS": "IN", "NAME": "Indiana"}) == "IN"
    assert state_code_in({"STUSPS": "OR", "NAME": "Oregon"}) == "OR"


def test_nothing_state_shaped_returns_nothing():
    from app.services.boundary_geo import state_code_in

    assert state_code_in({"GEOID": "34", "ALAND": 19047825962}) is None
    assert state_code_in({}) is None
    assert state_code_in(None) is None


def test_an_arcgis_error_payload_is_not_read_as_an_answer():
    """ArcGIS answers 200 with an {"error": ...} body for a bad query. Treating
    that as "no features" is right; treating it as a state would not be."""
    import asyncio

    from app.services.boundary_geo import state_from_coordinates

    class Fake:
        def __init__(self, payload): self.payload = payload
        async def get(self, url, params=None): return self
        def json(self): return self.payload

    err = Fake({"error": {"code": 400, "message": "Unable to complete operation"}})
    assert asyncio.run(state_from_coordinates(-74.2, 40.8, client=err)) is None

    ok = Fake({"features": [{"attributes": {"STUSPS": "NJ", "NAME": "New Jersey"}}]})
    assert asyncio.run(state_from_coordinates(-74.2, 40.8, client=ok)) == "NJ"

    empty = Fake({"features": []})
    assert asyncio.run(state_from_coordinates(-74.2, 40.8, client=empty)) is None


def test_the_query_asks_for_every_field():
    """Naming one field is the dependency this avoids."""
    import asyncio

    from app.services.boundary_geo import state_from_coordinates

    seen = {}

    class Recorder:
        async def get(self, url, params=None):
            seen.update(params or {})
            seen["url"] = url
            return self
        def json(self): return {"features": [{"attributes": {"STUSPS": "NJ"}}]}

    asyncio.run(state_from_coordinates(-74.2, 40.8, client=Recorder()))
    assert seen["outFields"] == "*"
    assert seen["geometryType"] == "esriGeometryPoint"
    assert seen["inSR"] == "4326"
    assert seen["geometry"] == "-74.2,40.8"
    assert seen["f"] == "json"


# The real response, recorded from the live service on 2026-07-30:
#   GET .../TIGERweb/State_County/MapServer/0/query
#       ?geometry=-74.209,40.825&geometryType=esriGeometryPoint&inSR=4326
#       &spatialRel=esriSpatialRelIntersects&outFields=*&returnGeometry=false&f=json
# Kept verbatim so the parser is tested against what the service sends rather
# than against what I assumed it sends -- which is the distinction that had this
# whole change resting on one unconfirmed field name.
MONTCLAIR_STATE_RESPONSE = {
    "features": [{
        "attributes": {
            "OBJECTID": 34, "STATE": "34", "GEOID": "34",
            "BASENAME": "New Jersey", "NAME": "New Jersey", "STUSAB": "NJ",
            "LSADC": "00", "MTFCC": "G4000", "FUNCSTAT": "A",
            "AREALAND": 19047825962, "AREAWATER": 3543101968,
            "CENTLAT": "+40.1072744", "CENTLON": "-074.6652012",
            "INTPTLAT": "+40.1072744", "INTPTLON": "-074.6652012",
            "OID": 27553700114373,
        }
    }]
}


def test_the_recorded_live_response_parses_to_new_jersey():
    """Layer 0 of State_County is states, the point-intersects query works, and
    the abbreviation is there. Confirmed against the service, then frozen."""
    import asyncio

    from app.services.boundary_geo import state_from_coordinates

    class Recorded:
        async def get(self, url, params=None): return self
        def json(self): return MONTCLAIR_STATE_RESPONSE

    assert asyncio.run(state_from_coordinates(-74.209, 40.825, client=Recorded())) == "NJ"


def test_the_fips_code_in_the_same_response_is_not_mistaken_for_a_state():
    """`STATE` is "34" here -- a FIPS code, two characters, and `STATE` is one
    of the keys the parser checks first. Without validating against the real
    abbreviations this returns "34" and every town gets the national layer."""
    from app.services.boundary_geo import state_code_in

    attributes = MONTCLAIR_STATE_RESPONSE["features"][0]["attributes"]
    assert attributes["STATE"] == "34", "the recording no longer matches the service"
    assert state_code_in(attributes) == "NJ"
    assert state_code_in({"STATE": "34", "LSADC": "00"}) is None


def test_the_response_still_resolves_if_the_abbreviation_field_disappears():
    """Belt and braces: BASENAME and NAME both carry the full state name."""
    from app.services.boundary_geo import state_code_in

    attributes = dict(MONTCLAIR_STATE_RESPONSE["features"][0]["attributes"])
    del attributes["STUSAB"]
    assert state_code_in(attributes) == "NJ"
