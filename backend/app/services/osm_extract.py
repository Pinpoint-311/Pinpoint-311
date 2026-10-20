"""Critical facilities from a Geofabrik regional extract instead of a live query.

The public Overpass servers are volunteer-run query engines, and a town-sized
query is heavy for them: they answer 502/504 when busy, which is how a new
install's first refresh failed and the town's admins were emailed. Geofabrik
publishes a daily file of all OpenStreetMap data for each region (a US state is
100-300 MB) as a plain download with an md5 beside it. Downloading that weekly
and picking the facilities out locally gives the same data from a source that
does not fall over under load. Overpass stays as the fallback.

What happens on each refresh:
  * the region index (a few MB) says which extracts cover the town. The
    smallest region containing the town is used, plus the neighbouring region
    when the fetch area crosses a state line;
  * each extract is streamed to a temporary file under a size cap, checked
    against its md5, read, and deleted;
  * the file is read in a few filtered passes so memory stays small: tagged
    relations, then their ways and tagged ways, then only the nodes those need.
    The result is the same element shape an Overpass `out geom` answer has, so
    `critical_facilities.parse_elements` turns both into facilities.

GEOFABRIK_REGIONS overrides the choice (comma-separated index ids, e.g.
"us/new-jersey") or turns the source off ("off").
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import tempfile
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

INDEX_URL = "https://download.geofabrik.de/index-v1.json"
ALLOWED_HOST = "download.geofabrik.de"
MAX_INDEX_BYTES = 30 * 1024 * 1024
# California and Texas are split into smaller regions; no US state the
# smallest-region rule picks is near this. A larger file falls back to Overpass.
MAX_EXTRACT_BYTES = 1024 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 600
INDEX_TTL_S = 24 * 3600
# The keys every facility tag in critical_facilities.classify() uses.
FACILITY_KEYS = ("amenity", "healthcare", "emergency")

Bbox = Tuple[float, float, float, float]

_index_cache: Dict[str, Any] = {}


class ExtractError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Which regions
# --------------------------------------------------------------------------- #

def configured_regions() -> Optional[List[str]]:
    """GEOFABRIK_REGIONS: None for automatic, [] for off, else the ids given."""
    try:
        from app.core.config import get_settings

        raw = str(getattr(get_settings(), "geofabrik_regions", "") or "").strip()
    except Exception:
        raw = ""
    if not raw:
        return None
    if raw.lower() in ("off", "none", "false", "0"):
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


def _in_ring(x: float, y: float, ring: Sequence[Sequence[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-300) + xi:
            inside = not inside
        j = i
    return inside


def _polygons(geometry: Dict[str, Any]) -> List[List[List[List[float]]]]:
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "Polygon":
        return [geometry.get("coordinates") or []]
    if geometry.get("type") == "MultiPolygon":
        return list(geometry.get("coordinates") or [])
    return []


def region_contains(geometry: Dict[str, Any], lon: float, lat: float) -> bool:
    """Point in a region's outline. Holes are ignored: regions have none that matter."""
    return any(poly and _in_ring(lon, lat, poly[0]) for poly in _polygons(geometry))


def _extent_area(geometry: Dict[str, Any]) -> float:
    xs = [p[0] for poly in _polygons(geometry) for p in (poly[0] if poly else [])]
    ys = [p[1] for poly in _polygons(geometry) for p in (poly[0] if poly else [])]
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) if xs else float("inf")


def _pbf_url(props: Dict[str, Any]) -> Optional[str]:
    url = (props.get("urls") or {}).get("pbf")
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        return None
    return url


