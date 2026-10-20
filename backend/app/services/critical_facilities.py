"""Hospitals, schools, fire stations and the like, kept locally for the whole town.

Every report's enrichment asks "is this near something critical?", and staff
see the answer as a "Near ..." chip and the AI weighs it into priority. That
question used to go to the public Overpass API once per report, with a 12 s
budget, and it failed in three ways at once:

  * it timed out. A town-sized Overpass query routinely takes 30 s or more, so
    the lookup came back empty -- logged as "Overpass critical infrastructure
    search failed:" with no message -- and a pin dropped beside two clinics
    reported nothing near it;
  * every resident's report location went to a third party, which a government
    customer is entitled to refuse;
  * it measured to the centre of a way, so a hospital campus whose edge was
    within range but whose middle was not was missed, and relations (campuses
    are often multipolygons) were never asked for at all.

So the facilities are fetched once a week, for the whole town in one query,
into `critical_facilities`, and the per-report check is a local PostGIS
distance to the facility's real outline. No report location leaves the server.

Admin map layers still count -- a town's own "Fire Stations" layer is better
than OpenStreetMap -- but they are matched by whole words, asset layers (fire
*hydrants*, storm *drains*) are excluded, every feature is checked, and their
results are merged with the facilities rather than replacing them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# What counts, and how near is near
# --------------------------------------------------------------------------- #

# Kind -> the label staff and the AI prompt see ("Hospital: Name (123m)").
# The labels are the ones the Overpass fallback used, so stored analyses and
# new ones read the same.
KIND_LABELS: Dict[str, str] = {
    "hospital": "Hospital",
    "clinic": "Medical Clinic",
    "school": "School",
    "fire_station": "Fire Station",
    "police": "Police Station",
    "ambulance_station": "Ambulance Station",
    "nursing_home": "Nursing Home/Assisted Living",
    # Admin layers only: a town layer called "Emergency Facilities" says what
    # it is without saying which of the above.
    "emergency": "Emergency Facility",
}

# Metres, measured to the facility's outline (zero inside it). 500 m is the
# radius the old lookup promised the AI prompt ("None identified within
# 500m"); schools are tighter because "near a school" is about children
# walking past this spot, not about the district.
DEFAULT_RADIUS_M = 500
SCHOOL_RADIUS_M = 300
RADIUS_M: Dict[str, int] = {"school": SCHOOL_RADIUS_M}


def radius_for(kind: str) -> int:
    return RADIUS_M.get(kind, DEFAULT_RADIUS_M)


MAX_RADIUS_M = max([DEFAULT_RADIUS_M, *RADIUS_M.values()])

# The fetch covers the boundary plus this margin: the hospital across the town
# line is still the nearest hospital.
BOUNDARY_BUFFER_M = 1000
# Half-width of the box used when a town has a centre but no outline.
CENTRE_FALLBACK_HALF_WIDTH_M = 8000

REFRESH_EVERY = timedelta(days=7)
# The health check warns past this, while a boundary is configured.
STALE_AFTER = timedelta(days=30)
# A second trigger (worker boot plus the daily beat) inside this window is a
# duplicate, not a retry.
ATTEMPT_COOLDOWN = timedelta(minutes=30)
# An empty store is retried hourly (see the beat schedule); the health check
# only calls it a problem once it has kept failing this long, so a public
# Overpass instance having a bad hour does not email every admin.
EMPTY_GRACE = timedelta(hours=24)


# --------------------------------------------------------------------------- #
# Admin layer names
# --------------------------------------------------------------------------- #

# Whole words only. The old substring match counted "Fire Hydrants" as a fire
# station (and "ems" matched "systems"), and since the OSM lookup only ran when
# the layers found nothing, a hydrant within 50 m switched the real check off.
_LAYER_KINDS: Sequence[Tuple[str, str]] = (
    ("hospital", r"\bhospitals?\b"),
    ("clinic", r"\b(clinics?|urgent\s+care|medical\s+cent(er|re)s?)\b"),
    ("fire_station", r"\b(fire\s*(stations?|houses?|companies|company|departments?|co\.?)|firehouses?)\b"),
    ("police", r"\bpolice\b"),
    ("ambulance_station", r"\b(ambulances?|ems|rescue\s+squads?|first\s+aid)\b"),
    ("nursing_home", r"\b(nursing\s+homes?|assisted\s+living|senior\s+(living|housing|centers?)|elderly)\b"),
    ("school", r"\bschools?\b"),
    ("emergency", r"\bemergency\b"),
)
# A layer of things on the street, not places people are. Checked first, so
# "Fire Hydrants", "School Zone Signs" and "Hospital Streetlights" are assets.
_ASSET_WORDS = re.compile(
    r"hydrant|drain|culvert|manhole|valve|catch\s*basin|sewer|\bpipes?\b|"
    r"\bsigns?\b|signage|signal|lights?\b|lighting|\bpoles?\b|\bmeters?\b",
    re.IGNORECASE,
)
_SCHOOL_ZONE = re.compile(r"\bschool\s*zones?\b", re.IGNORECASE)


def layer_kind(name: Optional[str]) -> Optional[str]:
    """The facility kind an admin layer's name says it holds, or None."""
    text = (name or "").strip()
    if not text or _ASSET_WORDS.search(text) or _SCHOOL_ZONE.search(text):
        return None
    for kind, pattern in _LAYER_KINDS:
        if re.search(pattern, text, re.IGNORECASE):
            return kind
    return None


