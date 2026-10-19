"""Polygon context layers: tax parcels and zones as GIS history on reports.

Two halves. The first needs nothing but the app's own modules: the streaming
GeoJSON parse, the CRS rule, the upload limits, the field heuristics and the
privacy rules on what public responses may carry. The second is spatial and
runs against a throwaway PostGIS named by GIS_LAYERS_PG_URL
(postgresql+asyncpg://...); without it, those tests skip. Each PG test starts
from an empty schema, so never point it at a real database.
"""

import inspect
import io
import json
import os

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("fastapi.routing")
pytest.importorskip("pydantic")
pytest.importorskip("geoalchemy2")

from fastapi import HTTPException  # noqa: E402

from app.models import MapLayer  # noqa: E402
from app.services import gis_layers  # noqa: E402
from app.services.gis_layers import LayerUploadError  # noqa: E402


# --------------------------------------------------------------- fixtures

def square(x0, y0, size=0.001):
    return [[[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]]


def feature(coords, kind="Polygon", **props):
    return {"type": "Feature", "properties": props, "geometry": {"type": kind, "coordinates": coords}}


def fc(features, **extra):
    return {"type": "FeatureCollection", **extra, "features": features}


def parse(doc, chunk=None, monkeypatch=None):
    text = doc if isinstance(doc, str) else json.dumps(doc)
    if chunk and monkeypatch:
        monkeypatch.setattr(gis_layers, "_READ_CHUNK", chunk)
    return list(gis_layers.iter_feature_collection(io.StringIO(text)))


# ------------------------------------------------------- streaming parse

def test_streams_features_larger_than_the_read_buffer(monkeypatch):
    """Each feature is decoded on its own; a buffer smaller than one feature
    only costs retries, never a wrong answer."""
    big = feature(square(-74.0, 40.0), PIN="1-2", NOTES="x" * 500)
    doc = fc([big, feature(square(-74.1, 40.0), PIN="1-3")])
    out = parse(doc, chunk=7, monkeypatch=monkeypatch)
    assert [f["properties"]["PIN"] for f in out] == ["1-2", "1-3"]
    assert out[0]["properties"]["NOTES"] == "x" * 500


@pytest.mark.parametrize("name", [
    "urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326", "urn:ogc:def:crs:EPSG::4326",
])
def test_a_declared_wgs84_crs_is_accepted_wherever_it_appears(name):
    crs = {"type": "name", "properties": {"name": name}}
    before = {"type": "FeatureCollection", "crs": crs, "features": [feature(square(-74, 40))]}
    after = '{"type": "FeatureCollection", "features": [%s], "crs": %s}' % (
        json.dumps(feature(square(-74, 40))), json.dumps(crs))
    assert len(parse(before)) == 1
    assert len(parse(after)) == 1


def test_any_other_crs_is_refused_with_instructions():
    crs = {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3424"}}
    with pytest.raises(LayerUploadError) as exc:
        parse(fc([feature(square(-74, 40))], crs=crs))
    assert "3424" in str(exc.value) and "EPSG:4326" in str(exc.value)

    # Declared after the features: still refused (the import is one
    # transaction, so what was inserted before it is rolled back).
    doc = '{"type": "FeatureCollection", "features": [%s], "crs": %s}' % (
        json.dumps(feature(square(-74, 40))), json.dumps(crs))
    with pytest.raises(LayerUploadError):
        parse(doc)


@pytest.mark.parametrize("doc", [
    feature(square(-74, 40)),                          # a lone Feature
    [feature(square(-74, 40))],                        # a bare list
    {"type": "GeometryCollection", "geometries": []},
    {"type": "FeatureCollection"},                     # no features member
    '{"type": "FeatureCollection", "features": [',     # cut short
    '{"type": "FeatureCollection", "features": [}]}',  # not JSON
])
def test_anything_but_a_feature_collection_is_refused(doc):
    with pytest.raises(LayerUploadError):
        parse(doc)


def test_points_and_projected_coordinates_are_refused_by_feature():
    with pytest.raises(LayerUploadError) as exc:
        gis_layers.feature_parts(feature([-74, 40], kind="Point"), 3)
    assert "Feature 3" in str(exc.value) and "point layer" in str(exc.value)

    # NJ State Plane feet: the classic "forgot to reproject" file.
    with pytest.raises(LayerUploadError) as exc:
        gis_layers.feature_parts(feature(square(612345.0, 701234.0, 50)), 1)
    assert "WGS 84" in str(exc.value)


def test_multipolygons_are_accepted_and_nul_bytes_dropped():
    geometry, props = gis_layers.feature_parts(
        feature([square(-74, 40), square(-74.01, 40)], kind="MultiPolygon", NAME="a\x00b"), 1)
    assert json.loads(geometry)["type"] == "MultiPolygon"
    assert props == {"NAME": "ab"}
    _, props = gis_layers.feature_parts({"type": "Feature", "properties": None,
                                         "geometry": {"type": "Polygon", "coordinates": square(-74, 40)}}, 1)
    assert props == {}


# ------------------------------------------------------------ the limits

@pytest.fixture
def staging(monkeypatch, tmp_path):
    monkeypatch.setenv("MAP_LAYER_UPLOAD_DIR", str(tmp_path))
    return tmp_path


def test_upload_size_limit_is_enforced_up_front(staging):
    with pytest.raises(LayerUploadError) as exc:
        gis_layers.start_upload(gis_layers.MAX_UPLOAD_BYTES + 1, 1)
    assert "100 MB" in str(exc.value)
    with pytest.raises(LayerUploadError):
        gis_layers.start_upload(0, 1)


def test_chunks_must_arrive_in_order_from_their_owner_and_complete(staging):
    up = gis_layers.start_upload(10, user_id=1)
    uid = up["upload_id"]
    assert up["chunk_bytes"] < 13 * 1024 * 1024  # each part clears the body ceiling
    with pytest.raises(LayerUploadError):
        gis_layers.append_chunk(uid, 1, b"abc", 1)          # out of order
    with pytest.raises(LayerUploadError):
        gis_layers.append_chunk(uid, 0, b"abc", 2)          # another admin's upload
    gis_layers.append_chunk(uid, 0, b"abcde", 1)
    with pytest.raises(LayerUploadError):
        gis_layers.completed_upload(uid, 1)                 # 5 of 10 bytes
    with pytest.raises(LayerUploadError):
        gis_layers.append_chunk(uid, 1, b"x" * 6, 1)        # more than declared
    gis_layers.append_chunk(uid, 1, b"fghij", 1)
    assert gis_layers.completed_upload(uid, 1).read_bytes() == b"abcdefghij"
    gis_layers.discard_upload(uid)
    with pytest.raises(LayerUploadError):
        gis_layers.completed_upload(uid, 1)


@pytest.mark.parametrize("bad", ["../../etc/passwd", "A" * 32, "", "0" * 31])
def test_upload_ids_cannot_name_other_files(staging, bad):
    with pytest.raises(LayerUploadError):
        gis_layers.append_chunk(bad, 0, b"x", 1)


class _RecordingDB:
    """Enough of a session for import_features to run without Postgres."""

    def __init__(self):
        self.batches = []

    async def execute(self, stmt, params=None):
        if isinstance(params, list):
            self.batches.append(params)

        class _R:
            rowcount = 0
        return _R()


async def test_feature_count_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(gis_layers, "MAX_FEATURES", 3)
    layer = MapLayer(id=1, name="Parcels")
    with pytest.raises(LayerUploadError) as exc:
        await gis_layers.import_features(_RecordingDB(), layer, [feature(square(-74, 40))] * 4)
    assert "3" in str(exc.value)


async def test_import_inserts_in_batches_and_records_the_fields(monkeypatch):
    monkeypatch.setattr(gis_layers, "INSERT_BATCH", 2)
    layer = MapLayer(id=1, name="Parcels", staff_properties=["GONE"], label_property="GONE")
    db = _RecordingDB()
    feats = [feature(square(-74 + i * 0.01, 40), PAMS_PIN=f"1-{i}", OWNER_NAME="X") for i in range(5)]
    summary = await gis_layers.import_features(db, layer, feats)
    assert [len(b) for b in db.batches] == [2, 2, 1]
    assert summary["feature_count"] == 5
    assert layer.available_properties == ["PAMS_PIN", "OWNER_NAME"]
    assert layer.feature_id_property == "PAMS_PIN"
    # Settings naming fields the new file does not have are dropped.
    assert layer.staff_properties == [] and layer.label_property is None
    assert layer.feature_storage == "table"
    assert layer.geojson == {"type": "FeatureCollection", "features": []}


# ------------------------------------------------- fields and privacy rules

@pytest.mark.parametrize("name,flag", [
    ("OWNER_NAME", "owner"), ("OWNERNAME", "owner"), ("TAXPAYER", "owner"),
    ("Mailing_Addr", "owner"), ("OWN_NAME", "owner"),
    ("ST_NAME", "maybe"), ("PROP_ADDR", "maybe"),
    ("PAMS_PIN", None), ("ZONE", None), ("ACREAGE", None),
])
def test_field_classification(name, flag):
    assert gis_layers.classify_field(name) == flag


def test_guess_id_property_prefers_parcel_identifiers():
    assert gis_layers.guess_id_property(["OBJECTID", "OWNER", "PAMS_PIN"]) == "PAMS_PIN"
    assert gis_layers.guess_id_property(["Parcel_ID", "id"]) == "Parcel_ID"
    assert gis_layers.guess_id_property(["ZONE", "ACRES"]) is None


def _ctx_layer(**kw):
    defaults = dict(id=1, name="Parcels", routing_mode="context", feature_storage="table",
                    staff_properties=[], available_properties=["PIN", "ZONE", "OWNER_NAME", "ST_NAME"],
                    geojson={"type": "FeatureCollection", "features": []}, is_active=True,
                    show_on_resident_portal=False, fill_color="#fff", stroke_color="#000",
                    fill_opacity=0.1, stroke_width=1, visible_on_map=True, service_codes=[])
    defaults.update(kw)
    return MapLayer(**defaults)


def test_portal_visibility_is_refused_without_reviewed_fields_or_with_owner_fields():
    errors, _ = gis_layers.portal_visibility_problems(_ctx_layer(staff_properties=[]))
    assert errors
    errors, _ = gis_layers.portal_visibility_problems(_ctx_layer(staff_properties=["PIN", "OWNER_NAME"]))
    assert errors and "OWNER_NAME" in errors[-1]
    # Unsure: a warning, not a refusal.
    errors, warnings = gis_layers.portal_visibility_problems(_ctx_layer(staff_properties=["PIN", "ST_NAME"]))
    assert not errors and any("ST_NAME" in w for w in warnings)
    # Owner fields the allowlist leaves out are mentioned, not blocking.
    errors, warnings = gis_layers.portal_visibility_problems(_ctx_layer(staff_properties=["PIN"]))
    assert not errors and any("OWNER_NAME" in w for w in warnings)


def test_snapshot_keeps_the_allowlist_only():
    entry = gis_layers.snapshot_entry(
        layer_id=1, layer_name="Parcels", feature_id=9, feature_key="12-4",
        properties={"PIN": "12-4", "ZONE": "R-1", "OWNER_NAME": "Jane Roe", "ADDR": "1 Main"},
        label_property="ADDR", staff_properties=["ZONE", "PIN", "MISSING"])
    assert entry["properties"] == {"ZONE": "R-1", "PIN": "12-4"}
    assert entry["label"] == "1 Main"
    assert "Jane Roe" not in json.dumps(entry)


def test_public_layer_never_carries_context_features_or_settings():
    from app.api.map_layers import public_layer
    inline_context = _ctx_layer(feature_storage="inline", geojson=fc([
        feature(square(-74, 40), OWNER_NAME="Jane Roe")]))
    out = public_layer(inline_context)
    assert out["geojson"] == {"type": "FeatureCollection", "features": []}
    text = json.dumps(out, default=str)
    assert "Jane Roe" not in text and "OWNER_NAME" not in text
    for key in ("staff_properties", "available_properties", "label_property",
                "feature_id_property", "field_flags"):
        assert key not in out

    # A point layer is untouched: residents pick assets from it.
    point = _ctx_layer(routing_mode="none", feature_storage="inline", layer_type="point",
                       geojson=fc([{"type": "Feature", "properties": {"asset_id": "H-1"},
                                    "geometry": {"type": "Point", "coordinates": [-74, 40]}}]))
    assert public_layer(point)["geojson"]["features"][0]["properties"] == {"asset_id": "H-1"}


def test_gis_context_is_on_the_staff_detail_schema_only():
    from app import schemas
    assert "gis_context" in schemas.ServiceRequestDetailResponse.model_fields
    for name in ("ServiceRequestResponse", "PublicServiceRequestResponse", "Open311CreatedRequestResponse"):
        assert "gis_context" not in getattr(schemas, name).model_fields, name


def test_every_intake_path_records_the_context():
    from app.api import integrations as api_integrations, open311
    from app.tasks import integrations as task_integrations
    assert "gis_layers.context_for_point(" in inspect.getsource(open311._intake_resident_report)
    assert "gis_layers.context_for_point(" in inspect.getsource(open311.create_manual_intake)
    # The Open311 keyed POST goes through the resident path.
    assert "_intake_resident_report(" in inspect.getsource(open311.create_request_open311)
    assert "gis_context=" in inspect.getsource(api_integrations)
    assert "gis_context=await _gis_context(" in inspect.getsource(task_integrations)


async def test_context_lookup_never_raises_off_postgres():
    class _NotPostgres:
        def get_bind(self):
            raise RuntimeError("no bind")
    assert await gis_layers.context_for_point(_NotPostgres(), 40.0, -74.0) is None
    assert await gis_layers.context_for_point(object(), None, None) is None


def test_routing_mode_is_validated():
    from pydantic import ValidationError
    from app.schemas import MapLayerUpdate
    assert MapLayerUpdate(routing_mode="context").routing_mode == "context"
    with pytest.raises(ValidationError):
        MapLayerUpdate(routing_mode="teleport")


def test_bbox_parsing():
    assert gis_layers.parse_bbox("-74.1,40.0,-74.0,40.1") == (-74.1, 40.0, -74.0, 40.1)
    for bad in ("1,2,3", "a,b,c,d", "-74,40,-75,41", "-200,0,0,1", "nan,0,1,1"):
        with pytest.raises(LayerUploadError):
            gis_layers.parse_bbox(bad)


# ===========================================================================
# PostGIS
# ===========================================================================

PG_URL = os.environ.get("GIS_LAYERS_PG_URL")
pg = pytest.mark.skipif(not PG_URL, reason="needs a throwaway PostGIS (GIS_LAYERS_PG_URL)")

# Parcels, ~110 m squares around (-74.000, 40.000):
#   A [-74.000..-73.999] and B [-73.999..-73.998] share an edge at x = -73.999.
#   C is a MultiPolygon: one part next to B, one part far east.
#   D has a hole in its middle.
#   E is a self-intersecting "bowtie" that only exists once repaired.
A = feature(square(-74.000, 40.000), PIN="A-1", ZONE="R-1", OWNER_NAME="Jane Roe", ADDR="1 Main St")
B = feature(square(-73.999, 40.000), PIN="B-2", ZONE="C-2", OWNER_NAME="John Doe", ADDR="3 Main St")
C = feature([square(-73.998, 40.000), square(-73.990, 40.000)], kind="MultiPolygon",
            PIN="C-3", ZONE="R-2", OWNER_NAME="Acme LLC", ADDR="5 Main St")
D = feature([[[-74.000, 40.010], [-73.996, 40.010], [-73.996, 40.014], [-74.000, 40.014], [-74.000, 40.010]],
             [[-73.999, 40.011], [-73.997, 40.011], [-73.997, 40.013], [-73.999, 40.013], [-73.999, 40.011]]],
            PIN="D-4", ZONE="P", OWNER_NAME="Town", ADDR="Park")
E = feature([[[-74.010, 40.000], [-74.008, 40.002], [-74.008, 40.000], [-74.010, 40.002], [-74.010, 40.000]]],
            PIN="E-5", ZONE="R-1", OWNER_NAME="Ann", ADDR="Bowtie")
PARCELS = fc([A, B, C, D, E])


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
        yield session
    await engine.dispose()


async def _layer(db, *, features=PARCELS, allow=("PIN", "ZONE"), label="ADDR", service_codes=()):
    layer = MapLayer(name="Tax Parcels", layer_type="polygon", routing_mode="context",
                     feature_storage="table", geojson=dict(gis_layers.EMPTY_FEATURE_COLLECTION),
                     is_active=True, show_on_resident_portal=False, service_codes=list(service_codes),
                     fill_color="#f59e0b", stroke_color="#b45309", fill_opacity=0.1, stroke_width=1)
    db.add(layer)
    await db.flush()
    await gis_layers.import_features(db, layer, gis_layers.iter_inline_features(features))
    layer.staff_properties = list(allow)
    layer.label_property = label
    await db.commit()
    return layer


def _keys(entries):
    return sorted(e["feature_key"] for e in (entries or []))


@pg
async def test_point_in_polygon_matching(pgdb):
    layer = await _layer(pgdb)
    assert layer.feature_count == 5 and layer.feature_id_property == "PIN"
    ctx = gis_layers.context_for_point
    assert _keys(await ctx(pgdb, 40.0005, -73.9995)) == ["A-1"]
    # On the shared boundary: ST_Covers counts the edge, so both parcels.
    assert _keys(await ctx(pgdb, 40.0005, -73.999)) == ["A-1", "B-2"]
    # Either part of the MultiPolygon.
    assert _keys(await ctx(pgdb, 40.0005, -73.9895)) == ["C-3"]
    # Inside D's hole: not in D.
    assert await ctx(pgdb, 40.012, -73.998) is None
    assert _keys(await ctx(pgdb, 40.0105, -73.9995)) == ["D-4"]
    # The bowtie, once repaired, still covers its lobes.
    assert _keys(await ctx(pgdb, 40.0003, -74.0099)) == ["E-5"]
    assert await ctx(pgdb, 41.0, -75.0) is None


@pg
async def test_the_snapshot_carries_the_allowlist_only(pgdb):
    await _layer(pgdb)
    [entry] = await gis_layers.context_for_point(pgdb, 40.0005, -73.9995)
    assert entry["layer_name"] == "Tax Parcels"
    assert entry["label"] == "1 Main St"
    assert entry["properties"] == {"PIN": "A-1", "ZONE": "R-1"}
    assert "Jane Roe" not in json.dumps(entry)


@pg
async def test_inactive_non_context_and_other_category_layers_do_not_match(pgdb):
    layer = await _layer(pgdb, service_codes=["pothole"])
    assert await gis_layers.context_for_point(pgdb, 40.0005, -73.9995, "graffiti") is None
    assert await gis_layers.context_for_point(pgdb, 40.0005, -73.9995, "pothole")
    layer.routing_mode = "log"
    await pgdb.commit()
    assert await gis_layers.context_for_point(pgdb, 40.0005, -73.9995, "pothole") is None
    layer.routing_mode, layer.is_active = "context", False
    await pgdb.commit()
    assert await gis_layers.context_for_point(pgdb, 40.0005, -73.9995, "pothole") is None


async def _seed_people(db):
    from app.models import Department, ServiceDefinition, User, user_departments
    from sqlalchemy import insert
    roads = Department(name="Roads", is_active=True)
    parks = Department(name="Parks", is_active=True)
    db.add_all([roads, parks])
    await db.flush()
    staff = User(username="roadie", email="r@example.org", role="staff", is_active=True)
    admin = User(username="boss", email="b@example.org", role="admin", is_active=True)
    db.add_all([staff, admin])
    db.add(ServiceDefinition(service_code="pothole", service_name="Pothole", is_active=True,
                             assigned_department_id=roads.id))
    await db.flush()
    await db.execute(insert(user_departments).values(user_id=staff.id, department_id=roads.id))
    await db.commit()
    return roads, parks, staff, admin


async def _request(db, sid, lat, lng, *, dept=None, ctx=None):
    from app.models import ServiceRequest
    sr = ServiceRequest(service_request_id=sid, service_code="pothole", service_name="Pothole",
                        description="Pothole here", lat=lat, long=lng, email="x@intake.local",
                        source="phone", assigned_department_id=dept, gis_context=ctx)
    db.add(sr)
    await db.commit()
    return sr


@pg
async def test_intake_stores_the_context(pgdb, monkeypatch):
    from app.api import open311
    from app.schemas import ServiceRequestCreate
    await _layer(pgdb)
    await _seed_people(pgdb)
    monkeypatch.setattr(open311, "enqueue", lambda *a, **k: None)
    monkeypatch.setattr(open311, "enqueue_later", lambda *a, **k: None)

    async def _no_block(*a, **k):
        class _D:
            blocked = False
        return _D()
    monkeypatch.setattr(open311.road_blocking, "evaluate", _no_block)
    created = await open311._intake_resident_report(
        pgdb, ServiceRequestCreate(service_code="pothole", description="Deep pothole",
                                   lat=40.0005, long=-73.9995, email="r@example.org"),
        source="resident_portal", notify_resident=False)
    assert _keys(created.gis_context) == ["A-1"]
    assert created.gis_context[0]["properties"] == {"PIN": "A-1", "ZONE": "R-1"}


@pg
async def test_reupload_keeps_the_history_snapshot(pgdb):
    layer = await _layer(pgdb)
    ctx = await gis_layers.context_for_point(pgdb, 40.0005, -73.9995)
    sr = await _request(pgdb, "SR-1", 40.0005, -73.9995, ctx=ctx)

    changed = json.loads(json.dumps(PARCELS))
    changed["features"][0]["properties"]["ZONE"] = "R-9"
    await gis_layers.import_features(pgdb, layer, gis_layers.iter_inline_features(changed))
    await pgdb.commit()
    await pgdb.refresh(sr)
    assert sr.gis_context[0]["properties"]["ZONE"] == "R-1"
    # Same parcel id, same key: the history query still finds it.
    [now] = await gis_layers.context_for_point(pgdb, 40.0005, -73.9995)
    assert now["feature_key"] == "A-1" and now["properties"]["ZONE"] == "R-9"


@pg
async def test_geometry_keys_are_stable_without_an_id_property(pgdb):
    no_ids = fc([feature(square(-74.0, 40.0), ZONE="R-1")])
    layer = await _layer(pgdb, features=no_ids, allow=("ZONE",), label=None)
    assert layer.feature_id_property is None
    [first] = await gis_layers.context_for_point(pgdb, 40.0005, -73.9995)
    await gis_layers.import_features(pgdb, layer, gis_layers.iter_inline_features(no_ids))
    await pgdb.commit()
    [second] = await gis_layers.context_for_point(pgdb, 40.0005, -73.9995)
    assert first["feature_key"].startswith("g:") and first["feature_key"] == second["feature_key"]


@pg
async def test_reports_in_feature_are_department_scoped(pgdb):
    from app.api.map_layers import reports_in_feature
    layer = await _layer(pgdb)
    roads, parks, staff, admin = await _seed_people(pgdb)
    ctx = await gis_layers.context_for_point(pgdb, 40.0005, -73.9995)
    await _request(pgdb, "SR-ROADS", 40.0005, -73.9995, dept=roads.id, ctx=ctx)
    await _request(pgdb, "SR-PARKS", 40.0005, -73.9995, dept=parks.id, ctx=ctx)
    await _request(pgdb, "SR-NEW", 40.0005, -73.9995, dept=None, ctx=ctx)
    await _request(pgdb, "SR-ELSEWHERE", 40.0005, -73.9985, dept=roads.id,
                   ctx=await gis_layers.context_for_point(pgdb, 40.0005, -73.9985))

    async def ids(user, **kw):
        args = dict(feature_key=None, feature_id=None, exclude_request_id=None)
        args.update(kw)
        rows = await reports_in_feature(layer.id, db=pgdb, current_user=user, **args)
        return sorted(r["service_request_id"] for r in rows)

    assert await ids(admin, feature_key="A-1") == ["SR-NEW", "SR-PARKS", "SR-ROADS"]
    assert await ids(staff, feature_key="A-1") == ["SR-NEW", "SR-ROADS"]
    assert await ids(staff, feature_key="A-1", exclude_request_id="SR-NEW") == ["SR-ROADS"]
    assert await ids(admin, feature_id=ctx[0]["feature_id"]) == ["SR-NEW", "SR-PARKS", "SR-ROADS"]
    assert await ids(admin, feature_key="B-2") == ["SR-ELSEWHERE"]
    with pytest.raises(HTTPException):
        await ids(admin)


@pg
async def test_bbox_is_simplified_capped_and_property_free(pgdb, monkeypatch):
    layer = await _layer(pgdb)
    view = (-74.0005, 39.9995, -73.9975, 40.0015)   # A, B and C's first part
    out = await gis_layers.features_in_bbox(pgdb, layer, view, 17)
    assert not out["zoom_in"]
    assert sorted(f["properties"]["feature_key"] for f in out["features"]) == ["A-1", "B-2", "C-3"]
    for f in out["features"]:
        assert set(f["properties"]) == {"feature_id", "feature_key", "label"}
        assert f["geometry"]["type"] in ("Polygon", "MultiPolygon") and f["geometry"]["coordinates"]
    assert "Jane Roe" not in json.dumps(out)

    monkeypatch.setattr(gis_layers, "MAX_BBOX_FEATURES", 2)
    capped = await gis_layers.features_in_bbox(pgdb, layer, view, 17)
    assert capped["zoom_in"] is True and capped["features"] == []
    far = await gis_layers.features_in_bbox(pgdb, layer, view, 12)
    assert far["zoom_in"] is True and far["features"] == []


@pg
async def test_backfill_fills_missing_context_in_batches_and_is_audited(pgdb):
    from sqlalchemy import func, select
    from app.models import AuditLog, RequestAuditLog, ServiceRequest
    from app.api.map_layers import backfill_layer_context
    layer = await _layer(pgdb)
    roads, parks, staff, admin = await _seed_people(pgdb)
    for i in range(5):
        await _request(pgdb, f"SR-{i}", 40.0005, -73.9995 + (0.001 if i % 2 else 0))
    await _request(pgdb, "SR-OUT", 41.0, -75.0)
    kept = [{"layer_id": layer.id, "feature_key": "A-1", "properties": {"ZONE": "OLD"}}]
    await _request(pgdb, "SR-HAS", 40.0005, -73.9995, ctx=kept)

    import app.services.gis_layers as g
    result = await g.backfill_layer(pgdb, layer, actor_name="boss", batch_size=2)
    assert result == {"scanned": 7, "updated": 5}
    rows = {r.service_request_id: r for r in (await pgdb.execute(select(ServiceRequest))).scalars()}
    assert _keys(rows["SR-0"].gis_context) == ["A-1"]
    assert _keys(rows["SR-1"].gis_context) == ["B-2"]
    assert rows["SR-OUT"].gis_context is None
    assert rows["SR-HAS"].gis_context == kept          # intake snapshot untouched
    n = (await pgdb.execute(select(func.count()).select_from(RequestAuditLog)
                            .where(RequestAuditLog.action == "location_context_updated"))).scalar()
    assert n == 5

    # Through the route: nothing left to do, and the admin trail says so.
    again = await backfill_layer_context(layer.id, db=pgdb, admin=admin)
    assert again["updated"] == 0
    events = (await pgdb.execute(select(AuditLog.event_type))).scalars().all()
    assert "map_layer_backfilled" in events


@pg
async def test_chunked_upload_to_layer_end_to_end(pgdb, staging):
    from app.api.map_layers import create_polygon_layer, list_public_layers, update_layer
    from app.schemas import MapLayerPolygonCreate, MapLayerUpdate
    roads, parks, staff, admin = await _seed_people(pgdb)
    raw = json.dumps(PARCELS).encode()
    up = gis_layers.start_upload(len(raw), admin.id)
    half = len(raw) // 2
    gis_layers.append_chunk(up["upload_id"], 0, raw[:half], admin.id)
    gis_layers.append_chunk(up["upload_id"], 1, raw[half:], admin.id)
    out = await create_polygon_layer(
        MapLayerPolygonCreate(name="Tax Parcels", upload_id=up["upload_id"]), db=pgdb, admin=admin)
    assert out.feature_count == 5 and out.import_summary["skipped"] == 0
    assert out.show_on_resident_portal is False and out.staff_properties == []
    assert out.field_flags.get("OWNER_NAME") == "owner"

    # Settings: unknown fields are refused; the allowlist is kept in file order.
    with pytest.raises(HTTPException):
        await update_layer(out.id, MapLayerUpdate(staff_properties=["NOPE"]), db=pgdb, admin=admin)
    upd = await update_layer(out.id, MapLayerUpdate(staff_properties=["ZONE", "PIN"], label_property="ADDR"),
                             db=pgdb, admin=admin)
    assert upd.staff_properties == ["PIN", "ZONE"]
    # Owner fields block portal visibility; reviewed ones allow it, with outlines only.
    with pytest.raises(HTTPException):
        await update_layer(out.id, MapLayerUpdate(staff_properties=["PIN", "OWNER_NAME"],
                                                  show_on_resident_portal=True), db=pgdb, admin=admin)
    shown = await update_layer(out.id, MapLayerUpdate(show_on_resident_portal=True), db=pgdb, admin=admin)
    assert shown.show_on_resident_portal is True and shown.warnings
    public = await list_public_layers(db=pgdb)
    assert public[0]["geojson"] == {"type": "FeatureCollection", "features": []}
    assert "Jane Roe" not in json.dumps(public, default=str)
    assert "PIN" not in json.dumps(public, default=str)
    # The staged file is gone once imported.
    assert not any(staging.rglob("*.geojson"))


def test_staff_cannot_edit_a_report_location():
    """The location is the resident's report; no staff route changes it."""
    open311 = pytest.importorskip("app.api.open311")
    assert not hasattr(open311, "update_request_location")
    paths = {getattr(r, "path", "") for r in open311.router.routes}
    assert not any(p.endswith("/location") for p in paths)


# ---------------------------------------------- resident-portal outlines

def _outlines_route():
    from app.api import map_layers
    # Past the two rate-limit wrappers, which need a live Request.
    return inspect.unwrap(map_layers.public_layer_outlines)


def test_public_outlines_route_is_rate_limited_and_declared_public():
    from app.api import map_layers
    assert map_layers.public_layer_outlines is not _outlines_route()
    from app.core.route_access import _VERIFIED_IN_HANDLER
    assert "public_layer_outlines" in _VERIFIED_IN_HANDLER


class _OneLayerDB:
    def __init__(self, layer):
        self.layer = layer

    async def execute(self, stmt, params=None):
        layer = self.layer

        class _R:
            def scalar_one_or_none(self):
                return layer
        return _R()


@pytest.mark.parametrize("overrides", [
    dict(show_on_resident_portal=False),                                   # not on the portal
    dict(show_on_resident_portal=True, is_active=False),                   # disabled
    dict(show_on_resident_portal=True, staff_properties=[]),               # guard: nothing reviewed
    dict(show_on_resident_portal=True, staff_properties=["PIN", "OWNER_NAME"]),  # guard: owner field
    dict(show_on_resident_portal=True, staff_properties=["PIN"], feature_storage="inline"),
])
async def test_public_outlines_refuse_layers_not_on_the_portal(overrides):
    layer = _ctx_layer(**overrides)
    with pytest.raises(HTTPException) as exc:
        await _outlines_route()(None, layer.id, bbox="-74.1,40.0,-74.0,40.1", zoom=17,
                                db=_OneLayerDB(layer))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await _outlines_route()(None, 1, bbox="-74.1,40.0,-74.0,40.1", zoom=17, db=_OneLayerDB(None))
    assert exc.value.status_code == 404


@pg
async def test_public_outlines_are_shapes_only_and_capped(pgdb, monkeypatch):
    layer = await _layer(pgdb)
    layer.show_on_resident_portal = True
    await pgdb.commit()
    view = "-74.0005,39.9995,-73.9975,40.0015"
    out = await _outlines_route()(None, layer.id, bbox=view, zoom=17, db=pgdb)
    assert out["zoom_in"] is False and len(out["features"]) == 3
    for f in out["features"]:
        assert set(f) == {"type", "properties", "geometry"} and f["properties"] == {}
    text = json.dumps(out)
    for leaked in ("A-1", "B-2", "1 Main St", "Jane Roe", "feature_key", "feature_id", "label"):
        assert leaked not in text
    far = await _outlines_route()(None, layer.id, bbox=view, zoom=13, db=pgdb)
    assert far["zoom_in"] is True and far["features"] == []
    monkeypatch.setattr(gis_layers, "MAX_BBOX_FEATURES", 2)
    capped = await _outlines_route()(None, layer.id, bbox=view, zoom=17, db=pgdb)
    assert capped["zoom_in"] is True and capped["features"] == []
    # Taken off the portal: gone.
    layer.show_on_resident_portal = False
    await pgdb.commit()
    with pytest.raises(HTTPException):
        await _outlines_route()(None, layer.id, bbox=view, zoom=17, db=pgdb)


# ------------------------------------------- categories residents see outlines in

def test_resident_categories_are_public_and_in_every_layer_schema():
    """The resident list is a list of category codes, not layer content: the
    public response carries it so the report form can filter outlines."""
    from app import schemas
    from app.api.map_layers import public_layer
    for name in ("MapLayerBase", "MapLayerUpdate", "MapLayerPolygonCreate", "MapLayerResponse"):
        assert "resident_service_codes" in getattr(schemas, name).model_fields, name
    out = public_layer(_ctx_layer(show_on_resident_portal=True, staff_properties=["PIN"],
                                  resident_service_codes=["potholes"]))
    assert out["resident_service_codes"] == ["potholes"]
    assert public_layer(_ctx_layer())["resident_service_codes"] is None  # NULL reads as all


@pg
async def test_resident_categories_round_trip(pgdb, staging):
    from app.api.map_layers import (create_polygon_layer, list_all_layers, list_context_layers,
                                    list_public_layers, update_layer)
    from app.schemas import MapLayerPolygonCreate, MapLayerUpdate
    _, _, staff, admin = await _seed_people(pgdb)
    raw = json.dumps(PARCELS).encode()
    up = gis_layers.start_upload(len(raw), admin.id)
    gis_layers.append_chunk(up["upload_id"], 0, raw, admin.id)
    out = await create_polygon_layer(MapLayerPolygonCreate(
        name="Springfield Parcels", upload_id=up["upload_id"],
        service_codes=["potholes"], resident_service_codes=["potholes", "streetlights"]),
        db=pgdb, admin=admin)
    assert out.service_codes == ["potholes"]
    assert out.resident_service_codes == ["potholes", "streetlights"]

    # Left out of an update: kept. An empty list: all categories again.
    kept = await update_layer(out.id, MapLayerUpdate(staff_properties=["PIN"]), db=pgdb, admin=admin)
    assert kept.resident_service_codes == ["potholes", "streetlights"]
    upd = await update_layer(out.id, MapLayerUpdate(resident_service_codes=["streetlights"],
                                                    service_codes=[], show_on_resident_portal=True),
                             db=pgdb, admin=admin)
    assert upd.resident_service_codes == ["streetlights"] and upd.service_codes == []

    [admin_row] = await list_all_layers(db=pgdb, _=admin)
    assert admin_row.resident_service_codes == ["streetlights"]
    [public_row] = await list_public_layers(db=pgdb)
    assert public_row["resident_service_codes"] == ["streetlights"]
    [staff_row] = await list_context_layers(db=pgdb, _=staff)
    assert staff_row["resident_service_codes"] == ["streetlights"] and staff_row["service_codes"] == []

    cleared = await update_layer(out.id, MapLayerUpdate(resident_service_codes=[]), db=pgdb, admin=admin)
    assert cleared.resident_service_codes == []
