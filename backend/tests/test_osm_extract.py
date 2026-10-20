"""Critical facilities from a Geofabrik extract, with Overpass as the fallback.

The extract is a small .pbf written here with osmium, so nothing touches the
network; downloads go through an httpx mock transport.
"""
import hashlib

import httpx
import pytest

from app.services import critical_facilities as cf
from app.services import osm_extract as X

BBOX = (-74.30, 39.70, -74.20, 39.80)


# ------------------------------------------------------------------ regions

def _square(minx, miny, maxx, maxy):
    return {"type": "MultiPolygon", "coordinates": [[[[minx, miny], [maxx, miny], [maxx, maxy],
                                                      [minx, maxy], [minx, miny]]]]}


def _region(rid, geometry, url=None):
    return {"type": "Feature", "geometry": geometry, "properties": {
        "id": rid, "urls": {"pbf": url or f"https://download.geofabrik.de/{rid}-latest.osm.pbf"}}}


INDEX = {"features": [
    _region("north-america", _square(-170, 10, -50, 80)),
    _region("us-northeast", _square(-81, 38, -66, 48)),
    _region("us/new-jersey", _square(-75.0, 38.9, -73.8, 41.4)),
    _region("us/pennsylvania", _square(-80.6, 39.7, -74.9, 42.3)),
    _region("evil", _square(-74.5, 39.5, -74.0, 40.0), url="https://attacker.example/x.osm.pbf"),
]}


def test_the_smallest_region_containing_the_town_is_chosen():
    assert X.pick_regions(INDEX, BBOX) == [
        ("us/new-jersey", "https://download.geofabrik.de/us/new-jersey-latest.osm.pbf")]


def test_a_town_on_a_state_line_gets_both_states_not_the_whole_northeast():
    ids = [rid for rid, _ in X.pick_regions(INDEX, (-75.1, 40.1, -74.85, 40.2))]
    assert ids == ["us/new-jersey", "us/pennsylvania"]


def test_regions_whose_download_is_not_on_geofabrik_are_ignored():
    assert all("attacker" not in url for _, url in X.pick_regions(INDEX, BBOX))
    with pytest.raises(X.ExtractError):
        X.regions_by_id(INDEX, ["evil"])


def test_configured_regions(monkeypatch):
    from app.core import config

    class S:
        geofabrik_regions = ""
    monkeypatch.setattr(config, "get_settings", lambda: S)
    assert X.configured_regions() is None
    S.geofabrik_regions = "off"
    assert X.configured_regions() == []
    S.geofabrik_regions = "us/new-jersey, us/pennsylvania"
    assert X.configured_regions() == ["us/new-jersey", "us/pennsylvania"]


# ------------------------------------------------------------------ reading

def _write_extract(path):
    osmium = pytest.importorskip("osmium")
    from osmium.osm.mutable import Node, Relation, Way

    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", "2026-10-18T20:25:06Z")
    w = osmium.SimpleWriter(str(path), header=header)
    # 1-4: a hospital building; 5: a fire station node; 6: a school node outside
    # the box; 7: a parking lot node (not a facility); 10-15: two ways making
    # one school campus ring; 20-23: a parking lot way.
    sq = [(-74.25, 39.75), (-74.249, 39.75), (-74.249, 39.751), (-74.25, 39.751)]
    for i, (lon, lat) in enumerate(sq, start=1):
        w.add_node(Node(id=i, location=(lon, lat)))
    w.add_node(Node(id=5, location=(-74.24, 39.74), tags={"amenity": "fire_station", "name": "Station 11"}))
    w.add_node(Node(id=6, location=(-75.50, 40.50), tags={"amenity": "school", "name": "Far Away"}))
    w.add_node(Node(id=7, location=(-74.23, 39.73), tags={"amenity": "parking"}))
    campus = [(-74.22, 39.72), (-74.218, 39.72), (-74.218, 39.722), (-74.22, 39.722)]
    for i, (lon, lat) in enumerate(campus, start=10):
        w.add_node(Node(id=i, location=(lon, lat)))
    for i, (lon, lat) in enumerate(sq, start=20):
        w.add_node(Node(id=i, location=(lon + 0.01, lat)))
    w.add_way(Way(id=100, nodes=[1, 2, 3, 4, 1], tags={"amenity": "hospital", "name": "Southern Ocean"}))
    w.add_way(Way(id=101, nodes=[10, 11, 12]))
    w.add_way(Way(id=102, nodes=[12, 13, 10]))
    w.add_way(Way(id=103, nodes=[20, 21, 22, 23, 20], tags={"amenity": "parking"}))
    w.add_relation(Relation(id=200, members=[("w", 101, "outer"), ("w", 102, "outer")],
                            tags={"type": "multipolygon", "amenity": "school", "name": "Elm School"}))
    w.close()