def is_school_zone_layer(name: Optional[str]) -> bool:
    return bool(_SCHOOL_ZONE.search(name or "")) and not _ASSET_WORDS.search(name or "")


# --------------------------------------------------------------------------- #
# OpenStreetMap: tags -> kind, elements -> geometry
# --------------------------------------------------------------------------- #

_AMENITY_KINDS = {
    "hospital": "hospital",
    "clinic": "clinic",
    "school": "school",
    "fire_station": "fire_station",
    "police": "police",
    "nursing_home": "nursing_home",
}
_HEALTHCARE_KINDS = {
    "hospital": "hospital",
    "clinic": "clinic",
    "urgent_care": "clinic",
    "nursing_home": "nursing_home",
}
# Most specific first: an urgent care tagged both amenity=clinic and
# healthcare=hospital is a hospital as far as an ambulance is concerned.
_KIND_ORDER = ("hospital", "ambulance_station", "fire_station", "police",
               "school", "nursing_home", "clinic")


def classify(tags: Dict[str, Any]) -> Optional[str]:
    """The kind an OSM element's tags describe, or None. Hydrants are not one."""
    if not isinstance(tags, dict):
        return None
    found = set()
    if tags.get("amenity") in _AMENITY_KINDS:
        found.add(_AMENITY_KINDS[tags["amenity"]])
    if tags.get("healthcare") in _HEALTHCARE_KINDS:
        found.add(_HEALTHCARE_KINDS[tags["healthcare"]])
    if tags.get("emergency") == "ambulance_station":
        found.add("ambulance_station")
    if tags.get("amenity") == "social_facility" and tags.get("social_facility") in ("nursing_home", "assisted_living"):
        found.add("nursing_home")
    for kind in _KIND_ORDER:
        if kind in found:
            return kind
    return None


def build_query(bbox: Tuple[float, float, float, float], timeout_s: int = 90) -> str:
    """One query for every facility in (minx, miny, maxx, maxy).

    `nwr` so relations come too, and `out geom` so ways and relations arrive
    with their outlines: distance is measured to the edge, not the centre.
    """
    minx, miny, maxx, maxy = bbox
    b = f"({miny:.6f},{minx:.6f},{maxy:.6f},{maxx:.6f})"
    return (
        f"[out:json][timeout:{int(timeout_s)}];\n"
        "(\n"
        f'  nwr["amenity"~"^(hospital|clinic|school|fire_station|police|nursing_home)$"]{b};\n'
        f'  nwr["healthcare"~"^(hospital|clinic|urgent_care|nursing_home)$"]{b};\n'
        f'  nwr["emergency"="ambulance_station"]{b};\n'
        f'  nwr["amenity"="social_facility"]["social_facility"~"^(nursing_home|assisted_living)$"]{b};\n'
        ");\n"
        "out geom;\n"
    )


