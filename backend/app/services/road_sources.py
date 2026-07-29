"""Fetch road centrelines for a town, from whichever source is best for its state.

A clerk sets the town boundary and roads appear. They never upload a file, paste
a URL, or email their county GIS office -- the lookup work is done once here, by
the project, for everyone in that state.

The ladder, best first:

  1. Statewide NG9-1-1 centrelines (NENA-STA-006). Maintained continuously
     because emergency dispatch depends on it; usually republished monthly.
  2. A state DOT or GIS-clearinghouse centreline layer.
  3. Census TIGER/Line, nationally. Coarser and annual, but it exists for every
     county in the country, it is public domain, and TIGERweb is already a
     trusted dependency here (app/api/gis.py uses it for boundaries).

Every one of those speaks the same ArcGIS REST dialect, which is the quiet
reason this works at all: heterogeneous publishers, one protocol. A single
fetcher handles a state 911 authority, a county GIS shop and the Census Bureau.

OpenStreetMap via Overpass is available as an explicit opt-in. It is not in the
default ladder: it is contributor-maintained with no coverage guarantee, and its
ODbL share-alike terms reach into the research exports in a way public-domain
TIGER does not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from app.services.road_matching import normalize_road_name
from app.services.road_sources_registry import STATE_ROAD_SOURCES

logger = logging.getLogger(__name__)

FETCH_TIMEOUT = 120.0
PAGE_SIZE = 1000

# Ways that are not roads anyone reports a pothole *on* in a jurisdictional
# sense. Excluded at ingest so a pin cannot snap to a footpath or a parking
# aisle. Kept as a filter rather than a hard delete of the class column, so a
# town that does maintain its alleys can opt them back in later.
EXCLUDED_HIGHWAY_CLASSES = {
    "footway", "path", "steps", "cycleway", "bridleway", "pedestrian",
    "construction", "proposed", "raceway", "driveway", "parking_aisle",
}

# Field names that plausibly carry a street name, most specific first. Used only
# when the registry entry has no verified field_map -- the registry deliberately
# leaves that None rather than guessing column names it never saw.
CANDIDATE_NAME_FIELDS = [
    "CompleteStreetName", "FULLNAME", "FullName", "St_Name", "STREETNAME",
    "StreetName", "ROADNAME", "RoadName", "RD_NAME", "LABEL", "NAME",
]
CANDIDATE_REF_FIELDS = ["RTE_NAME", "ROUTE_NUMBER", "RouteNumber", "REF", "SIGN1"]


@dataclass
class FetchedSegment:
    """One road, normalised out of whatever the publisher happened to call things."""

    source_feature_id: str
    name: Optional[str]
    ref: Optional[str]
    highway_class: Optional[str]
    coordinates: List[List[float]]   # [[lng, lat], ...]

    @property
    def name_norm(self) -> str:
        return normalize_road_name(self.name or "")

    @property
    def ref_norm(self) -> str:
        return normalize_road_name(self.ref or "")


@dataclass
class FetchResult:
    source_id: str
    source_name: str
    endpoint: str
    segments: List[FetchedSegment] = field(default_factory=list)
    source_updated_at: Optional[str] = None
    truncated: bool = False


def _first_present(attributes: Dict[str, Any], candidates: Sequence[str]) -> Optional[str]:
    """Case-insensitive lookup of the first candidate field that has a value."""
    lowered = {k.lower(): v for k, v in attributes.items()}
    for candidate in candidates:
        value = lowered.get(candidate.lower())
        if value not in (None, "", " "):
            return str(value).strip()
    return None


def _nena_street_name(attributes: Dict[str, Any]) -> Optional[str]:
    """Rebuild a street name from NENA's eight-part decomposition.

    NENA-STA-006 splits a name across pre-modifier, pre-directional, pre-type,
    separator, the name itself, post-type, post-directional and post-modifier.
    Joining them is the only way to get "North Main Street" back out; reading
    St_Name alone yields "Main", which matches nothing a clerk would type.
    """
    lowered = {k.lower(): (str(v).strip() if v not in (None, "") else "") for k, v in attributes.items()}
    parts = [
        lowered.get("st_premod", ""),
        lowered.get("st_predir", ""),
        lowered.get("st_pretyp", ""),
        lowered.get("st_presep", ""),
        lowered.get("st_name", ""),
        lowered.get("st_postyp", ""),
        lowered.get("st_posdir", ""),
        lowered.get("st_posmod", ""),
    ]
    joined = " ".join(p for p in parts if p)
    return joined or None


def parse_arcgis_features(
    payload: Dict[str, Any],
    *,
    schema: str,
    field_map: Optional[Dict[str, str]] = None,
    id_field: Optional[str] = None,
) -> List[FetchedSegment]:
    """Turn an ArcGIS GeoJSON response into segments. Pure -- no I/O.

    Separated from the HTTP call so it can be tested against fixtures, which
    matters because the sandbox this was written in cannot reach any of these
    services.
    """
    segments: List[FetchedSegment] = []
    for index, feature in enumerate(payload.get("features") or []):
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type")
        attributes = feature.get("properties") or feature.get("attributes") or {}

        # MultiLineString parts are kept as separate segments: a road broken
        # into pieces is exactly what the data model expects, and flattening
        # them into one line would invent connections that do not exist.
        if geometry_type == "LineString":
            line_sets: Iterable[List[List[float]]] = [geometry.get("coordinates") or []]
        elif geometry_type == "MultiLineString":
            line_sets = geometry.get("coordinates") or []
        else:
            continue

        if schema == "nena":
            name = _nena_street_name(attributes) or _first_present(attributes, CANDIDATE_NAME_FIELDS)
        elif field_map and field_map.get("name"):
            name = _first_present(attributes, [field_map["name"]]) or _first_present(
                attributes, CANDIDATE_NAME_FIELDS
            )
        else:
            name = _first_present(attributes, CANDIDATE_NAME_FIELDS)

        ref_fields = [field_map["ref"]] if field_map and field_map.get("ref") else []
        ref = _first_present(attributes, ref_fields + CANDIDATE_REF_FIELDS)

        highway_class = _first_present(attributes, ["highway", "MTFCC", "RoadClass", "FUNC_CLASS"])

        base_id = None
        if id_field:
            base_id = _first_present(attributes, [id_field])
        if not base_id:
            base_id = _first_present(
                attributes, ["RCL_NGUID", "LINEARID", "OBJECTID", "FID", "GlobalID", "id"]
            )

        for part, coordinates in enumerate(line_sets):
            if len(coordinates or []) < 2:
                continue  # a one-point "line" has no geometry to measure against
            feature_id = f"{base_id or index}" + (f":{part}" if part else "")
            segments.append(
                FetchedSegment(
                    source_feature_id=feature_id,
                    name=name,
                    ref=ref,
                    highway_class=highway_class,
                    coordinates=[[float(c[0]), float(c[1])] for c in coordinates],
                )
            )
    return segments


def should_keep(segment: FetchedSegment) -> bool:
    """Drop footpaths, driveways and parking aisles; keep everything else.

    An unnamed road is kept. It can never match a clerk's list, so it can never
    cause a block -- but it can win "nearest road", which is exactly what stops
    a pin on an unnamed service road from being attributed to the county road
    twenty metres away.
    """
    return (segment.highway_class or "").lower() not in EXCLUDED_HIGHWAY_CLASSES


def resolve_source(state_code: Optional[str]) -> Dict[str, Any]:
    """Pick the road source for a state, falling back to TIGER.

    Anything unknown, unlisted or malformed resolves to the national default.
    A town is never left without roads because its state has no entry.
    """
    if state_code:
        entry = STATE_ROAD_SOURCES.get(state_code.upper())
        if entry and entry.get("url"):
            return entry
    return STATE_ROAD_SOURCES["DEFAULT"]


def _query_url(entry: Dict[str, Any]) -> Optional[str]:
    url = entry.get("url")
    if not url:
        return None
    return f"{url.rstrip('/')}/query"


async def fetch_segments(
    entry: Dict[str, Any],
    bbox: Tuple[float, float, float, float],
    *,
    client: Optional[httpx.AsyncClient] = None,
    max_records: int = 200_000,
) -> FetchResult:
    """Page an ArcGIS layer for every road inside `bbox` (minx, miny, maxx, maxy).

    Raises on failure rather than returning an empty result. The caller stages
    and swaps, so an exception leaves the town's existing roads untouched --
    whereas a silent empty return would swap in nothing and disable road routing
    for the whole town.
    """
    url = _query_url(entry)
    if not url:
        raise ValueError(f"road source {entry.get('name')!r} has no queryable layer URL")

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True)

    result = FetchResult(
        source_id=entry.get("schema") or "custom",
        source_name=entry.get("name") or "Unknown source",
        endpoint=entry["url"],
    )

    try:
        offset = 0
        while True:
            params = {
                "where": "1=1",
                "geometry": ",".join(str(v) for v in bbox),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "outSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "*",
                "returnGeometry": "true",
                "resultOffset": str(offset),
                "resultRecordCount": str(PAGE_SIZE),
                "f": "geojson",
            }
            response = await client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict) and "error" in payload:
                raise RuntimeError(payload["error"].get("message", "ArcGIS error"))

            page = parse_arcgis_features(
                payload,
                schema=entry.get("schema") or "custom",
                field_map=entry.get("field_map"),
                id_field=(entry.get("field_map") or {}).get("id"),
            )
            result.segments.extend(s for s in page if should_keep(s))

            exceeded = bool(payload.get("exceededTransferLimit") or payload.get("properties", {}).get("exceededTransferLimit"))
            if not page or not exceeded:
                break
            offset += PAGE_SIZE
            if len(result.segments) >= max_records:
                # A bbox that swallowed half a state. Stop and say so rather
                # than paging until the worker is killed.
                result.truncated = True
                logger.warning(
                    "road fetch hit max_records=%s for %s; result truncated",
                    max_records, result.source_name,
                )
                break
    finally:
        if owns_client:
            await client.aclose()

    return result


async def fetch_source_updated_at(
    entry: Dict[str, Any], *, client: Optional[httpx.AsyncClient] = None
) -> Optional[int]:
    """When the publisher last edited the layer, in epoch milliseconds.

    One cheap metadata call. If it has not changed since our last import there
    is nothing to download, which turns most monthly refreshes into a single
    request -- and, more usefully, distinguishes "we re-fetched" from "the
    source actually published something new".
    """
    url = entry.get("url")
    if not url:
        return None
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=30.0, follow_redirects=True)
    try:
        response = await client.get(url, params={"f": "json"})
        response.raise_for_status()
        payload = response.json()
        editing = (payload or {}).get("editingInfo") or {}
        value = editing.get("lastEditDate")
        return int(value) if value else None
    except Exception as exc:
        logger.debug("could not read lastEditDate for %s: %s", entry.get("name"), exc)
        return None
    finally:
        if owns_client:
            await client.aclose()
