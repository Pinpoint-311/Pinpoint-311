"""Map layers from an ArcGIS link, the township clip, the new upload limits, and auto-sync.

No real network: every ArcGIS answer comes from `FakeArcGis`, an in-process
server on httpx's MockTransport behind the real GuardedTransport (so the SSRF
guard, the pinning and the redirect handling are the shipped code), with a
fake resolver. The spatial half runs against a throwaway PostGIS named by
GIS_LAYERS_PG_URL, like tests/test_polygon_context_layers.py; each PG test
starts from an empty schema, so never point it at a real database.
"""

import asyncio
import inspect
import json
import logging
import os
from urllib.parse import parse_qs

import pytest

pytest.importorskip("sqlalchemy.orm")
pytest.importorskip("geoalchemy2")
httpx = pytest.importorskip("httpx")

from app.models import MapLayer  # noqa: E402
from app.services import arcgis_import as ag  # noqa: E402
from app.services import gis_layers  # noqa: E402
from app.services.arcgis_import import ArcGisClient, ArcGisError  # noqa: E402
from app.services.gis_layers import Clip, LayerUploadError  # noqa: E402

PUBLIC_IP = "93.184.216.34"
HOST = "gis.example.org"
SVC = "/arcgis/rest/services/County/Parcels/FeatureServer"
LAYER_URL = f"https://{HOST}{SVC}/0"
POINTS_URL = f"https://{HOST}{SVC}/1"
TOKEN = "sekrit-token-abc123XYZ"


# --------------------------------------------------------------- geometry