def _coords(points: Any) -> List[List[float]]:
    out: List[List[float]] = []
    for p in points or []:
        if isinstance(p, dict) and isinstance(p.get("lat"), (int, float)) and isinstance(p.get("lon"), (int, float)):
            out.append([float(p["lon"]), float(p["lat"])])
    return out


def _closed(ring: List[List[float]]) -> bool:
    return len(ring) >= 4 and ring[0] == ring[-1]


def assemble_rings(chains: List[List[List[float]]]) -> Tuple[List[List[List[float]]], List[List[List[float]]]]:
    """Join member ways end to end. Returns (closed rings, chains that never closed).

    A multipolygon's outer ring is often split across several ways; each way
    alone is a line, and only joined do they enclose the campus.
    """
    rings: List[List[List[float]]] = []
    open_chains: List[List[List[float]]] = []
    pending = [list(c) for c in chains if len(c) >= 2]
    while pending:
        current = pending.pop(0)
        grew = True
        while not _closed(current) and grew:
            grew = False
            for i, other in enumerate(pending):
                if other[0] == current[-1]:
                    current = current + other[1:]
                elif other[-1] == current[-1]:
                    current = current + other[-2::-1]
                elif other[-1] == current[0]:
                    current = other[:-1] + current
                elif other[0] == current[0]:
                    current = other[:0:-1] + current
                else:
                    continue
                pending.pop(i)
                grew = True
                break
        (rings if _closed(current) else open_chains).append(current)
    return rings, open_chains


