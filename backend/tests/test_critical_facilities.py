"""Critical-infrastructure proximity: the local facility store and admin layers.

Two halves, like test_polygon_context_layers.py. The first needs only the app's
modules: OSM tag classification, node/way/relation geometry, the layer-name
rules, the Overpass fetch (mocked) and the guarantee that the per-report path
has no network client in it. The second is spatial and runs against a
throwaway PostGIS named by GIS_LAYERS_PG_URL (postgresql+asyncpg://...);
without it those tests skip. Each PG test starts from an empty schema, so never
point it at a real database.

All coordinates are made up: a square of nowhere around (-75.000, 41.000).
"""

import inspect
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("geoalchemy2")
pytest.importorskip("httpx")

from app.services import critical_facilities as cf  # noqa: E402


# ------------------------------------------------------------------ helpers

def node(osm_id, lon, lat, **tags):
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "tags": tags}


def ring(x0, y0, w, h):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h), (x0, y0)]


def pts(coords):
    return [{"lat": y, "lon": x} for x, y in coords]


def way(osm_id, coords, **tags):
    return {"type": "way", "id": osm_id, "geometry": pts(coords), "tags": tags}


# --------------------------------------------------------- classification

@pytest.mark.parametrize("tags,kind", [
    ({"amenity": "hospital"}, "hospital"),
    ({"healthcare": "hospital"}, "hospital"),
    ({"amenity": "clinic"}, "clinic"),
    ({"healthcare": "clinic"}, "clinic"),
    ({"healthcare": "urgent_care"}, "clinic"),
    ({"amenity": "clinic", "healthcare": "hospital"}, "hospital"),
    ({"amenity": "school"}, "school"),
    ({"amenity": "fire_station"}, "fire_station"),
    ({"amenity": "police"}, "police"),
    ({"emergency": "ambulance_station"}, "ambulance_station"),
    ({"amenity": "nursing_home"}, "nursing_home"),
    ({"amenity": "social_facility", "social_facility": "assisted_living"}, "nursing_home"),
    ({"emergency": "fire_hydrant"}, None),
    ({"amenity": "social_facility", "social_facility": "food_bank"}, None),
    ({"healthcare": "pharmacy"}, None),
    ({}, None),
])
def test_osm_tags_classify_into_the_kinds_and_hydrants_are_not_one(tags, kind):
    assert cf.classify(tags) == kind


def test_the_query_asks_for_everything_once_with_outlines_and_a_real_timeout():
    q = cf.build_query((-75.01, 40.99, -74.99, 41.01))
    assert "[timeout:90]" in q and "out geom" in q
    assert q.count("nwr[") == 4 and "node[" not in q and "way[" not in q
    assert "around" not in q and "fire_hydrant" not in q
    # Overpass bboxes are (south, west, north, east).
    assert "(40.990000,-75.010000,41.010000,-74.990000)" in q


# ----------------------------------------------------------------- geometry

def test_a_node_is_a_point_and_a_closed_way_a_polygon():
    assert cf.element_geometry(node(1, -75.0, 41.0)) == {"type": "Point", "coordinates": [-75.0, 41.0]}
    g = cf.element_geometry(way(2, ring(-75.0, 41.0, 0.001, 0.001)))
    assert g["type"] == "Polygon" and g["coordinates"][0][0] == g["coordinates"][0][-1]
    g = cf.element_geometry(way(3, [(-75.0, 41.0), (-75.001, 41.001)]))
    assert g["type"] == "LineString"


def test_a_multipolygon_relation_joins_its_split_outer_ways_and_drops_inners():
    x0, y0 = -75.0, 41.0
    # The outer ring in two halves, the second one drawn backwards.
    a = [(x0, y0), (x0 + 0.01, y0), (x0 + 0.01, y0 + 0.01)]
    b = [(x0, y0), (x0, y0 + 0.01), (x0 + 0.01, y0 + 0.01)]
    rel = {"type": "relation", "id": 9, "tags": {"amenity": "hospital", "type": "multipolygon"},
           "members": [
               {"type": "way", "ref": 1, "role": "outer", "geometry": pts(a)},
               {"type": "way", "ref": 2, "role": "outer", "geometry": pts(b)},
               {"type": "way", "ref": 3, "role": "inner", "geometry": pts(ring(x0 + 0.004, y0 + 0.004, 0.001, 0.001))},
           ]}
    g = cf.element_geometry(rel)
    assert g["type"] == "MultiPolygon" and len(g["coordinates"]) == 1
    outer = g["coordinates"][0][0]
    assert outer[0] == outer[-1] and len(outer) == 5
    assert {tuple(p) for p in outer} == {tuple(map(float, p)) for p in a + b}