def test_the_extract_gives_the_same_facilities_overpass_would(tmp_path):
    path = tmp_path / "x.osm.pbf"
    _write_extract(path)
    elements, stamp = X.read_extract(str(path), BBOX)
    assert stamp == "2026-10-18T20:25:06Z"
    facilities = {(f["osm_type"], f["osm_id"]): f for f in cf.parse_elements(elements)}
    assert set(facilities) == {("way", 100), ("node", 5), ("relation", 200)}
    assert facilities[("way", 100)]["kind"] == "hospital"
    assert facilities[("way", 100)]["geometry"]["type"] == "Polygon"
    assert facilities[("node", 5)]["name"] == "Station 11"
    campus = facilities[("relation", 200)]
    assert campus["kind"] == "school" and campus["geometry"]["type"] == "MultiPolygon"
    assert len(campus["geometry"]["coordinates"][0][0]) == 5        # the two ways joined into one ring


# ------------------------------------------------------------------ downloads

PBF_URL = "https://download.geofabrik.de/us/new-jersey-latest.osm.pbf"


def _client(routes):
    def handler(request):
        url = str(request.url)
        if url not in routes:
            return httpx.Response(404)
        return routes[url]() if callable(routes[url]) else routes[url]
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_download_is_checked_against_its_md5_and_follows_redirects_on_geofabrik(tmp_path):
    body = b"pbf bytes" * 1000
    good = hashlib.md5(body).hexdigest()
    dated = "https://download.geofabrik.de/us/new-jersey-261018.osm.pbf"
    async with _client({
        PBF_URL + ".md5": httpx.Response(200, text=f"{good}  new-jersey-latest.osm.pbf\n"),
        PBF_URL: httpx.Response(307, headers={"location": dated}),
        dated: httpx.Response(200, content=body),
    }) as client:
        assert await X.download_extract(client, PBF_URL, str(tmp_path / "a")) == good
    assert (tmp_path / "a").read_bytes() == body

    async with _client({
        PBF_URL + ".md5": httpx.Response(200, text="0" * 32 + "  x\n"),
        PBF_URL: httpx.Response(200, content=body),
    }) as client:
        with pytest.raises(X.ExtractError, match="checksum"):
            await X.download_extract(client, PBF_URL, str(tmp_path / "b"))


async def test_a_redirect_off_geofabrik_or_an_oversized_file_is_refused(tmp_path):
    body = b"x" * 5000
    md5 = httpx.Response(200, text=hashlib.md5(body).hexdigest() + "  x\n")
    async with _client({
        PBF_URL + ".md5": md5,
        PBF_URL: httpx.Response(302, headers={"location": "https://attacker.example/x.pbf"}),
    }) as client:
        with pytest.raises(X.ExtractError, match="refusing"):
            await X.download_extract(client, PBF_URL, str(tmp_path / "a"))
    async with _client({
        PBF_URL + ".md5": httpx.Response(200, text=hashlib.md5(body).hexdigest() + "  x\n"),
        PBF_URL: httpx.Response(200, content=body),
    }) as client:
        with pytest.raises(X.ExtractError, match="limit"):
            await X.download_extract(client, PBF_URL, str(tmp_path / "b"), max_bytes=1000)
    with pytest.raises(X.ExtractError, match="refusing"):
        X._check_url("http://download.geofabrik.de/x")


async def test_the_whole_fetch_from_index_to_facilities(tmp_path, monkeypatch):
    path = tmp_path / "x.osm.pbf"
    _write_extract(path)
    body = path.read_bytes()
    X._index_cache.clear()
    monkeypatch.setattr(X, "configured_regions", lambda: None)
    async with _client({
        X.INDEX_URL: httpx.Response(200, json=INDEX),
        PBF_URL + ".md5": httpx.Response(200, text=hashlib.md5(body).hexdigest() + "  x\n"),
        PBF_URL: httpx.Response(200, content=body),
    }) as client:
        facilities, source = await X.fetch_facilities(BBOX, client=client)
    X._index_cache.clear()
    assert len(facilities) == 3
    assert source == "Geofabrik OpenStreetMap extract: us/new-jersey (data as of 2026-10-18)"


# ------------------------------------------------------------------ fallback

async def test_overpass_is_the_fallback_and_both_failures_are_reported(monkeypatch):
    async def extract_down(bbox):
        raise X.ExtractError("HTTP 503")

    async def overpass_ok(bbox):
        return [{"osm_type": "node", "osm_id": 1}], "https://overpass.example/api/interpreter"

    async def overpass_down(bbox):
        raise cf.FetchError("overpass: HTTP 502")

    monkeypatch.setattr(X, "fetch_facilities", extract_down)
    monkeypatch.setattr(cf, "fetch_facilities", overpass_ok)
    assert (await cf.fetch_best(BBOX))[1].startswith("https://overpass.example")

    monkeypatch.setattr(cf, "fetch_facilities", overpass_down)
    with pytest.raises(cf.FetchError) as err:
        await cf.fetch_best(BBOX)
    assert "Geofabrik" in str(err.value) and "HTTP 502" in str(err.value)


async def test_off_goes_straight_to_overpass(monkeypatch):
    monkeypatch.setattr(X, "configured_regions", lambda: [])
    with pytest.raises(X.ExtractError, match="off"):
        await X.fetch_facilities(BBOX)


def test_refresh_uses_the_extract_first_by_default():
    import inspect
    assert "fetch or fetch_best" in inspect.getsource(cf.refresh)