def element_geometry(el: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """GeoJSON for one `out geom` element, or None if it carries no shape.

    node     -> Point
    way      -> Polygon when closed (a building or campus), else LineString
    relation -> MultiPolygon from its outer ways joined into rings. Inner
                rings are dropped: a point in a courtyard is at the hospital.
                Members that never close are kept as lines, and a relation of
                nodes (a type=site) becomes their points, so nothing that has
                coordinates is thrown away.
    """
    etype = el.get("type")
    if etype == "node":
        if isinstance(el.get("lat"), (int, float)) and isinstance(el.get("lon"), (int, float)):
            return {"type": "Point", "coordinates": [float(el["lon"]), float(el["lat"])]}
        return None
    if etype == "way":
        line = _coords(el.get("geometry"))
        if _closed(line):
            return {"type": "Polygon", "coordinates": [line]}
        if len(line) >= 2:
            return {"type": "LineString", "coordinates": line}
        if len(line) == 1:
            return {"type": "Point", "coordinates": line[0]}
        return None
    if etype == "relation":
        chains: List[List[List[float]]] = []
        points: List[List[float]] = []
        for member in el.get("members") or []:
            if not isinstance(member, dict) or member.get("role") == "inner":
                continue
            if member.get("type") == "way":
                line = _coords(member.get("geometry"))
                if line:
                    chains.append(line)
            elif member.get("type") == "node":
                if isinstance(member.get("lat"), (int, float)) and isinstance(member.get("lon"), (int, float)):
                    points.append([float(member["lon"]), float(member["lat"])])
        rings, open_chains = assemble_rings(chains)
        if rings:
            # Lines left over beside real rings are almost always a ring the
            # mapper left unclosed by one node; the rings already say where it is.
            return {"type": "MultiPolygon", "coordinates": [[r] for r in rings]}
        if open_chains:
            return {"type": "MultiLineString", "coordinates": open_chains}
        if points:
            return {"type": "MultiPoint", "coordinates": points}
        # `out center` instead of `out geom`, or a relation of relations.
        centre = el.get("center")
        if isinstance(centre, dict) and isinstance(centre.get("lat"), (int, float)):
            return {"type": "Point", "coordinates": [float(centre["lon"]), float(centre["lat"])]}
        return None
    return None


def parse_elements(elements: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Facilities from an Overpass response: osm_type, osm_id, kind, name, geometry."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for el in elements or []:
        if not isinstance(el, dict):
            continue
        kind = classify(el.get("tags") or {})
        if not kind:
            continue
        key = (el.get("type"), el.get("id"))
        if key in seen or not isinstance(el.get("id"), int):
            continue
        geometry = element_geometry(el)
        if not geometry:
            continue
        seen.add(key)
        name = (el.get("tags") or {}).get("name")
        out.append({
            "osm_type": el["type"],
            "osm_id": el["id"],
            "kind": kind,
            "name": str(name).strip()[:300] if name else None,
            "geometry": geometry,
        })
    return out


# --------------------------------------------------------------------------- #
# The fetch
# --------------------------------------------------------------------------- #

# The main public instance, then a long-running public mirror. Both are
# volunteer-run and are busy at times (502/504); one weekly query per town is
# what they ask of clients. A town that wants its own instance sets OVERPASS_URLS.
DEFAULT_OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
SERVER_TIMEOUT_S = 90
CLIENT_TIMEOUT_S = 120
FETCH_ROUNDS = 2  # every mirror, twice
RETRY_PAUSE_S = 10


class FetchError(Exception):
    pass


def overpass_urls() -> List[str]:
    """Mirrors to try, in order: OVERPASS_URLS (comma-separated) or the main instance."""
    try:
        from app.core.config import get_settings

        raw = getattr(get_settings(), "overpass_urls", None) or ""
    except Exception:
        raw = ""
    urls = [u.strip() for u in str(raw).split(",") if u.strip().startswith("https://")]
    return urls or list(DEFAULT_OVERPASS_URLS)


def user_agent() -> str:
    """Product and version only. Never an email or anything about a person."""
    try:
        from app.core.config import get_settings

        version = get_settings().app_version or "dev"
    except Exception:
        version = "dev"
    return f"Pinpoint311/{version} (critical-facilities refresh)"


async def fetch_facilities(bbox: Tuple[float, float, float, float], *, client=None,
                           urls: Optional[Sequence[str]] = None,
                           pause_s: float = RETRY_PAUSE_S) -> Tuple[List[Dict[str, Any]], str]:
    """(facilities, url that answered). Raises FetchError when every try failed.

    A 200 is not enough: Overpass answers a query that ran out of time with a
    200, a `remark` saying so, and however many elements it got to -- applying
    that would quietly drop half the town's schools.
    """
    import httpx

    query = build_query(bbox, SERVER_TIMEOUT_S)
    urls = list(urls or overpass_urls())
    own = client is None
    client = client or httpx.AsyncClient(timeout=CLIENT_TIMEOUT_S)
    errors: List[str] = []
    try:
        for round_no in range(FETCH_ROUNDS):
            for url in urls:
                try:
                    resp = await client.post(url, data={"data": query}, headers={"User-Agent": user_agent()})
                    if resp.status_code != 200:
                        errors.append(f"{url}: HTTP {resp.status_code}")
                        continue
                    body = resp.json()
                    remark = str(body.get("remark") or "")
                    if "error" in remark.lower() or "timed out" in remark.lower():
                        errors.append(f"{url}: {remark[:200]}")
                        continue
                    return parse_elements(body.get("elements") or []), url
                except Exception as exc:
                    errors.append(f"{url}: {type(exc).__name__}: {exc}"[:300])
            if round_no + 1 < FETCH_ROUNDS and pause_s:
                await asyncio.sleep(pause_s)
    finally:
        if own:
            await client.aclose()
    raise FetchError("; ".join(errors[-4:]) or "no Overpass URL configured")


# --------------------------------------------------------------------------- #
# Where to fetch
# --------------------------------------------------------------------------- #

def _expand(bbox: Tuple[float, float, float, float], metres: float) -> Tuple[float, float, float, float]:
    minx, miny, maxx, maxy = bbox
    dlat = metres / 111_320.0
    mid = math.radians((miny + maxy) / 2)
    dlon = metres / (111_320.0 * max(math.cos(mid), 0.01))
    return minx - dlon, miny - dlat, maxx + dlon, maxy + dlat


def fetch_area(boundary: Optional[Dict[str, Any]]) -> Tuple[Optional[Tuple[float, float, float, float]], Optional[Dict[str, Any]]]:
    """(bbox to fetch, boundary geometry to clip to). (None, None) with no boundary.

    The boundary's box plus a kilometre; or, when all a town has given is a
    centre, a box around that. Overpass is asked for the box and the result is
    clipped to the buffered outline locally -- a polygon filter in the query
    would make the one slow request slower.
    """
    from app.services.boundary_geo import boundary_bbox, boundary_centre, extract_boundary_geometry

    geometry = extract_boundary_geometry(boundary)
    bbox = boundary_bbox(geometry) if geometry else None
    if bbox:
        return _expand(bbox, BOUNDARY_BUFFER_M), geometry
    centre = boundary_centre(boundary) if boundary else None
    if centre:
        lon, lat = centre
        return _expand((lon, lat, lon, lat), CENTRE_FALLBACK_HALF_WIDTH_M), None
    return None, None


async def _load_boundary(db) -> Optional[Dict[str, Any]]:
    from sqlalchemy import select
    from app.models import SystemSettings

    row = (await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))).scalar_one_or_none()
    boundary = getattr(row, "township_boundary", None) if row else None
    return boundary if isinstance(boundary, dict) and boundary else None