def square(x0, y0, size=0.001):
    return [[[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]]


def poly(oid, x0, y0, size=0.001, **props):
    return {"type": "Feature", "id": oid, "properties": {"OBJECTID": oid, **props},
            "geometry": {"type": "Polygon", "coordinates": square(x0, y0, size)}}


def point(oid, x, y, **props):
    return {"type": "Feature", "id": oid, "properties": {"OBJECTID": oid, **props},
            "geometry": {"type": "Point", "coordinates": [x, y]}}


def to_esri(feature):
    g = feature["geometry"]
    attrs = dict(feature["properties"])
    if g is None:
        return {"attributes": attrs, "geometry": None}
    if g["type"] == "Point":
        return {"attributes": attrs, "geometry": {"x": g["coordinates"][0], "y": g["coordinates"][1]}}
    rings = []
    for i, ring in enumerate(g["coordinates"]):
        # Esri: outer rings clockwise, holes counter-clockwise (GeoJSON is the reverse).
        rings.append(list(reversed(ring)))
    return {"attributes": attrs, "geometry": {"rings": rings}}


# The township: a 0.1 degree square, about 8.5 km x 11 km.
W, S, E, N = -74.10, 40.00, -74.00, 40.10
BOUNDARY = {"type": "Feature", "properties": {"name": "Testville"},
            "geometry": {"type": "Polygon", "coordinates": [[[W, S], [E, S], [E, N], [W, N], [W, S]]]}}


def county_parcels():
    """Inside, far outside, straddling, just over the line, and past the buffer."""
    return [
        poly(1, -74.05, 40.05, PIN="IN-1"),
        poly(2, -74.06, 40.06, PIN="IN-2"),
        poly(3, -74.07, 40.03, PIN="IN-3"),
        poly(4, -74.0007, 40.05, PIN="STRADDLE"),             # crosses the east edge, 70% inside
        poly(5, -73.9994, 40.05, PIN="BORDER"),               # ~50 m east of it: the neighbour's
        poly(6, -74.50, 40.50, PIN="FAR"),                    # another town entirely
        poly(7, -73.99, 40.05, PIN="EAST"),                   # ~850 m east: out
        # Off the north-east corner, diagonally ~113 m away: inside the
        # buffered outline's bounding box, outside the rounded corner.
        poly(8, E + 0.00094, N + 0.00072, size=0.00005, PIN="CORNER"),
    ]


# --------------------------------------------------------------- fake server

def _bbox(geom):
    return gis_layers.geometry_bbox(geom["coordinates"]) if geom else None


class FakeArcGis:
    def __init__(self):
        self.layers = {}
        self.items = {}
        self.services = {}
        self.redirects = {}
        self.hosts = {HOST: [PUBLIC_IP], "www.arcgis.com": [PUBLIC_IP], "hub.arcgis.com": [PUBLIC_IP]}
        self.requests = []
        self.require_token = None
        self.seen_by_transport = []

    def add_layer(self, path, features, *, geometry="esriGeometryPolygon", max_records=1000,
                  pagination=True, geojson=True, geojson_broken=False, name="Parcels", fields=None,
                  editing=None):
        self.layers[path] = {
            "features": features, "geometry": geometry, "max": max_records, "pagination": pagination,
            "geojson": geojson, "geojson_broken": geojson_broken, "name": name,
            "fields": fields, "editing": editing,
        }

    async def resolve(self, host, port):
        if host in self.hosts:
            return list(self.hosts[host])
        raise ArcGisError(ag.NO_SUCH_HOST)

    def client(self, token=None):
        return ArcGisClient(token, transport=httpx.MockTransport(self.handle), resolver=self.resolve)

    # -- http
    def handle(self, request: httpx.Request) -> httpx.Response:
        host = request.headers["host"]
        self.seen_by_transport.append((request.url.host, host, request.extensions.get("sni_hostname")))
        params = dict(request.url.params)
        if request.method == "POST":
            params.update({k: v[0] for k, v in parse_qs(request.content.decode()).items()})
        self.requests.append({"method": request.method, "host": host, "path": request.url.path,
                              "params": params, "url": str(request.url),
                              "headers": dict(request.headers)})
        path = request.url.path
        key = (host, path)
        if key in self.redirects:
            return httpx.Response(302, headers={"location": self.redirects[key]})
        if self.require_token is not None and params.get("token") != self.require_token:
            return self.json({"error": {"code": 499, "message": "Token Required"}})
        if host in ("www.arcgis.com", HOST) and path in self.items:
            return self.json(self.items[path])
        if path in self.services:
            return self.json(self.services[path])
        if path in self.layers:
            return self.json(self.meta(path))
        if path.endswith("/query") and path[:-6] in self.layers:
            return self.query(self.layers[path[:-6]], params)
        return httpx.Response(404, json={"error": {"code": 404}})

    @staticmethod
    def json(body, status=200):
        return httpx.Response(status, json=body, headers={"content-type": "application/json; charset=utf-8"})

    def meta(self, path):
        L = self.layers[path]
        fields = L["fields"] or sorted({k for f in L["features"] for k in f["properties"]})
        body = {
            "id": int(path.rsplit("/", 1)[1]), "name": L["name"], "type": "Feature Layer",
            "geometryType": L["geometry"], "objectIdField": "OBJECTID", "maxRecordCount": L["max"],
            "capabilities": "Query", "supportedQueryFormats": "JSON, geoJSON" if L["geojson"] else "JSON",
            "advancedQueryCapabilities": {"supportsPagination": L["pagination"]},
            "fields": [{"name": n, "type": "esriFieldTypeOID" if n == "OBJECTID" else "esriFieldTypeString"}
                       for n in fields] + [{"name": "Shape", "type": "esriFieldTypeGeometry"}],
        }
        if L["editing"] is not None:
            body["editingInfo"] = {"lastEditDate": L["editing"], "dataLastEditDate": L["editing"]}
        return body

    def query(self, L, params):
        feats = list(L["features"])
        if params.get("geometry"):
            assert params.get("geometryType") == "esriGeometryEnvelope"
            w, s, e, n = (float(v) for v in params["geometry"].split(","))
            feats = [f for f in feats if f["geometry"] and gis_layers._overlaps(_bbox(f["geometry"]), (w, s, e, n))]
        if params.get("objectIds"):
            wanted = {int(v) for v in params["objectIds"].split(",")}
            feats = [f for f in feats if f["properties"]["OBJECTID"] in wanted]
        if params.get("returnCountOnly") == "true":
            return self.json({"count": len(feats)})
        if params.get("returnIdsOnly") == "true":
            return self.json({"objectIdFieldName": "OBJECTID",
                              "objectIds": [f["properties"]["OBJECTID"] for f in feats]})
        if params.get("outStatistics"):
            top = max((f["properties"]["OBJECTID"] for f in feats), default=None)
            return self.json({"features": [{"attributes": {"max_oid": top}}]})
        exceeded = False
        if "resultOffset" in params:
            assert L["pagination"], "paged a layer that does not support pagination"
            off, want = int(params["resultOffset"]), int(params["resultRecordCount"])
            size = min(want, L["max"])
            exceeded = off + size < len(feats)
            feats = feats[off:off + size]
        fmt = params.get("f")
        if fmt == "geojson":
            if not L["geojson"] or L["geojson_broken"]:
                return self.json({"error": {"code": 400, "message": "Invalid or missing input parameters."}})
            body = {"type": "FeatureCollection", "features": feats}
            if exceeded:
                body["properties"] = {"exceededTransferLimit": True}
            return self.json(body)
        body = {"spatialReference": {"wkid": 4326}, "features": [to_esri(f) for f in feats]}
        if exceeded:
            body["exceededTransferLimit"] = True
        return self.json(body)

    def queries(self, kind="features"):
        out = []
        for r in self.requests:
            if not r["path"].endswith("/query"):
                continue
            p = r["params"]
            if kind == "features" and "outFields" in p:
                out.append(r)
        return out


@pytest.fixture
def fake(monkeypatch):
    server = FakeArcGis()
    monkeypatch.setattr(ag, "client_factory", server.client)
    return server


def no_clip():
    return Clip(applied=False, reason="no_boundary")


# =========================================================================
# What the admin pasted
# =========================================================================

@pytest.mark.parametrize("url,kind,canonical,layer", [
    (f"https://{HOST}{SVC}/0", "layer", f"https://{HOST}{SVC}/0", 0),
    (f"https://{HOST}{SVC}/3/query?where=1%3D1", "layer", f"https://{HOST}{SVC}/3", 3),
    (f"https://{HOST}{SVC}/", "service", f"https://{HOST}{SVC}", None),
    ("https://services.arcgis.com/AbC123/arcgis/rest/services/Trees/FeatureServer/0",
     "layer", "https://services.arcgis.com/AbC123/arcgis/rest/services/Trees/FeatureServer/0", 0),
    ("https://maps.example.gov/server/rest/services/Zoning/MapServer/2", "layer",
     "https://maps.example.gov/server/rest/services/Zoning/MapServer/2", 2),
    ("https://town.maps.arcgis.com/home/item.html?id=0123456789abcdef0123456789abcdef", "item",
     "https://town.maps.arcgis.com/sharing/rest/content/items/0123456789abcdef0123456789abcdef", None),
    ("https://gis.example.org/portal/home/item.html?id=0123456789ABCDEF0123456789abcdef", "item",
     "https://gis.example.org/portal/sharing/rest/content/items/0123456789abcdef0123456789abcdef", None),
    ("https://hub.arcgis.com/datasets/0123456789abcdef0123456789abcdef_2", "hub",
     "https://www.arcgis.com/sharing/rest/content/items/0123456789abcdef0123456789abcdef", 2),
])
def test_url_classification(url, kind, canonical, layer):
    parsed = ag.parse_url(url)
    assert (parsed.kind, parsed.url, parsed.layer_id) == (kind, canonical, layer)


@pytest.mark.parametrize("url,message", [
    ("https://data-town.hub.arcgis.com/datasets/town::tax-parcels", ag.HUB_UNRESOLVED),
    ("https://example.org/some/page.html", ag.NOT_A_LAYER),
    ("not a url", ag.NOT_A_LAYER),
    ("", ag.NOT_A_LAYER),
    (f"http://{HOST}{SVC}/0", ag.HTTPS_ONLY),
    (f"ftp://{HOST}{SVC}/0", ag.HTTPS_ONLY),
    (f"https://user:pw@{HOST}{SVC}/0", ag.NO_CREDENTIALS),
    (f"https://{HOST}{SVC}/0?token=abc", ag.TOKEN_IN_URL),
    (f"https://{HOST}:8080{SVC}/0", ag.BAD_PORT),
    (f"https://localhost{SVC}/0", ag.PRIVATE_ADDRESS),
    (f"https://gis.internal{SVC}/0", ag.PRIVATE_ADDRESS),
    (f"https://gisserver{SVC}/0", ag.PRIVATE_ADDRESS),
])
def test_junk_and_unsafe_urls_are_refused_with_plain_messages(url, message):
    with pytest.raises(ArcGisError) as exc:
        ag.parse_url(url)
    assert str(exc.value) == message


async def test_item_and_hub_resolve_to_the_layer(fake):
    item = "0123456789abcdef0123456789abcdef"
    fake.add_layer(SVC + "/0", [poly(1, -74.05, 40.05)])
    fake.items[f"/sharing/rest/content/items/{item}"] = {"type": "Feature Service", "url": f"https://{HOST}{SVC}"}
    async with fake.client() as client:
        parsed = await ag.resolve_item(client, ag.parse_url(f"https://www.arcgis.com/home/item.html?id={item}"))
        assert (parsed.kind, parsed.url) == ("service", f"https://{HOST}{SVC}")
        parsed = await ag.resolve_item(client, ag.parse_url(f"https://hub.arcgis.com/datasets/{item}_0"))
        assert (parsed.kind, parsed.url) == ("layer", f"https://{HOST}{SVC}/0")
        fake.items[f"/sharing/rest/content/items/{item}"] = {"type": "Web Map"}
        with pytest.raises(ArcGisError) as exc:
            await ag.resolve_item(client, ag.parse_url(f"https://www.arcgis.com/home/item.html?id={item}"))
        assert "Web Map" in str(exc.value)
        with pytest.raises(ArcGisError) as exc:
            await ag.resolve_item(client, ag.parse_url(f"https://hub.arcgis.com/datasets/{item}"))
        assert str(exc.value) == ag.HUB_UNRESOLVED


# =========================================================================
# The SSRF guard
# =========================================================================

@pytest.mark.parametrize("ip", [
    "127.0.0.1", "10.1.2.3", "172.16.5.4", "192.168.1.5", "169.254.169.254", "100.64.0.1",
    "0.0.0.0", "224.0.0.1", "::1", "fd00::1", "fe80::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1",
    "64:ff9b::a00:1", "2002:a00:1::", "192.0.2.10", "not-an-ip",
])
def test_internal_addresses_are_refused(ip):
    assert ag.ip_refused(ip)


@pytest.mark.parametrize("ip", [PUBLIC_IP, "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_pass(ip):
    assert not ag.ip_refused(ip)


@pytest.mark.parametrize("host_ips", [
    ["127.0.0.1"], ["10.0.0.7"], ["169.254.169.254"], ["::1"], ["fd00:ec2::254"],
    [PUBLIC_IP, "192.168.0.10"],   # any private answer refuses, not just the first
])
async def test_a_name_resolving_to_a_private_address_is_refused(fake, host_ips):
    fake.hosts["evil.example.com"] = host_ips
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(f"https://evil.example.com{SVC}/0", {"f": "json"})
    assert str(exc.value) == ag.PRIVATE_ADDRESS
    assert not fake.requests  # nothing left the building


@pytest.mark.parametrize("url", [
    f"https://127.0.0.1{SVC}/0", f"https://10.0.0.1{SVC}/0", f"https://169.254.169.254{SVC}/0",
    f"https://[::1]{SVC}/0", f"https://localhost{SVC}/0",
])
async def test_literal_internal_hosts_are_refused(fake, url):
    fake.hosts.update({"127.0.0.1": ["127.0.0.1"], "10.0.0.1": ["10.0.0.1"],
                       "169.254.169.254": ["169.254.169.254"], "::1": ["::1"], "localhost": ["127.0.0.1"]})
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(url, {"f": "json"})
    assert str(exc.value) == ag.PRIVATE_ADDRESS
    assert not fake.requests


async def test_http_is_refused_at_the_transport_too(fake):
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(f"http://{HOST}{SVC}/0", {"f": "json"})
    assert str(exc.value) == ag.HTTPS_ONLY


async def test_a_redirect_to_a_private_address_is_refused(fake):
    fake.add_layer(SVC + "/0", [])
    fake.hosts["internal.example.org"] = ["10.0.0.5"]
    fake.redirects[(HOST, SVC + "/0")] = f"https://internal.example.org{SVC}/0?f=json"
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(LAYER_URL, {"f": "json"})
    assert str(exc.value) == ag.PRIVATE_ADDRESS
    assert [r["host"] for r in fake.requests] == [HOST]


async def test_redirects_to_http_are_refused_and_public_hops_followed(fake):
    fake.add_layer(SVC + "/0", [])
    fake.redirects[(HOST, "/old" + SVC + "/0")] = f"http://{HOST}{SVC}/0?f=json"
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(f"https://{HOST}/old{SVC}/0", {"f": "json"})
        assert str(exc.value) == ag.HTTPS_ONLY
        fake.redirects[(HOST, "/old" + SVC + "/0")] = f"https://{HOST}{SVC}/0?f=json"
        body = await client.get_json(f"https://{HOST}/old{SVC}/0", {"f": "json"})
    assert body["name"] == "Parcels"


async def test_the_connection_goes_to_the_checked_address_with_the_name_kept_for_tls(fake):
    fake.add_layer(SVC + "/0", [])
    async with fake.client() as client:
        await client.get_json(LAYER_URL, {"f": "json"})
    assert fake.seen_by_transport == [(PUBLIC_IP, HOST, HOST)]
    ua = fake.requests[0]["headers"]["user-agent"]
    assert ua.startswith("Pinpoint311/") and ua.endswith("(gis-import)") and "@" not in ua


async def test_oversized_and_non_json_answers_are_refused_without_echoing_them(fake, monkeypatch):
    secret_page = "<html><body>internal admin console secret-value</body></html>"

    def handler(request):
        if request.url.path.endswith("/html"):
            return httpx.Response(200, text=secret_page, headers={"content-type": "text/html"})
        return httpx.Response(200, content=b'{"a": "' + b"x" * 5000 + b'"}',
                              headers={"content-type": "application/json"})

    monkeypatch.setattr(ag, "MAX_PAGE_BYTES", 1000)
    client = ArcGisClient(None, transport=httpx.MockTransport(handler), resolver=fake.resolve)
    async with client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(f"https://{HOST}/html", {})
        assert str(exc.value) == ag.WEB_PAGE and "secret" not in str(exc.value)
        with pytest.raises(ag.PageTooLarge):
            await client.get_json(f"https://{HOST}/big", {})


async def test_server_errors_become_short_messages(fake):
    fake.add_layer(SVC + "/0", [])
    fake.require_token = TOKEN
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(LAYER_URL, {"f": "json"})
        assert str(exc.value) == ag.TOKEN_NEEDED
    async with fake.client("wrong") as client:
        with pytest.raises(ArcGisError):
            await client.get_json(LAYER_URL, {"f": "json"})
    fake.require_token = None
    async with fake.client() as client:
        with pytest.raises(ArcGisError) as exc:
            await client.get_json(f"https://{HOST}{SVC}/9", {"f": "json"})
        assert str(exc.value) == ag.NOT_FOUND


def test_timeouts_and_limits_are_set():
    assert ag.CONNECT_TIMEOUT_S <= 5 and ag.REQUEST_TIMEOUT_S <= 30
    assert ag.MAX_PAGE_BYTES <= 64 * 1024 * 1024
    client = ArcGisClient(None)
    assert client._http.timeout.connect == ag.CONNECT_TIMEOUT_S
    assert client._http.follow_redirects is False
    assert isinstance(client._http._transport, ag.GuardedTransport)


# =========================================================================
# Describing and fetching
# =========================================================================

async def test_inspect_a_layer_and_a_service(fake):
    fake.add_layer(SVC + "/0", county_parcels())
    fake.add_layer(SVC + "/1", [point(1, -74.05, 40.05)], geometry="esriGeometryPoint", name="Hydrants")
    fake.add_layer(SVC + "/2", [], geometry="esriGeometryPolyline", name="Roads")
    fake.services[SVC] = {"layers": [{"id": 0, "name": "Parcels"}, {"id": 1, "name": "Hydrants"},
                                     {"id": 2, "name": "Roads"}, {"id": 9, "name": "Group", "subLayerIds": [0]}]}
    clip = Clip(applied=True, area_name="Testville", ewkb_hex="00", bbox=(W - 0.002, S - 0.002, E + 0.002, N + 0.002))
    async with fake.client() as client:
        one = await ag.inspect(client, LAYER_URL, clip)
        assert one["kind"] == "layer" and one["resolved_url"] == LAYER_URL
        [layer] = one["layers"]
        assert layer["geometry"] == "polygon" and layer["feature_count"] == 8
        assert layer["in_area_count"] < layer["feature_count"]
        assert "PIN" in layer["fields"] and "Shape" not in layer["fields"]
        many = await ag.inspect(client, f"https://{HOST}{SVC}", clip)
    assert many["kind"] == "service"
    by_name = {l["name"]: l for l in many["layers"]}
    assert set(by_name) == {"Parcels", "Hydrants", "Roads"}
    assert by_name["Hydrants"]["geometry"] == "point" and by_name["Hydrants"]["importable"]
    assert by_name["Roads"]["importable"] is False and by_name["Roads"]["problem"] == ag.LINES_UNSUPPORTED
    # The township's envelope rides on the count query.
    counted = [r["params"] for r in fake.requests if r["params"].get("returnCountOnly") == "true"]
    assert any(p.get("geometryType") == "esriGeometryEnvelope" and p.get("inSR") == "4326"
               and p.get("spatialRel") == "esriSpatialRelIntersects" for p in counted)


async def test_too_many_features_is_refused_up_front_without_a_boundary(fake, monkeypatch):
    fake.add_layer(SVC + "/0", [poly(i, -74.05 + i * 0.001, 40.05) for i in range(1, 6)])
    monkeypatch.setattr(gis_layers, "MAX_FEATURES", 3)
    async with fake.client() as client:
        out = await ag.inspect(client, LAYER_URL, no_clip())
        assert out["layers"][0]["problem"] == "Too many features: 5; the limit is 3."
        with pytest.raises(ArcGisError) as exc:
            await ag.describe_import_target(client, LAYER_URL, no_clip())
    assert str(exc.value) == "Too many features: 5; the limit is 3."
    assert not fake.queries()  # refused before a single feature was downloaded


async def _collect(client, info, **kw):
    out = []
    async for f in ag.iter_features(client, info, **kw):
        out.append(f)
    return out


async def test_paging_across_three_pages(fake):
    fake.add_layer(SVC + "/0", [poly(i, -74.05 + i * 0.001, 40.05) for i in range(1, 6)], max_records=2)
    async with fake.client() as client:
        info = await ag.describe_layer(client, LAYER_URL)
        feats = await _collect(client, info)
    assert [f["properties"]["OBJECTID"] for f in feats] == [1, 2, 3, 4, 5]
    pages = fake.queries()
    assert [int(p["params"]["resultOffset"]) for p in pages] == [0, 2, 4]
    assert all(p["params"]["outSR"] == "4326" and p["params"]["f"] == "geojson" for p in pages)
    assert all(p["params"]["orderByFields"] == "OBJECTID" for p in pages)


async def test_servers_without_pagination_are_read_by_object_ids(fake, monkeypatch):
    monkeypatch.setattr(ag, "ID_BATCH", 2)
    fake.add_layer(SVC + "/0", [poly(i, -74.05 + i * 0.001, 40.05) for i in range(1, 6)], pagination=False)
    async with fake.client() as client:
        info = await ag.describe_layer(client, LAYER_URL)
        feats = await _collect(client, info)
    assert sorted(f["properties"]["OBJECTID"] for f in feats) == [1, 2, 3, 4, 5]
    assert [p["params"]["objectIds"] for p in fake.queries()] == ["1,2", "3,4", "5"]


async def test_geojson_refused_falls_back_to_esri_json(fake):
    fake.add_layer(SVC + "/0", [poly(1, -74.05, 40.05, PIN="A"), poly(2, -74.06, 40.05, PIN="B")],
                   geojson_broken=True)
    async with fake.client() as client:
        info = await ag.describe_layer(client, LAYER_URL)
        assert info.supports_geojson
        feats = await _collect(client, info)
    assert [f["properties"]["PIN"] for f in feats] == ["A", "B"]
    assert feats[0]["geometry"]["type"] == "Polygon"
    assert [p["params"]["f"] for p in fake.queries()] == ["geojson", "json"]


async def test_servers_without_geojson_are_asked_for_esri_json_and_null_shapes_skipped(fake):
    feats = [point(1, -74.05, 40.05), {"type": "Feature", "properties": {"OBJECTID": 2}, "geometry": None},
             point(3, -74.06, 40.05)]
    fake.add_layer(SVC + "/1", feats, geometry="esriGeometryPoint", geojson=False)
    stats = ag.FetchStats()
    async with fake.client() as client:
        info = await ag.describe_layer(client, POINTS_URL)
        got = await _collect(client, info, stats=stats)
    assert [f["geometry"] for f in got] == [{"type": "Point", "coordinates": [-74.05, 40.05]},
                                            {"type": "Point", "coordinates": [-74.06, 40.05]}]
    assert stats.no_geometry == 1 and stats.format == "json"


def test_esri_json_conversion():
    assert ag.esri_to_geojson({"x": -74.0, "y": 40.0}) == {"type": "Point", "coordinates": [-74.0, 40.0]}
    assert ag.esri_to_geojson({"x": None, "y": None}) is None
    assert ag.esri_to_geojson({"x": "NaN", "y": 1}) is None
    assert ag.esri_to_geojson({"points": [[1, 2], [3, 4]]}) == {"type": "MultiPoint", "coordinates": [[1, 2], [3, 4]]}
    assert ag.esri_to_geojson({"paths": [[[0, 0], [1, 1]]]})["type"] == "LineString"
    assert ag.esri_to_geojson(None) is None and ag.esri_to_geojson({"rings": []}) is None

    outer = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]      # clockwise: an outer ring
    hole = [[2, 2], [4, 2], [4, 4], [2, 4], [2, 2]]          # counter-clockwise: a hole
    other = [[20, 0], [20, 5], [25, 5], [25, 0], [20, 0]]     # a second outer ring
    one = ag.esri_to_geojson({"rings": [outer, hole]})
    assert one["type"] == "Polygon" and len(one["coordinates"]) == 2
    assert ag._ring_area(one["coordinates"][0]) > 0           # RFC 7946: outer counter-clockwise
    assert ag._ring_area(one["coordinates"][1]) < 0
    two = ag.esri_to_geojson({"rings": [outer, other, hole]})
    assert two["type"] == "MultiPolygon" and [len(p) for p in two["coordinates"]] == [2, 1]
    # An unclosed ring is closed.
    closed = ag.esri_to_geojson({"rings": [outer[:-1]]})
    assert closed["coordinates"][0][0] == closed["coordinates"][0][-1]


def test_lines_are_refused_and_kinds_must_match():
    info = ag.LayerInfo(url=LAYER_URL, id=0, name="Roads", geometry="line", esri_geometry="esriGeometryPolyline",
                        fields=[], max_record_count=1000, supports_pagination=True, supports_geojson=True,
                        object_id_field="OBJECTID", can_query=True, layer_type="Feature Layer")
    with pytest.raises(ArcGisError) as exc:
        ag.check_kind(info, "polygons")
    assert str(exc.value) == ag.LINES_UNSUPPORTED
    info.geometry, info.esri_geometry = "point", "esriGeometryPoint"
    with pytest.raises(ArcGisError) as exc:
        ag.check_kind(info, "polygons")
    assert "only be imported as points" in str(exc.value)


# =========================================================================
# Upload limits (no database)
# =========================================================================

@pytest.fixture
def staging(monkeypatch, tmp_path):
    monkeypatch.setenv("MAP_LAYER_UPLOAD_DIR", str(tmp_path))
    return tmp_path / "pinpoint-layer-uploads"


def test_the_new_upload_limits():
    assert gis_layers.MAX_UPLOAD_BYTES == 500 * 1024 * 1024
    assert gis_layers.MAX_FEATURES == 500_000
    assert gis_layers.MAX_INLINE_FEATURES == 50_000
    assert gis_layers.MAX_INLINE_BYTES == 25 * 1024 * 1024
    # Each part still clears the 13 MB proxy/app body ceiling.
    assert gis_layers.UPLOAD_CHUNK_BYTES == 8 * 1024 * 1024


def test_size_refusal_names_the_real_limit(staging):
    with pytest.raises(LayerUploadError) as exc:
        gis_layers.start_upload(gis_layers.MAX_UPLOAD_BYTES + 1, 1)
    assert "500 MB" in str(exc.value)
    up = gis_layers.start_upload(gis_layers.MAX_UPLOAD_BYTES // 1000, 1)
    assert up["max_bytes"] == gis_layers.MAX_UPLOAD_BYTES


def test_disk_space_is_checked_against_twice_the_size_less_unfinished_uploads(staging, monkeypatch):
    mb = 1024 * 1024
    monkeypatch.setattr(gis_layers, "_free_bytes", lambda root: 100 * mb)
    gis_layers.start_upload(50 * mb, 1)          # needs 100, has 100
    with pytest.raises(gis_layers.UploadNoSpace) as exc:
        gis_layers.start_upload(30 * mb, 1)      # needs 60; the first upload's 50 MB is spoken for
    assert "does not have room" in str(exc.value) and "needs 60 MB free and has 50 MB" in str(exc.value)
    gis_layers.start_upload(25 * mb, 1)          # needs 50, has 50


def test_abandoned_uploads_are_pruned_in_pairs(staging, monkeypatch):
    import time as _time
    old = gis_layers.start_upload(10, 1)
    fresh = gis_layers.start_upload(10, 1)
    long_ago = _time.time() - gis_layers.UPLOAD_IDLE_SECONDS - 60
    for path in staging.glob(old["upload_id"] + ".*"):
        os.utime(path, (long_ago, long_ago))
    assert gis_layers.prune_stale_uploads() == 2
    names = {p.name for p in staging.iterdir()}
    assert not any(n.startswith(old["upload_id"]) for n in names)
    assert {fresh["upload_id"] + ".geojson", fresh["upload_id"] + ".json"} <= names


def test_inline_cap(monkeypatch):
    monkeypatch.setattr(gis_layers, "MAX_INLINE_FEATURES", 2)
    gis_layers.check_inline_size({"type": "FeatureCollection", "features": [point(1, 0, 0), point(2, 0, 0)]})
    with pytest.raises(LayerUploadError) as exc:
        gis_layers.check_inline_size({"type": "FeatureCollection", "features": [point(i, 0, 0) for i in range(3)]})
    assert "Split it into several layers" in str(exc.value) and "polygon layer" in str(exc.value)
    monkeypatch.setattr(gis_layers, "MAX_INLINE_BYTES", 100)
    with pytest.raises(LayerUploadError):
        gis_layers.check_inline_size({"type": "FeatureCollection", "features": [point(1, 0, 0, NOTE="x" * 200)]})


async def test_points_without_a_boundary_import_everything_and_say_so(monkeypatch):
    feats = [point(i, -74.05, 40.05) for i in range(3)]
    geojson, summary = await gis_layers.build_inline_points(None, feats, clip=no_clip())
    assert len(geojson["features"]) == 3
    assert summary["clip_message"] == ("No township boundary is set, so all 3 features were imported. "
                                       "Set one in Setup to limit layers to the township.")
    with pytest.raises(LayerUploadError) as exc:
        await gis_layers.build_inline_points(None, [poly(1, 0, 0)], clip=no_clip())
    assert "polygon layer" in str(exc.value)


def test_new_routes_are_admin_only_and_rate_limited():
    from app.api import map_layers
    from app.core.route_access import ADMIN, route_access
    routes = {r.endpoint.__name__: r for r in map_layers.router.routes}
    for name in ("inspect_arcgis_link", "import_arcgis_layer", "arcgis_job_status", "refresh_arcgis_layer",
                 "check_arcgis_layer_now", "set_arcgis_sync", "create_point_layer"):
        assert route_access(routes[name]) == ADMIN, name
    for fn in (map_layers.inspect_arcgis_link, map_layers.import_arcgis_layer, map_layers.refresh_arcgis_layer,
               map_layers.check_arcgis_layer_now, map_layers.set_arcgis_sync):
        assert fn is not inspect.unwrap(fn), "not rate limited"


def test_the_beat_schedule_runs_the_sync_hourly():
    from app.core.celery_app import celery_app
    entry = celery_app.conf.beat_schedule["hourly-arcgis-layer-sync"]
    assert entry["task"] == "app.tasks.arcgis_sync.sync_arcgis_layers"
    import app.tasks.arcgis_sync  # noqa: F401  (registered)
    assert "app.tasks.arcgis_sync.sync_arcgis_layers" in celery_app.tasks


def test_sync_is_off_by_default_and_the_health_check_is_registered():
    from app.services import proactive_health
    assert "arcgis_sync" in proactive_health.CHECK_KEYS
    assert MapLayer.__table__.c.source_sync.default is None
    assert MapLayer.__table__.c.source_sync.nullable


def test_the_new_columns_are_in_the_combined_migration():
    import glob
    [path] = glob.glob(os.path.join(os.path.dirname(__file__), "..", "alembic", "versions", "e3a5c7d9f1b2_*.py"))
    text = open(path).read()
    for col in ("source_url", "source_synced_at", "source_sync", "source_last_edit", "source_checked_at",
                "source_sync_status", "source_sync_error"):
        assert f'"map_layers", sa.Column("{col}"' in text, col
        assert f'op.drop_column("map_layers", "{col}")' in text, col
        assert col in MapLayer.__table__.c


# =========================================================================
# PostGIS
# =========================================================================

PG_URL = os.environ.get("GIS_LAYERS_PG_URL")
pg = pytest.mark.skipif(not PG_URL, reason="needs a throwaway PostGIS (GIS_LAYERS_PG_URL)")


@pytest.fixture
async def pgmaker():
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
    yield maker
    await engine.dispose()


@pytest.fixture
async def pgdb(pgmaker):
    async with pgmaker() as session:
        yield session


async def _set_boundary(db, boundary=BOUNDARY, name="Testville"):
    from app.models import SystemSettings
    db.add(SystemSettings(township_name=name, township_boundary=boundary))
    await db.commit()


async def _admin(db):
    from app.models import User
    admin = User(username="boss", email="b@example.org", role="admin", is_active=True)
    db.add(admin)
    await db.commit()
    return admin


def _factory(maker):
    async def make():
        return maker()
    return make


async def _keys(db, layer_id):
    from sqlalchemy import text
    rows = (await db.execute(text(
        "SELECT feature_key FROM map_layer_features WHERE layer_id = :l ORDER BY feature_key"),
        {"l": layer_id})).scalars().all()
    return list(rows)


async def _new_table_layer(db, name="Parcels"):
    layer = MapLayer(name=name, layer_type="polygon", routing_mode="context", feature_storage="table",
                     geojson=dict(gis_layers.EMPTY_FEATURE_COLLECTION), is_active=True,
                     show_on_resident_portal=False, staff_properties=[])
    db.add(layer)
    await db.flush()
    return layer


@pg
async def test_upload_keeps_only_the_townships_own_parcels(pgdb):
    await _set_boundary(pgdb)
    clip = await gis_layers.load_clip(pgdb)
    assert clip.applied and clip.area_name == "Testville"
    layer = await _new_table_layer(pgdb)
    summary = await gis_layers.import_features(
        pgdb, layer, gis_layers.iter_inline_features({"type": "FeatureCollection", "features": county_parcels()}),
        clip=clip)
    await pgdb.commit()
    # STRADDLE is mostly inside, so it is the town's; BORDER, in the 100 m margin
    # but wholly outside the line, is the neighbour's.
    assert await _keys(pgdb, layer.id) == ["IN-1", "IN-2", "IN-3", "STRADDLE"]
    assert summary["feature_count"] == 4 and summary["outside"] == 4
    assert summary["clip_message"] == "Kept 4 of 8 features inside Testville."


@pg
async def test_a_neighbours_parcel_on_the_town_line_is_dropped_and_a_big_zone_is_trimmed(pgdb):
    from sqlalchemy import text
    await _set_boundary(pgdb)
    clip = await gis_layers.load_clip(pgdb)
    layer = await _new_table_layer(pgdb)
    feats = [
        # Shares the east edge exactly: touches the boundary, nothing inside.
        poly(1, E, 40.05, size=0.002, PIN="NEIGHBOUR"),
        # Mostly outside, with a sliver (~10 m x 220 m) over the line: the neighbour's.
        poly(2, E - 0.0001, 40.06, size=0.002, PIN="SLIVER"),
        # A county zone: a third of it is in town, several km² of it.
        {"type": "Feature", "id": 3, "properties": {"OBJECTID": 3, "PIN": "ZONE"},
         "geometry": {"type": "Polygon", "coordinates": [[[E - 0.05, S], [E + 0.10, S], [E + 0.10, N],
                                                          [E - 0.05, N], [E - 0.05, S]]]}},
    ]
    summary = await gis_layers.import_features(
        pgdb, layer, gis_layers.iter_inline_features({"type": "FeatureCollection", "features": feats}), clip=clip)
    await pgdb.commit()
    assert await _keys(pgdb, layer.id) == ["ZONE"]
    assert summary["outside"] == 2
    # Trimmed to the town and its 100 m margin, not 10 km east of it.
    east = (await pgdb.execute(text(
        "SELECT ST_XMax(geom) FROM map_layer_features WHERE layer_id = :l"), {"l": layer.id})).scalar_one()
    assert east < E + 0.002


@pg
async def test_no_boundary_imports_everything_and_says_so(pgdb):
    clip = await gis_layers.load_clip(pgdb)
    assert not clip.applied and clip.reason == "no_boundary"
    layer = await _new_table_layer(pgdb)
    summary = await gis_layers.import_features(pgdb, layer, county_parcels(), clip=clip)
    assert summary["feature_count"] == 8
    assert summary["clip_message"].startswith("No township boundary is set, so all 8 features were imported.")


@pg
async def test_the_cap_counts_features_after_the_clip(pgdb, monkeypatch):
    await _set_boundary(pgdb, name="Your Township")  # the placeholder name is not used
    clip = await gis_layers.load_clip(pgdb)
    assert clip.area_name is None
    monkeypatch.setattr(gis_layers, "MAX_FEATURES", 5)
    monkeypatch.setattr(gis_layers, "INSERT_BATCH", 2)
    county = county_parcels() + [poly(100 + i, -74.6 + i * 0.002, 40.6) for i in range(20)]
    layer = await _new_table_layer(pgdb)
    summary = await gis_layers.import_features(pgdb, layer, county, clip=clip)  # 28 read, 4 in town
    assert summary["feature_count"] == 4
    assert summary["clip_message"] == "Kept 4 of 28 features within your township boundary."
    await pgdb.rollback()
    layer = await _new_table_layer(pgdb)
    with pytest.raises(LayerUploadError) as exc:
        await gis_layers.import_features(
            pgdb, layer, county + [poly(98, -74.08, 40.08), poly(99, -74.085, 40.085)], clip=clip)
    assert "more than 5 features inside your township boundary" in str(exc.value)


@pg
async def test_points_are_clipped_then_capped(pgdb, monkeypatch):
    await _set_boundary(pgdb)
    clip = await gis_layers.load_clip(pgdb)
    pts = [point(1, -74.05, 40.05), point(2, -73.9995, 40.05), point(3, -74.5, 40.5),
           point(4, E + 0.00094, N + 0.00072), point(5, -74.06, 40.06)]
    monkeypatch.setattr(gis_layers, "MAX_INLINE_FEATURES", 3)
    geojson, summary = await gis_layers.build_inline_points(pgdb, pts, clip=clip)
    assert [f["properties"]["OBJECTID"] for f in geojson["features"]] == [1, 2, 5]
    assert summary["clip_message"] == "Kept 3 of 5 features inside Testville."
    with pytest.raises(LayerUploadError) as exc:
        await gis_layers.build_inline_points(pgdb, pts + [point(6, -74.07, 40.07)], clip=clip)
    assert "more than 3 points inside Testville" in str(exc.value)


@pg
async def test_point_file_goes_up_in_parts_and_is_stored_inline(pgdb, staging):
    from app.api.map_layers import create_point_layer, reupload_layer_features
    from app.schemas import MapLayerFeatureReupload, MapLayerPointCreate
    await _set_boundary(pgdb)
    admin = await _admin(pgdb)
    raw = json.dumps({"type": "FeatureCollection",
                      "features": [point(1, -74.05, 40.05, NAME="Hydrant 1"), point(2, -74.5, 40.5)]}).encode()
    up = gis_layers.start_upload(len(raw), admin.id)
    gis_layers.append_chunk(up["upload_id"], 0, raw[:20], admin.id)
    gis_layers.append_chunk(up["upload_id"], 1, raw[20:], admin.id)
    out = await create_point_layer(MapLayerPointCreate(name="Hydrants", upload_id=up["upload_id"]),
                                   db=pgdb, admin=admin)
    assert out.feature_storage == "inline" and out.layer_type == "point"
    assert [f["properties"].get("NAME") for f in out.geojson["features"]] == ["Hydrant 1"]
    assert out.import_summary["clip_message"] == "Kept 1 of 2 features inside Testville."
    # Replacing a point layer's file takes the same chunked path.
    raw2 = json.dumps({"type": "FeatureCollection",
                       "features": [point(1, -74.05, 40.05), point(2, -74.06, 40.06)]}).encode()
    up2 = gis_layers.start_upload(len(raw2), admin.id)
    gis_layers.append_chunk(up2["upload_id"], 0, raw2, admin.id)
    again = await reupload_layer_features(out.id, MapLayerFeatureReupload(upload_id=up2["upload_id"]),
                                          db=pgdb, admin=admin)
    assert len(again.geojson["features"]) == 2 and again.feature_count == 2


@pg
async def test_create_layer_refuses_an_inline_layer_over_the_cap(pgdb, monkeypatch):
    from fastapi import HTTPException
    from app.api.map_layers import create_layer
    from app.schemas import MapLayerCreate
    admin = await _admin(pgdb)
    monkeypatch.setattr(gis_layers, "MAX_INLINE_FEATURES", 1)
    with pytest.raises(HTTPException) as exc:
        await create_layer(MapLayerCreate(name="Trees", layer_type="point", geojson={
            "type": "FeatureCollection", "features": [point(1, 0, 0), point(2, 0, 0)]}), db=pgdb, admin=admin)
    assert exc.value.status_code == 400 and "Split it" in exc.value.detail


# ------------------------------------------------- ArcGIS import end to end

def _import_request(**kw):
    from app.schemas import ArcGisImportRequest
    body = {"url": LAYER_URL, "name": "County Parcels", "as": "polygons", **kw}
    return ArcGisImportRequest(**body)


class _Job:
    read = 0
    expected = None


@pg
async def test_arcgis_polygon_import_matches_an_upload_and_sends_the_spatial_filter(pgdb, pgmaker, fake, staging):
    from app.api.map_layers import _run_arcgis_import, create_polygon_layer
    from app.schemas import MapLayerPolygonCreate
    await _set_boundary(pgdb)
    admin = await _admin(pgdb)
    fake.add_layer(SVC + "/0", county_parcels(), max_records=2)

    job = _Job()
    result = await _run_arcgis_import(job, _import_request(), admin.id, session_factory=_factory(pgmaker))
    layer = result["layer"]
    assert layer["feature_storage"] == "table" and layer["layer_type"] == "polygon"
    assert layer["routing_mode"] == "context" and layer["staff_properties"] == []
    assert layer["show_on_resident_portal"] is False
    assert layer["source_url"] == LAYER_URL and layer["source_synced_at"]
    assert layer["source_sync"] is None                      # off by default
    assert layer["feature_id_property"] == "PIN"
    assert layer["import_summary"]["clip_message"] == "Kept 4 of 6 features inside Testville."
    assert job.read == 6
    # Only the township's envelope was asked for: FAR and EAST never left the server.
    for q in fake.queries():
        p = q["params"]
        assert (p["geometryType"], p["inSR"], p["spatialRel"]) == (
            "esriGeometryEnvelope", "4326", "esriSpatialRelIntersects")
        w, s, e, n = (float(v) for v in p["geometry"].split(","))
        assert w < W and s < S and e > E and n > N and e - E < 0.01

    # The same features as a file upload give the same layer.
    raw = json.dumps({"type": "FeatureCollection", "features": county_parcels()}).encode()
    up = gis_layers.start_upload(len(raw), admin.id)
    gis_layers.append_chunk(up["upload_id"], 0, raw, admin.id)
    uploaded = await create_polygon_layer(MapLayerPolygonCreate(name="Upload", upload_id=up["upload_id"]),
                                          db=pgdb, admin=admin)
    assert uploaded.feature_count == layer["feature_count"] == 4
    assert await _keys(pgdb, uploaded.id) == await _keys(pgdb, layer["id"])
    assert uploaded.available_properties == layer["available_properties"]


@pg
async def test_arcgis_point_import_is_inline(pgdb, pgmaker, fake):
    from app.api.map_layers import _run_arcgis_import
    await _set_boundary(pgdb)
    admin = await _admin(pgdb)
    fake.add_layer(SVC + "/1", [point(1, -74.05, 40.05), point(2, -74.5, 40.5)],
                   geometry="esriGeometryPoint", geojson=False)
    result = await _run_arcgis_import(_Job(), _import_request(url=POINTS_URL, **{"as": "points"}), admin.id,
                                      session_factory=_factory(pgmaker))
    layer = result["layer"]
    assert layer["feature_storage"] == "inline" and layer["layer_type"] == "point"
    assert len(layer["geojson"]["features"]) == 1 and layer["source_url"] == POINTS_URL
    with pytest.raises(ArcGisError):
        await _run_arcgis_import(_Job(), _import_request(url=POINTS_URL), admin.id,
                                 session_factory=_factory(pgmaker))


@pg
async def test_arcgis_points_obey_the_inline_cap_and_stop_downloading(pgdb, pgmaker, fake, monkeypatch):
    from app.api.map_layers import _run_arcgis_import
    admin = await _admin(pgdb)
    monkeypatch.setattr(gis_layers, "MAX_INLINE_FEATURES", 3)
    monkeypatch.setattr(gis_layers, "POINT_BATCH", 2)
    monkeypatch.setattr(ag, "count_problem", lambda info, clip: None)  # as if the count was unknown
    fake.add_layer(SVC + "/1", [point(i, -74.05 + i * 0.0001, 40.05) for i in range(1, 21)],
                   geometry="esriGeometryPoint", max_records=2)
    with pytest.raises(LayerUploadError) as exc:
        await _run_arcgis_import(_Job(), _import_request(url=POINTS_URL, **{"as": "points"}), admin.id,
                                 session_factory=_factory(pgmaker))
    assert "more than 3 points" in str(exc.value)
    assert len(fake.queries()) < 10  # stopped at the cap, not after all ten pages
    from sqlalchemy import select, func
    assert (await pgdb.execute(select(func.count(MapLayer.id)))).scalar() == 0  # nothing half-made


@pg
async def test_the_token_is_used_but_never_stored_or_logged(pgdb, pgmaker, fake, caplog):
    from sqlalchemy import text
    from app.api.map_layers import _run_arcgis_import
    caplog.set_level(logging.DEBUG)
    admin = await _admin(pgdb)
    fake.require_token = TOKEN
    fake.add_layer(SVC + "/0", county_parcels()[:3])
    with pytest.raises(ArcGisError) as exc:
        await _run_arcgis_import(_Job(), _import_request(), admin.id, session_factory=_factory(pgmaker))
    assert str(exc.value) == ag.TOKEN_NEEDED
    result = await _run_arcgis_import(_Job(), _import_request(token=TOKEN, source_sync="daily"), admin.id,
                                      session_factory=_factory(pgmaker))
    assert result["layer"]["feature_count"] == 3
    assert result["layer"]["source_sync"] is None  # a secured service cannot auto-sync
    sent = [r for r in fake.requests if r["params"].get("token") == TOKEN]
    assert sent and all(r["method"] == "POST" for r in sent)
    assert all(TOKEN not in r["url"] for r in fake.requests)       # never in a URL
    assert all(r["headers"].get("x-esri-authorization") == f"Bearer {TOKEN}" for r in sent)
    assert TOKEN not in caplog.text
    assert TOKEN not in json.dumps(result, default=str)
    dump = json.dumps([dict(r) for r in (await pgdb.execute(text("SELECT * FROM map_layers"))).mappings()],
                      default=str)
    assert TOKEN not in dump
    audit = json.dumps([dict(r) for r in (await pgdb.execute(text("SELECT * FROM audit_logs"))).mappings()],
                       default=str)
    assert "map_layer_imported" in audit and TOKEN not in audit


@pg
async def test_refresh_replaces_features_atomically_with_stable_keys(pgdb, pgmaker, fake):
    from app.api.map_layers import _run_arcgis_import, _run_arcgis_refresh
    await _set_boundary(pgdb)
    admin = await _admin(pgdb)
    first = [poly(1, -74.05, 40.05, PIN="A"), poly(2, -74.06, 40.05, PIN="B"), poly(3, -74.07, 40.05, PIN="C")]
    fake.add_layer(SVC + "/0", first)
    result = await _run_arcgis_import(_Job(), _import_request(), admin.id, session_factory=_factory(pgmaker))
    layer_id = result["layer"]["id"]
    assert await _keys(pgdb, layer_id) == ["A", "B", "C"]

    # The source changes: B edited, C deleted, D added. A keeps its key; so does B.
    fake.layers[SVC + "/0"]["features"] = [poly(1, -74.05, 40.05, PIN="A"), poly(2, -74.06, 40.05, PIN="B", ZONE="R2"),
                                           poly(4, -74.08, 40.05, PIN="D")]
    out = await _run_arcgis_refresh(_Job(), layer_id, None, admin.id, guard=False,
                                    session_factory=_factory(pgmaker))
    assert (out["before"], out["after"]) == (3, 3)
    assert await _keys(pgdb, layer_id) == ["A", "B", "D"]

    # A failing refresh leaves the old features exactly as they were.
    fake.layers[SVC + "/0"]["features"] = [poly(1, 10.0, 10.0, PIN="A")] + [
        {"type": "Feature", "properties": {"OBJECTID": 9}, "geometry": {"type": "Polygon", "coordinates": [[[0, 0]]]}}]
    with pytest.raises((ArcGisError, LayerUploadError)):
        await _run_arcgis_refresh(_Job(), layer_id, None, admin.id, guard=False, session_factory=_factory(pgmaker))
    assert await _keys(pgdb, layer_id) == ["A", "B", "D"]


# ------------------------------------------------------------- auto-sync

async def _synced_layer(pgdb, pgmaker, fake, features, *, editing=1000):
    from app.api.map_layers import _run_arcgis_import
    admin = await _admin(pgdb)
    fake.add_layer(SVC + "/0", features, editing=editing)
    result = await _run_arcgis_import(_Job(), _import_request(source_sync="daily"), admin.id,
                                      session_factory=_factory(pgmaker))
    assert result["layer"]["source_sync"] == "daily"
    return result["layer"]["id"], admin


async def _sync_once(pgmaker, layer_id, fake):
    from sqlalchemy import select
    async with pgmaker() as db:
        layer = (await db.execute(select(MapLayer).where(MapLayer.id == layer_id))).scalar_one()
        return await ag.sync_layer(db, layer, client_for=fake.client)


async def _layer(pgmaker, layer_id):
    from sqlalchemy import select
    async with pgmaker() as db:
        return (await db.execute(select(MapLayer).where(MapLayer.id == layer_id))).scalar_one()


def ten(start=0, **props):
    return [poly(i + 1, -74.09 + (i + start) * 0.002, 40.05, PIN=f"P{i + start}", **props) for i in range(10)]


@pg
async def test_an_unchanged_source_is_not_downloaded(pgdb, pgmaker, fake):
    layer_id, _ = await _synced_layer(pgdb, pgmaker, fake, ten())
    fake.requests.clear()
    result = await _sync_once(pgmaker, layer_id, fake)
    assert result["state"] == "unchanged"
    assert not fake.queries()          # no feature page fetched
    assert len(fake.requests) <= 2     # the layer's JSON (and nothing else, with an edit date)
    assert (await _layer(pgmaker, layer_id)).source_sync_status == "ok"


@pg
async def test_count_and_max_objectid_are_the_marker_without_an_edit_date(pgdb, pgmaker, fake):
    layer_id, _ = await _synced_layer(pgdb, pgmaker, fake, ten(), editing=None)
    assert (await _layer(pgmaker, layer_id)).source_last_edit == "count:10:max:10"
    assert (await _sync_once(pgmaker, layer_id, fake))["state"] == "unchanged"
    fake.layers[SVC + "/0"]["features"] = ten() + [poly(11, -74.01, 40.06, PIN="NEW")]
    assert (await _sync_once(pgmaker, layer_id, fake))["state"] == "updated"


@pg
async def test_a_changed_source_is_applied_and_audited(pgdb, pgmaker, fake):
    from sqlalchemy import text
    layer_id, _ = await _synced_layer(pgdb, pgmaker, fake, ten())
    fake.layers[SVC + "/0"].update(features=ten() + [poly(11, -74.01, 40.06, PIN="NEW")], editing=2000)
    result = await _sync_once(pgmaker, layer_id, fake)
    assert result["state"] == "updated" and (result["before"], result["after"]) == (10, 11)
    layer = await _layer(pgmaker, layer_id)
    assert layer.feature_count == 11 and layer.source_sync_status == "updated"
    assert layer.source_last_edit == "edit:2000"
    events = (await pgdb.execute(text("SELECT event_type FROM audit_logs"))).scalars().all()
    assert "map_layer_sync_applied" in events


GUARDRAILS = {
    "drop": (lambda: ten()[:7], "drop from 10 to 7"),
    "growth": (lambda: [poly(i + 1, -74.09 + i * 0.0015, 40.05 + (i % 3) * 0.002, PIN=f"P{i}") for i in range(31)],
               "rise from 10 to 31"),
    "zero": (lambda: [poly(1, -74.5, 40.5, PIN="FAR")], "no features"),
    "geometry": (None, "geometry type changed from polygon to point"),
    "id_field": (lambda: [poly(i + 1, -74.09 + i * 0.002, 40.05, PARCEL=f"P{i}") for i in range(10)],
                 "ID field PIN is no longer in the source"),
    "fetch_error": (None, "Couldn't read the source"),
}


@pg
@pytest.mark.parametrize("case", list(GUARDRAILS))
async def test_guardrails_hold_the_old_data_and_warn(pgdb, pgmaker, fake, case):
    from sqlalchemy import text
    from app.services import proactive_health
    await _set_boundary(pgdb)
    layer_id, _ = await _synced_layer(pgdb, pgmaker, fake, ten())
    before = await _keys(pgdb, layer_id)
    make, expected = GUARDRAILS[case]
    L = fake.layers[SVC + "/0"]
    L["editing"] = 2000
    if case == "geometry":
        L["geometry"] = "esriGeometryPoint"
    elif case == "fetch_error":
        fake.layers.pop(SVC + "/0")
    else:
        L["features"] = make()
        if case == "id_field":
            L["fields"] = ["OBJECTID", "PARCEL"]
    result = await _sync_once(pgmaker, layer_id, fake)
    assert result["state"] == "held", result
    assert expected in result["reason"]
    layer = await _layer(pgmaker, layer_id)
    assert layer.source_sync_status == "held" and expected in layer.source_sync_error
    assert layer.feature_count == 10 and await _keys(pgdb, layer_id) == before
    assert layer.source_last_edit == "edit:1000"  # still waiting on the new version
    events = (await pgdb.execute(text("SELECT event_type FROM audit_logs"))).scalars().all()
    assert "map_layer_sync_held" in events
    async with pgmaker() as db:
        check = await proactive_health._arcgis_sync_check(db)
    assert check["status"] == "warning" and "County Parcels" in check["message"] and expected in check["message"]


@pg
async def test_apply_anyway_overrides_a_held_sync(pgdb, pgmaker, fake):
    from app.api.map_layers import _run_arcgis_refresh
    from app.services import proactive_health
    layer_id, admin = await _synced_layer(pgdb, pgmaker, fake, ten())
    fake.layers[SVC + "/0"].update(features=ten()[:5], editing=2000)
    assert (await _sync_once(pgmaker, layer_id, fake))["state"] == "held"
    out = await _run_arcgis_refresh(_Job(), layer_id, None, admin.id, guard=False, apply_anyway=True,
                                    session_factory=_factory(pgmaker))
    assert (out["before"], out["after"]) == (10, 5)
    layer = await _layer(pgmaker, layer_id)
    assert layer.feature_count == 5 and layer.source_sync_status == "updated" and layer.source_sync_error is None
    async with pgmaker() as db:
        assert (await proactive_health._arcgis_sync_check(db))["status"] == "ok"


@pg
async def test_a_secured_service_is_held_with_the_public_only_message(pgdb, pgmaker, fake):
    layer_id, _ = await _synced_layer(pgdb, pgmaker, fake, ten())
    fake.require_token = TOKEN
    result = await _sync_once(pgmaker, layer_id, fake)
    assert result["state"] == "held" and result["reason"] == ag.SYNC_NEEDS_PUBLIC


@pg
async def test_only_due_layers_are_synced(pgdb, pgmaker, fake):
    from datetime import datetime, timedelta, timezone
    layer_id, _ = await _synced_layer(pgdb, pgmaker, fake, ten())
    now = datetime.now(timezone.utc)
    async with pgmaker() as db:
        out = await ag.run_due_syncs(db, now=now, client_for=fake.client)
    assert out["checked"] == 0  # checked at import time
    async with pgmaker() as db:
        out = await ag.run_due_syncs(db, now=now + timedelta(hours=24), client_for=fake.client)
    assert out["checked"] == 1
    async with pgmaker() as db:
        layer = (await db.execute(__import__("sqlalchemy").select(MapLayer))).scalar_one()
        layer.source_sync = None
        await db.commit()
        out = await ag.run_due_syncs(db, now=now + timedelta(days=30), client_for=fake.client)
    assert out["checked"] == 0