def test_a_relation_that_never_closes_or_is_only_nodes_keeps_its_coordinates():
    open_rel = {"type": "relation", "id": 10, "tags": {"amenity": "school"},
                "members": [{"type": "way", "ref": 1, "role": "outer",
                             "geometry": pts([(-75.0, 41.0), (-75.01, 41.0)])}]}
    assert cf.element_geometry(open_rel)["type"] == "MultiLineString"
    site = {"type": "relation", "id": 11, "tags": {"amenity": "school", "type": "site"},
            "members": [{"type": "node", "ref": 5, "role": "", "lat": 41.0, "lon": -75.0}]}
    assert cf.element_geometry(site) == {"type": "MultiPoint", "coordinates": [[-75.0, 41.0]]}


def test_parse_keeps_named_kinds_drops_the_rest_and_deduplicates():
    els = [
        node(1, -75.0, 41.0, amenity="clinic", name="Example Urgent Care"),
        node(1, -75.0, 41.0, amenity="clinic", name="Example Urgent Care"),
        node(2, -75.0, 41.0, emergency="fire_hydrant"),
        way(3, ring(-75.0, 41.0, 0.001, 0.001), amenity="school"),
        {"type": "way", "id": 4, "tags": {"amenity": "police"}},  # no geometry
    ]
    out = cf.parse_elements(els)
    assert [(f["osm_type"], f["osm_id"], f["kind"], f["name"]) for f in out] == [
        ("node", 1, "clinic", "Example Urgent Care"), ("way", 3, "school", None)]


# --------------------------------------------------------------- layer names

@pytest.mark.parametrize("name,kind", [
    ("Fire Hydrants", None),
    ("Hydrants - Fire", None),
    ("Storm Drains", None),
    ("School Zone Signs", None),
    ("Streetlights", None),
    ("Traffic Signals", None),
    ("Water Systems", None),           # "ems" inside a word
    ("School Zones", None),            # a zone, used for containment instead
    ("Fire Stations", "fire_station"),
    ("Fire Department", "fire_station"),
    ("Firehouses", "fire_station"),
    ("Hospitals", "hospital"),
    ("Urgent Care Centers", "clinic"),
    ("EMS Stations", "ambulance_station"),
    ("Police", "police"),
    ("Public Schools", "school"),
    ("Assisted Living Facilities", "nursing_home"),
])
def test_layer_names_match_whole_words_and_never_assets(name, kind):
    assert cf.layer_kind(name) == kind


def test_school_zone_layers_are_recognised():
    assert cf.is_school_zone_layer("School Zones")
    assert cf.is_school_zone_layer("school zone")
    assert not cf.is_school_zone_layer("Schools")
    assert not cf.is_school_zone_layer("School Zone Signs")


def test_entries_format_like_the_old_strings():
    assert cf.format_entry({"label": "Hospital", "name": "General", "distance_m": 122.6}) == "Hospital: General (123m)"
    assert cf.format_entry({"label": "School", "name": None, "distance_m": 5}) == "School: unnamed school (5m)"


# ------------------------------------------------------------- the fetch