# --------------------------------------------------------------------------- #
# The store
# --------------------------------------------------------------------------- #

# Polygons are repaired (and kept polygonal, so the geography cast below never
# meets a GeometryCollection); points and lines are stored as they came.
_INSERT_SQL = (
    "INSERT INTO critical_facilities (osm_type, osm_id, kind, name, geom, fetched_at) "
    "SELECT :osm_type, :osm_id, :kind, :name, "
    "CASE WHEN GeometryType(g) IN ('POLYGON', 'MULTIPOLYGON') "
    "THEN ST_Multi(ST_CollectionExtract(ST_MakeValid(g), 3)) ELSE g END, :fetched_at "
    "FROM (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:geometry), 4326) AS g) s "
    "WHERE NOT ST_IsEmpty(g)"
)
_CLIP_SQL = (
    "DELETE FROM critical_facilities WHERE NOT ST_DWithin("
    "geom::geography, ST_SetSRID(ST_GeomFromGeoJSON(:boundary), 4326)::geography, CAST(:buffer AS float8))"
)


async def _status_row(db):
    from sqlalchemy import select
    from app.models import CriticalFacilitiesStatus

    row = (await db.execute(
        select(CriticalFacilitiesStatus).order_by(CriticalFacilitiesStatus.id).limit(1)
    )).scalar_one_or_none()
    if row is None:
        row = CriticalFacilitiesStatus()
        db.add(row)
    return row


async def counts_by_kind(db) -> Dict[str, int]:
    from sqlalchemy import func, select
    from app.models import CriticalFacility

    rows = (await db.execute(
        select(CriticalFacility.kind, func.count(CriticalFacility.id)).group_by(CriticalFacility.kind)
    )).all()
    return {kind: int(n) for kind, n in rows}


async def replace_facilities(db, facilities: List[Dict[str, Any]],
                             clip_to: Optional[Dict[str, Any]] = None) -> Dict[str, int]:
    """Swap the stored facilities for these, in one transaction. The caller commits.

    Delete and insert share the transaction, so a failure anywhere rolls back
    to the previous set rather than an empty or half-built table.
    """
    from sqlalchemy import delete, text
    from app.models import CriticalFacility

    now = datetime.now(timezone.utc)
    await db.execute(delete(CriticalFacility))
    for f in facilities:
        await db.execute(text(_INSERT_SQL), {
            "osm_type": f["osm_type"], "osm_id": f["osm_id"], "kind": f["kind"],
            "name": f.get("name"), "geometry": json.dumps(f["geometry"]), "fetched_at": now,
        })
    if clip_to:
        await db.execute(text(_CLIP_SQL), {"boundary": json.dumps(clip_to), "buffer": BOUNDARY_BUFFER_M})
    return await counts_by_kind(db)