def pick_regions(index: Dict[str, Any], bbox: Bbox) -> List[Tuple[str, str]]:
    """(region id, pbf url) covering bbox: for the centre and each corner, the
    smallest region containing it. Usually one state; two at a state line."""
    regions = []
    for feature in index.get("features") or []:
        props = feature.get("properties") or {}
        url = _pbf_url(props)
        if url and props.get("id"):
            regions.append((_extent_area(feature.get("geometry")), props["id"], url, feature.get("geometry")))
    regions.sort(key=lambda r: r[0])

    minx, miny, maxx, maxy = bbox
    points = [((minx + maxx) / 2, (miny + maxy) / 2),
              (minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    chosen: List[Tuple[str, str]] = []
    for lon, lat in points:
        for _area, rid, url, geometry in regions:
            if region_contains(geometry, lon, lat):
                if (rid, url) not in chosen:
                    chosen.append((rid, url))
                break
    return chosen


def regions_by_id(index: Dict[str, Any], ids: Sequence[str]) -> List[Tuple[str, str]]:
    found = {}
    for feature in index.get("features") or []:
        props = feature.get("properties") or {}
        url = _pbf_url(props)
        if url and props.get("id") in ids:
            found[props["id"]] = url
    missing = [i for i in ids if i not in found]
    if missing:
        raise ExtractError(f"GEOFABRIK_REGIONS names unknown regions: {', '.join(missing)}")
    return [(i, found[i]) for i in ids]


# --------------------------------------------------------------------------- #
# Downloads
# --------------------------------------------------------------------------- #

def _check_url(url: str) -> None:
    parsed = urlparse(str(url))
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
        raise ExtractError(f"refusing to download from {parsed.scheme}://{parsed.hostname}")


async def _get(client, url: str):
    """GET following redirects, but only ever to Geofabrik over https."""
    for _ in range(5):
        _check_url(url)
        resp = await client.get(url, follow_redirects=False)
        if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
            url = str(resp.url.join(resp.headers["location"]))
            continue
        return resp
    raise ExtractError("too many redirects")


async def load_index(client) -> Dict[str, Any]:
    cached = _index_cache.get("index")
    if cached and time.monotonic() - _index_cache.get("at", 0) < INDEX_TTL_S:
        return cached
    resp = await _get(client, INDEX_URL)
    if resp.status_code != 200:
        raise ExtractError(f"region index: HTTP {resp.status_code}")
    if len(resp.content) > MAX_INDEX_BYTES:
        raise ExtractError("region index too large")
    index = resp.json()
    _index_cache.update(index=index, at=time.monotonic())
    return index


async def download_extract(client, url: str, dest: str, *, max_bytes: int = MAX_EXTRACT_BYTES) -> str:
    """Stream url to dest, verify it against Geofabrik's .md5. Returns the md5."""
    md5_resp = await _get(client, url + ".md5")
    if md5_resp.status_code != 200:
        raise ExtractError(f"{url}.md5: HTTP {md5_resp.status_code}")
    match = re.match(r"\s*([0-9a-fA-F]{32})\b", md5_resp.text)
    if not match:
        raise ExtractError(f"{url}.md5: no checksum in the answer")
    expected = match.group(1).lower()

    target = url
    for _ in range(5):
        _check_url(target)
        async with client.stream("GET", target, follow_redirects=False) as resp:
            if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                target = str(resp.url.join(resp.headers["location"]))
                continue
            if resp.status_code != 200:
                raise ExtractError(f"{url}: HTTP {resp.status_code}")
            declared = int(resp.headers.get("content-length") or 0)
            if declared > max_bytes:
                raise ExtractError(f"{url}: {declared // (1024 * 1024)} MB is over the "
                                   f"{max_bytes // (1024 * 1024)} MB limit")
            digest = hashlib.md5(usedforsecurity=False)
            size = 0
            with open(dest, "wb") as fh:
                async for chunk in resp.aiter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ExtractError(f"{url}: over the {max_bytes // (1024 * 1024)} MB limit")
                    digest.update(chunk)
                    fh.write(chunk)
            break
    else:
        raise ExtractError("too many redirects")
    if digest.hexdigest() != expected:
        raise ExtractError(f"{url}: checksum mismatch; the download is incomplete or altered")
    return expected


# --------------------------------------------------------------------------- #
# Reading an extract
# --------------------------------------------------------------------------- #

def _in_bbox(lon: float, lat: float, bbox: Bbox) -> bool:
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def _tags(obj) -> Dict[str, str]:
    return {t.k: t.v for t in obj.tags}


def read_extract(path: str, bbox: Bbox) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Overpass-shaped elements for every facility in bbox, and the data's timestamp.

    Blocking (call it in a thread). Up to five passes, each decoding one
    object type. The tag passes filter in C++. The passes for the untagged
    ways and nodes an outline needs check ids in Python instead: osmium's
    IdFilter allocates its bitmap in blocks across the whole id range, and a
    state's facility outlines touch thousands of blocks (1.7 GB for New
    Jersey, against about 150 MB this way and about a minute).
    """
    import osmium
    from osmium.filter import KeyFilter

    from app.services.critical_facilities import classify

    def objects(entity, flt):
        return osmium.FileProcessor(path, entity).with_filter(flt)

    timestamp = None
    try:
        header = osmium.io.Reader(path, osmium.osm.osm_entity_bits.NOTHING).header()
        timestamp = header.get("osmosis_replication_timestamp") or None
    except Exception:
        pass

    relations: Dict[int, Tuple[Dict[str, str], List[Tuple[str, int, str]]]] = {}
    for rel in objects(osmium.osm.RELATION, KeyFilter(*FACILITY_KEYS)):
        tags = _tags(rel)
        if classify(tags):
            relations[rel.id] = (tags, [(m.type, m.ref, m.role) for m in rel.members if m.role != "inner"])
    member_ways = {ref for _, members in relations.values() for t, ref, _ in members if t == "w"}
    member_nodes = {ref for _, members in relations.values() for t, ref, _ in members if t == "n"}

    ways: Dict[int, Tuple[Optional[Dict[str, str]], List[int]]] = {}
    for way in objects(osmium.osm.WAY, KeyFilter(*FACILITY_KEYS)):
        tags = _tags(way)
        if classify(tags):
            ways[way.id] = (tags, [n.ref for n in way.nodes])
    missing = member_ways - ways.keys()
    if missing:
        for way in osmium.FileProcessor(path, osmium.osm.WAY):
            if way.id in missing:
                ways[way.id] = (None, [n.ref for n in way.nodes])

    elements: List[Dict[str, Any]] = []
    locations: Dict[int, Tuple[float, float]] = {}
    for node in objects(osmium.osm.NODE, KeyFilter(*FACILITY_KEYS)):
        if not node.location.valid():
            continue
        lon, lat = node.location.lon, node.location.lat
        locations[node.id] = (lon, lat)
        tags = _tags(node)
        if classify(tags) and _in_bbox(lon, lat, bbox):
            elements.append({"type": "node", "id": node.id, "lat": lat, "lon": lon, "tags": tags})
    needed = {ref for _, refs in ways.values() for ref in refs} | member_nodes
    needed -= locations.keys()
    if needed:
        for node in osmium.FileProcessor(path, osmium.osm.NODE):
            if node.id in needed and node.location.valid():
                locations[node.id] = (node.location.lon, node.location.lat)

    def geometry(refs: Sequence[int]) -> List[Dict[str, float]]:
        return [{"lat": locations[r][1], "lon": locations[r][0]} for r in refs if r in locations]

    def touches(points: Sequence[Dict[str, float]]) -> bool:
        return any(_in_bbox(p["lon"], p["lat"], bbox) for p in points)

    for wid, (tags, refs) in ways.items():
        if tags is None:
            continue
        geom = geometry(refs)
        if touches(geom):
            elements.append({"type": "way", "id": wid, "tags": tags, "geometry": geom})

    for rid, (tags, members) in relations.items():
        out_members, points = [], []
        for mtype, ref, role in members:
            if mtype == "w" and ref in ways:
                geom = geometry(ways[ref][1])
                out_members.append({"type": "way", "ref": ref, "role": role, "geometry": geom})
                points.extend(geom)
            elif mtype == "n" and ref in locations:
                lon, lat = locations[ref]
                out_members.append({"type": "node", "ref": ref, "role": role, "lat": lat, "lon": lon})
                points.append({"lat": lat, "lon": lon})
        if touches(points):
            elements.append({"type": "relation", "id": rid, "tags": tags, "members": out_members})
    return elements, timestamp


# --------------------------------------------------------------------------- #
# The fetch
# --------------------------------------------------------------------------- #

async def fetch_facilities(bbox: Bbox, *, client=None) -> Tuple[List[Dict[str, Any]], str]:
    """(facilities, source) from the Geofabrik extracts covering bbox.

    Raises ExtractError (or whatever the reader raised) on any failure, so the
    caller can fall back to Overpass.
    """
    import httpx

    from app.services.critical_facilities import parse_elements, user_agent

    wanted = configured_regions()
    if wanted == []:
        raise ExtractError("turned off (GEOFABRIK_REGIONS=off)")

    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60, read=DOWNLOAD_TIMEOUT_S),
                                         headers={"User-Agent": user_agent()})
    elements: List[Dict[str, Any]] = []
    stamps: List[str] = []
    try:
        index = await load_index(client)
        regions = regions_by_id(index, wanted) if wanted else pick_regions(index, bbox)
        if not regions:
            raise ExtractError("no Geofabrik region covers the town")
        with tempfile.TemporaryDirectory(prefix="osm-extract-") as tmp:
            for rid, url in regions:
                path = os.path.join(tmp, re.sub(r"[^a-z0-9-]", "_", rid.lower()) + ".osm.pbf")
                await download_extract(client, url, path)
                found, stamp = await asyncio.to_thread(read_extract, path, bbox)
                os.unlink(path)
                elements.extend(found)
                if stamp:
                    stamps.append(stamp[:10])
    finally:
        if own:
            await client.aclose()

    source = "Geofabrik OpenStreetMap extract: " + ", ".join(r for r, _ in regions)
    if stamps:
        source += f" (data as of {min(stamps)})"
    return parse_elements(elements), source