class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    async def post(self, url, data=None, headers=None):
        self.calls.append((url, data, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


async def test_fetch_moves_on_from_a_timeout_remark_and_a_dead_mirror():
    ok = {"elements": [node(1, -75.0, 41.0, amenity="hospital", name="General")]}
    client = FakeClient([
        FakeResponse(200, {"remark": "runtime error: Query timed out in \"query\" at line 3", "elements": []}),
        TimeoutError("read timeout"),
        FakeResponse(200, ok),
    ])
    facilities, used = await cf.fetch_facilities(
        (-75.01, 40.99, -74.99, 41.01), client=client,
        urls=["https://a.example/api/interpreter", "https://b.example/api/interpreter"], pause_s=0)
    assert [f["name"] for f in facilities] == ["General"]
    assert used == "https://a.example/api/interpreter"  # second round, first mirror
    assert len(client.calls) == 3
    for _, data, headers in client.calls:
        assert "nwr[" in data["data"]
        ua = headers["User-Agent"]
        assert ua.startswith("Pinpoint311/") and "critical-facilities" in ua and "@" not in ua


async def test_fetch_raises_when_every_try_fails():
    client = FakeClient([FakeResponse(504, {})] * 4)
    with pytest.raises(cf.FetchError) as exc:
        await cf.fetch_facilities((0, 0, 1, 1), client=client,
                                  urls=["https://a.example/i", "https://b.example/i"], pause_s=0)
    assert "504" in str(exc.value) and len(client.calls) == 4


def test_mirrors_come_from_settings_and_must_be_https(monkeypatch):
    from app.core import config

    class S:
        overpass_urls = "https://one.example/api/interpreter, http://plain.example/x ,https://two.example/i"
        app_version = "9.9.9"

    monkeypatch.setattr(config, "get_settings", lambda: S())
    assert cf.overpass_urls() == ["https://one.example/api/interpreter", "https://two.example/i"]
    assert cf.user_agent() == "Pinpoint311/9.9.9 (critical-facilities refresh)"
    S.overpass_urls = ""
    assert cf.overpass_urls() == list(cf.DEFAULT_OVERPASS_URLS)


def test_fetch_area_buffers_the_boundary_and_falls_back_to_the_centre():
    boundary = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
                "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring(-75.0, 41.0, 0.02, 0.02)]]}}]}
    bbox, clip = cf.fetch_area(boundary)
    assert clip["type"] == "Polygon"
    assert bbox[0] < -75.0 - 0.01 and bbox[1] < 41.0 - 0.008 and bbox[3] > 41.02 + 0.008
    bbox, clip = cf.fetch_area({"center": {"lat": 41.0, "lng": -75.0}})
    assert clip is None and bbox[0] < -75.05 and bbox[2] > -74.95
    assert cf.fetch_area(None) == (None, None)


# ------------------------------------------------- no network per report

def test_the_request_path_has_no_network_client_in_it():
    from app.services import vertex_ai_service

    sources = [inspect.getsource(vertex_ai_service.get_spatial_context)] + [
        inspect.getsource(fn) for fn in (cf.proximity, cf.nearest_facilities, cf.layer_matches)]
    for src in sources:
        for word in ("aiohttp", "httpx", "overpass", "requests.", "urllib"):
            assert word not in src.lower(), word


# ===========================================================================
# PostGIS
# ===========================================================================

PG_URL = os.environ.get("GIS_LAYERS_PG_URL")
pg = pytest.mark.skipif(not PG_URL, reason="needs a throwaway PostGIS (GIS_LAYERS_PG_URL)")

# The made-up town: a 0.04 x 0.04 degree square; the report pin P in it.
X0, Y0 = -75.02, 40.98
P_LNG, P_LAT = -75.000, 41.000
BOUNDARY = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"name": "Nowhere"},
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring(X0, Y0, 0.04, 0.04)]]}}]}

# Metres per degree near 41 N.
M_LON = 111_320 * 0.7547
M_LAT = 110_950


def east(m):
    return P_LNG + m / M_LON


def north(m):
    return P_LAT + m / M_LAT


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
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        session.add(models.SystemSettings(township_boundary=BOUNDARY))
        await session.commit()
        yield session
    await engine.dispose()


def fetcher(elements):
    async def fetch(bbox):
        fetch.bbox = bbox
        return cf.parse_elements(elements), "https://overpass.example/api/interpreter"
    return fetch


def failing(exc=RuntimeError("Overpass said 504")):
    async def fetch(bbox):
        raise exc
    return fetch