async def refresh(db, *, fetch=None) -> Dict[str, Any]:
    """Fetch the town's facilities and replace the stored ones. Never raises.

    On any failure -- no boundary, Overpass down, an empty answer, a database
    error mid-swap -- the previous rows stay, and the error is recorded where
    the health check reads it.
    """
    fetch = fetch or fetch_facilities
    status = await _status_row(db)
    status.attempted_at = datetime.now(timezone.utc)
    await db.commit()

    boundary = await _load_boundary(db)
    bbox, clip_to = fetch_area(boundary)
    if not bbox:
        return await _fail(db, "no township boundary configured")

    try:
        facilities, source = await fetch(bbox)
    except Exception as exc:
        logger.warning("[critical facilities] fetch failed; keeping the stored set: %s", exc)
        return await _fail(db, f"fetch failed: {exc}")

    existing = sum((await counts_by_kind(db)).values())
    if not facilities and existing:
        # A town with no school, clinic or fire station anywhere in it is far
        # less likely than a truncated answer.
        return await _fail(db, f"fetch returned no facilities; keeping the {existing} stored")

    try:
        counts = await replace_facilities(db, facilities, clip_to)
        status = await _status_row(db)
        status.refreshed_at = datetime.now(timezone.utc)
        status.counts = counts
        status.source = source
        status.last_error = None
        status.failing_since = None
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("[critical facilities] replace failed; previous set kept", exc_info=True)
        return await _fail(db, f"store failed: {type(exc).__name__}: {exc}")

    logger.info("[critical facilities] refreshed from %s: %s", source,
                ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "none")
    return {"ok": True, "counts": counts, "total": sum(counts.values()), "source": source}


async def _fail(db, reason: str) -> Dict[str, Any]:
    try:
        status = await _status_row(db)
        status.last_error = reason[:500]
        if status.failing_since is None:
            status.failing_since = datetime.now(timezone.utc)
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning("[critical facilities] could not record the failure", exc_info=True)
    return {"ok": False, "reason": reason}


async def refresh_if_due(db, *, only_if_empty: bool = False, force: bool = False,
                         fetch=None) -> Dict[str, Any]:
    """The scheduled entry point: refresh when empty, or when a week old.

    Checked daily rather than scheduled weekly so that a failed refresh is
    retried the next day, not the next week.
    """
    now = datetime.now(timezone.utc)
    status = await _status_row(db)
    total = sum((await counts_by_kind(db)).values())
    if not force:
        if only_if_empty and total:
            return {"ok": True, "skipped": "already populated"}
        if status.attempted_at and now - status.attempted_at < ATTEMPT_COOLDOWN:
            return {"ok": True, "skipped": "attempted in the last 30 minutes"}
        if total and status.refreshed_at and now - status.refreshed_at < REFRESH_EVERY:
            return {"ok": True, "skipped": "refreshed within the week"}
    return await refresh(db, fetch=fetch)


async def store_status(db) -> Dict[str, Any]:
    """What the health check shows: freshness, counts, the last error. Read-only."""
    from sqlalchemy import select
    from app.models import CriticalFacilitiesStatus

    status = (await db.execute(
        select(CriticalFacilitiesStatus).order_by(CriticalFacilitiesStatus.id).limit(1)
    )).scalar_one_or_none()
    counts = await counts_by_kind(db)
    refreshed = getattr(status, "refreshed_at", None)
    attempted = getattr(status, "attempted_at", None)
    return {
        "refreshed_at": refreshed,
        "attempted_at": attempted,
        "counts": counts,
        "total": sum(counts.values()),
        "last_error": getattr(status, "last_error", None),
        "failing_since": getattr(status, "failing_since", None),
        "source": getattr(status, "source", None),
        "boundary_configured": bool(await _load_boundary(db)),
    }


# --------------------------------------------------------------------------- #
# The per-report check. Local only: nothing here talks to the network.
# --------------------------------------------------------------------------- #

def _deg(metres: float, lat: float) -> float:
    """A bounding distance in degrees, generous, for the index prefilter."""
    return metres / (111_320.0 * max(math.cos(math.radians(lat)), 0.01)) * 1.1


_NEAREST_SQL = (
    "SELECT DISTINCT ON (kind) kind, name, dist FROM ("
    "  SELECT kind, name, ST_Distance(geom::geography, p.g::geography) AS dist"
    "  FROM critical_facilities, (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS g) p"
    "  WHERE geom && ST_Expand(p.g, CAST(:deg AS float8))"
    "    AND ST_DWithin(geom::geography, p.g::geography,"
    "                   CASE WHEN kind = 'school' THEN CAST(:school_r AS float8) ELSE CAST(:r AS float8) END)"
    ") s ORDER BY kind, dist, name"
)


async def nearest_facilities(db, lat: float, lng: float) -> List[Dict[str, Any]]:
    """The nearest stored facility of each kind within its radius."""
    from sqlalchemy import text

    async with db.begin_nested():
        rows = (await db.execute(text(_NEAREST_SQL), {
            "lat": float(lat), "lng": float(lng), "deg": _deg(MAX_RADIUS_M, lat),
            "r": DEFAULT_RADIUS_M, "school_r": SCHOOL_RADIUS_M,
        })).mappings().all()
    return [{"kind": r["kind"], "label": KIND_LABELS.get(r["kind"], r["kind"]),
             "name": r["name"], "distance_m": float(r["dist"]), "source": "osm"} for r in rows]


_NAME_KEYS = ("name", "NAME", "Name", "facility", "FACILITY", "FacilityName", "SITE_NAME", "label")

# Every feature of an inline layer in one statement. A feature whose geometry
# is not a JSON object is skipped rather than failing the layer.
_INLINE_SQL = (
    "SELECT props, dist FROM ("
    "  SELECT f.value -> 'properties' AS props,"
    "         ST_Distance(ST_SetSRID(ST_GeomFromGeoJSON((f.value -> 'geometry')::text), 4326)::geography,"
    "                     ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) AS dist"
    "  FROM map_layers l CROSS JOIN LATERAL jsonb_array_elements("
    "       CASE WHEN jsonb_typeof(l.geojson::jsonb -> 'features') = 'array'"
    "            THEN l.geojson::jsonb -> 'features' ELSE '[]'::jsonb END) f"
    "  WHERE l.id = :layer_id AND jsonb_typeof(f.value -> 'geometry') = 'object'"
    ") s WHERE dist <= CAST(:r AS float8) ORDER BY dist LIMIT 1"
)
_TABLE_SQL = (
    "SELECT f.properties AS props, f.feature_key,"
    "       ST_Distance(f.geom::geography, p.g::geography) AS dist"
    "  FROM map_layer_features f, (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS g) p"
    " WHERE f.layer_id = :layer_id AND f.geom && ST_Expand(p.g, CAST(:deg AS float8))"
    "   AND ST_DWithin(f.geom::geography, p.g::geography, CAST(:r AS float8))"
    " ORDER BY dist LIMIT 1"
)
_INLINE_COVERS_SQL = (
    "SELECT 1 FROM map_layers l CROSS JOIN LATERAL jsonb_array_elements("
    "       CASE WHEN jsonb_typeof(l.geojson::jsonb -> 'features') = 'array'"
    "            THEN l.geojson::jsonb -> 'features' ELSE '[]'::jsonb END) f"
    " WHERE l.id = :layer_id AND jsonb_typeof(f.value -> 'geometry') = 'object'"
    "   AND (f.value -> 'geometry' ->> 'type') IN ('Polygon', 'MultiPolygon')"
    "   AND ST_Covers(ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON((f.value -> 'geometry')::text), 4326)),"
    "                 ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))"
    " LIMIT 1"
)
_TABLE_COVERS_SQL = (
    "SELECT 1 FROM map_layer_features f"
    " WHERE f.layer_id = :layer_id"
    "   AND ST_Covers(f.geom, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)) LIMIT 1"
)