async def _layer(db, name, features=None, *, table_features=None):
    from app.models import MapLayer
    from app.services import gis_layers

    layer = MapLayer(name=name, layer_type="point", is_active=True, routing_mode="none",
                     geojson={"type": "FeatureCollection", "features": features or []},
                     feature_storage="table" if table_features else "inline",
                     fill_color="#000000", stroke_color="#000000", fill_opacity=0.1, stroke_width=1)
    db.add(layer)
    await db.flush()
    if table_features:
        layer.routing_mode = "context"
        await gis_layers.import_features(db, layer, gis_layers.iter_inline_features(
            {"type": "FeatureCollection", "features": table_features}))
        layer.label_property = "NAME"
    await db.commit()
    return layer


def point_feature(lng, lat, **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [lng, lat]}}


async def _context(db):
    from app.services.vertex_ai_service import get_spatial_context
    return await get_spatial_context(db, P_LAT, P_LNG, "pothole")


@pg
async def test_a_campus_whose_edge_is_in_range_counts_though_its_centre_is_not(pgdb):
    # A 600 m wide campus whose west edge is 200 m east of the pin: centre ~500+ m.
    w = 600 / M_LON
    campus = {"type": "relation", "id": 77, "tags": {"amenity": "hospital", "name": "Campus Hospital", "type": "multipolygon"},
              "members": [{"type": "way", "ref": 1, "role": "outer",
                           "geometry": pts(ring(east(200), north(-300), w, 600 / M_LAT))}]}
    result = await cf.refresh(pgdb, fetch=fetcher([campus]))
    assert result["ok"] and result["counts"] == {"hospital": 1}

    ctx = await _context(pgdb)
    [line] = ctx["critical_infrastructure"]
    assert line.startswith("Hospital: Campus Hospital (")
    assert 190 <= int(line.split("(")[1].rstrip("m)")) <= 210


@pg
async def test_nearest_per_kind_sorted_by_distance_with_per_kind_radii(pgdb):
    els = [
        node(1, east(450), P_LAT, amenity="hospital", name="Far Hospital"),
        node(2, east(100), P_LAT, amenity="clinic", name="Near Clinic"),
        node(3, east(250), P_LAT, amenity="clinic", name="Other Clinic"),
        node(4, east(350), P_LAT, amenity="school", name="Too Far School"),   # > 300 m
        node(5, east(600), P_LAT, amenity="police", name="Out Of Range"),     # > 500 m
        node(6, east(30), P_LAT, emergency="fire_hydrant"),
    ]
    await cf.refresh(pgdb, fetch=fetcher(els))
    ctx = await _context(pgdb)
    names = [s.split(": ")[1].split(" (")[0] for s in ctx["critical_infrastructure"]]
    assert names == ["Near Clinic", "Far Hospital"]
    assert ctx["critical_infrastructure"][0].startswith("Medical Clinic: ")
    assert ctx["is_school_zone"] is False


@pg
async def test_a_hydrant_layer_neither_counts_nor_suppresses_facilities(pgdb):
    await _layer(pgdb, "Fire Hydrants", [point_feature(east(10), P_LAT, name="H-1")])
    await cf.refresh(pgdb, fetch=fetcher([node(1, east(300), P_LAT, amenity="fire_station", name="Station 1")]))
    ctx = await _context(pgdb)
    assert len(ctx["critical_infrastructure"]) == 1
    assert ctx["critical_infrastructure"][0].startswith("Fire Station: Station 1 (")


@pg
async def test_every_feature_of_a_large_layer_is_checked_and_merged(pgdb):
    # 300 hospitals far away, and one near -- at position 250, well past the
    # 50 the old loop looked at.
    feats = [point_feature(east(5000 + i), north(5000), name=f"H{i}") for i in range(300)]
    feats[250] = point_feature(east(120), P_LAT, name="Town Hospital")
    await _layer(pgdb, "Hospitals", feats)
    await cf.refresh(pgdb, fetch=fetcher([node(1, east(60), P_LAT, amenity="police", name="Precinct")]))
    ctx = await _context(pgdb)
    assert [s.split(" (")[0] for s in ctx["critical_infrastructure"]] == [
        "Police Station: Precinct", "Hospitals: Town Hospital"]