def _feature_name(props: Any, layer, feature_key: Optional[str] = None) -> str:
    props = props if isinstance(props, dict) else {}
    if getattr(layer, "feature_storage", None) == "table":
        # Table-backed layers carry raw attribute tables (owner names on
        # parcels); only the label the admin chose is ever copied out.
        label = props.get(layer.label_property) if getattr(layer, "label_property", None) else None
        return str(label).strip() if label not in (None, "") else (feature_key or layer.name)
    for key in _NAME_KEYS:
        if props.get(key) not in (None, ""):
            return str(props[key]).strip()
    return layer.name


async def layer_matches(db, lat: float, lng: float, layers) -> Tuple[List[Dict[str, Any]], bool]:
    """(nearest feature per facility layer within its radius, inside a school zone?)

    One query per relevant layer, over all of its features. Each in its own
    savepoint: a layer with a malformed geometry is skipped, not fatal.
    """
    from sqlalchemy import text

    found: List[Dict[str, Any]] = []
    in_school_zone = False
    params = {"lat": float(lat), "lng": float(lng)}
    for layer in layers:
        table = getattr(layer, "feature_storage", None) == "table"
        kind = layer_kind(layer.name)
        if kind:
            r = radius_for(kind)
            try:
                async with db.begin_nested():
                    row = (await db.execute(
                        text(_TABLE_SQL if table else _INLINE_SQL),
                        {**params, "layer_id": layer.id, "r": r, "deg": _deg(r, lat)},
                    )).mappings().first()
                if row is not None:
                    found.append({
                        "kind": kind, "label": layer.name,
                        "name": _feature_name(row["props"], layer, row.get("feature_key") if table else None),
                        "distance_m": float(row["dist"]), "source": "layer",
                    })
            except Exception as exc:
                logger.warning("[critical facilities] layer %r skipped: %s", layer.name, exc)
        if is_school_zone_layer(layer.name) and not in_school_zone:
            try:
                async with db.begin_nested():
                    hit = (await db.execute(
                        text(_TABLE_COVERS_SQL if table else _INLINE_COVERS_SQL),
                        {**params, "layer_id": layer.id},
                    )).first()
                in_school_zone = hit is not None
            except Exception as exc:
                logger.warning("[critical facilities] school-zone layer %r skipped: %s", layer.name, exc)
    return found, in_school_zone


def format_entry(entry: Dict[str, Any]) -> str:
    """'Hospital: Name (123m)' -- the shape the prompt and staff chips expect."""
    name = entry.get("name") or f"unnamed {entry['label'].lower()}"
    return f"{entry['label']}: {name} ({int(round(entry['distance_m']))}m)"


async def proximity(db, lat: float, lng: float, layers=()) -> Dict[str, Any]:
    """Critical infrastructure near a point, from the local store and admin layers.

    Returns {"critical_infrastructure": [...strings, nearest first],
             "is_school_zone": bool, "entries": [...]}.
    """
    entries: List[Dict[str, Any]] = []
    try:
        entries.extend(await nearest_facilities(db, lat, lng))
    except Exception as exc:
        logger.warning("[critical facilities] store lookup failed: %s", exc)
    layer_entries, in_school_zone = await layer_matches(db, lat, lng, layers)
    entries.extend(layer_entries)

    # The same building from a town layer and from OSM is one fact, not two.
    entries.sort(key=lambda e: (e["distance_m"], e["source"] != "layer"))
    unique: List[Dict[str, Any]] = []
    seen = set()
    for e in entries:
        key = (e["kind"], (e.get("name") or "").strip().lower())
        if e.get("name") and key in seen:
            continue
        seen.add(key)
        unique.append(e)

    school_near = any(e["kind"] == "school" and e["distance_m"] <= SCHOOL_RADIUS_M for e in unique)
    return {
        "critical_infrastructure": [format_entry(e) for e in unique],
        "is_school_zone": bool(in_school_zone or school_near),
        "entries": unique,
    }