@pg
async def test_table_backed_layers_are_checked_by_their_outline(pgdb):
    square = [[list(p) for p in ring(east(150), north(-50), 100 / M_LON, 100 / M_LAT)]]
    await _layer(pgdb, "Fire Stations", table_features=[
        {"type": "Feature", "properties": {"NAME": "Station 9", "OWNER": "Private Person"},
         "geometry": {"type": "Polygon", "coordinates": square}}])
    ctx = await _context(pgdb)
    [line] = ctx["critical_infrastructure"]
    assert line.startswith("Fire Stations: Station 9 (") and "Private" not in line


@pg
async def test_the_school_zone_flag_is_about_this_point(pgdb):
    # A school layer far away used to set the flag for every report in town.
    await _layer(pgdb, "Schools", [point_feature(east(3000), P_LAT, name="Far School")])
    assert (await _context(pgdb))["is_school_zone"] is False

    # A school within 300 m sets it.
    await cf.refresh(pgdb, fetch=fetcher([node(1, east(200), P_LAT, amenity="school", name="Elm School")]))
    ctx = await _context(pgdb)
    assert ctx["is_school_zone"] is True and ctx["critical_infrastructure"][0].startswith("School: Elm School")

    # Inside a "School Zones" polygon, with no school near.
    await cf.refresh(pgdb, fetch=fetcher([node(1, east(2000), P_LAT, amenity="school", name="Elm School")]), )
    assert (await _context(pgdb))["is_school_zone"] is False
    zone = {"type": "Feature", "properties": {},
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in ring(east(-50), north(-50), 100 / M_LON, 100 / M_LAT)]]}}
    await _layer(pgdb, "School Zones", [zone])
    assert (await _context(pgdb))["is_school_zone"] is True


@pg
async def test_a_failed_or_empty_fetch_keeps_the_previous_set(pgdb):
    from app.models import CriticalFacilitiesStatus
    from sqlalchemy import select

    first = await cf.refresh(pgdb, fetch=fetcher([
        node(1, east(100), P_LAT, amenity="hospital", name="General"),
        node(2, east(200), P_LAT, amenity="school", name="Elm"),
        node(3, -80.0, 35.0, amenity="school", name="Another State"),  # clipped off
    ]))
    assert first["counts"] == {"hospital": 1, "school": 1}

    assert not (await cf.refresh(pgdb, fetch=failing()))["ok"]
    assert not (await cf.refresh(pgdb, fetch=fetcher([])))["ok"]
    # A swap that fails half-way (an unparseable geometry) rolls back whole.
    bad = [{"osm_type": "node", "osm_id": 9, "kind": "police", "name": "X", "geometry": {"type": "Nope"}}]

    async def broken(bbox):
        return bad, "https://overpass.example/"
    assert not (await cf.refresh(pgdb, fetch=broken))["ok"]

    assert await cf.counts_by_kind(pgdb) == {"hospital": 1, "school": 1}
    st = (await pgdb.execute(select(CriticalFacilitiesStatus))).scalars().one()
    assert st.last_error.startswith("store failed") and st.counts == {"hospital": 1, "school": 1}
    assert st.attempted_at >= st.refreshed_at
    assert (await _context(pgdb))["critical_infrastructure"][0].startswith("Hospital: General")


@pg
async def test_refresh_if_due_only_acts_when_empty_or_a_week_old(pgdb):
    from app.models import CriticalFacilitiesStatus
    from sqlalchemy import select

    calls = []

    async def fetch(bbox):
        calls.append(bbox)
        return cf.parse_elements([node(1, east(100), P_LAT, amenity="police", name="Precinct")]), "https://o.example/"

    assert (await cf.refresh_if_due(pgdb, only_if_empty=True, fetch=fetch))["ok"]
    assert len(calls) == 1
    assert (await cf.refresh_if_due(pgdb, only_if_empty=True, fetch=fetch))["skipped"]
    st = (await pgdb.execute(select(CriticalFacilitiesStatus))).scalars().one()
    st.attempted_at = st.refreshed_at = datetime.now(timezone.utc) - timedelta(days=3)
    await pgdb.commit()
    assert "week" in (await cf.refresh_if_due(pgdb, fetch=fetch))["skipped"]
    st.attempted_at = st.refreshed_at = datetime.now(timezone.utc) - timedelta(days=8)
    await pgdb.commit()
    assert (await cf.refresh_if_due(pgdb, fetch=fetch))["ok"] and len(calls) == 2
    # Two triggers back to back (worker boot and the beat): one fetch.
    st.refreshed_at = datetime.now(timezone.utc) - timedelta(days=8)
    await pgdb.commit()
    assert "30 minutes" in (await cf.refresh_if_due(pgdb, fetch=fetch))["skipped"]


@pg
async def test_the_request_path_makes_no_network_call(pgdb, monkeypatch):
    import httpx

    await cf.refresh(pgdb, fetch=fetcher([node(1, east(100), P_LAT, amenity="hospital", name="General")]))
    await _layer(pgdb, "Hospitals", [point_feature(east(50), P_LAT, name="Town Hospital")])

    attempts = []

    def refuse(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("network client opened on the request path")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", refuse)
    monkeypatch.setattr(httpx.Client, "__init__", refuse)
    try:
        import aiohttp
        monkeypatch.setattr(aiohttp.ClientSession, "__init__", refuse)
    except ImportError:
        pass

    ctx = await _context(pgdb)
    assert attempts == []
    assert [s.split(" (")[0] for s in ctx["critical_infrastructure"]] == [
        "Hospitals: Town Hospital", "Hospital: General"]


@pg
async def test_health_warns_when_empty_or_stale_and_reports_counts(pgdb):
    from app.models import CriticalFacilitiesStatus
    from app.services.proactive_health import _critical_facilities_check
    from sqlalchemy import select

    check = await _critical_facilities_check(pgdb)
    assert check["key"] == "critical_facilities" and check["status"] == "warning"

    await cf.refresh(pgdb, fetch=fetcher([node(1, east(100), P_LAT, amenity="school", name="Elm"),
                                           node(2, east(100), P_LAT, amenity="school", name="Oak")]))
    check = await _critical_facilities_check(pgdb)
    assert check["status"] == "ok" and "2 school" in check["message"]
    assert check["detail"]["counts"] == {"school": 2} and check["detail"]["refreshed_at"]

    st = (await pgdb.execute(select(CriticalFacilitiesStatus))).scalars().one()
    st.refreshed_at = datetime.now(timezone.utc) - timedelta(days=31)
    await pgdb.commit()
    assert (await _critical_facilities_check(pgdb))["status"] == "warning"


@pg
async def test_the_reconciler_creates_the_tables_on_a_database_already_at_head(pgdb):
    """A town already at e3a5c7d9f1b2 never replays it; boot reconciliation
    must create the store, GIST index included."""
    from sqlalchemy import inspect, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from app.db import migrate

    engine = create_async_engine(PG_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE critical_facilities_status"))
        await conn.execute(text("DROP TABLE critical_facilities"))
        plan = await conn.run_sync(migrate.reconcile)
        assert set(plan.missing_tables) == {"critical_facilities", "critical_facilities_status"}
        indexes = await conn.run_sync(lambda c: {i["name"] for i in inspect(c).get_indexes("critical_facilities")})
        assert {"ix_critical_facilities_geom", "ix_critical_facilities_kind"} <= indexes
        method = (await conn.execute(text(
            "SELECT am.amname FROM pg_class c JOIN pg_am am ON am.oid = c.relam "
            "WHERE c.relname = 'ix_critical_facilities_geom'"))).scalar()
        assert method == "gist"
    await engine.dispose()


def test_the_migration_and_the_models_declare_the_same_tables():
    import pathlib
    from app import models

    src = next((pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions").glob("e3a5c7d9f1b2_*.py")).read_text()
    for table in ("critical_facilities", "critical_facilities_status"):
        assert f'"{table}",' in src
        assert table in models.Base.metadata.tables
    assert '"ix_critical_facilities_geom", "critical_facilities", ["geom"], postgresql_using="gist"' in src
    cols = set(models.Base.metadata.tables["critical_facilities"].columns.keys())
    assert cols == {"id", "osm_type", "osm_id", "kind", "name", "geom", "fetched_at"}
    for col in cols:
        assert f'sa.Column("{col}"' in src
