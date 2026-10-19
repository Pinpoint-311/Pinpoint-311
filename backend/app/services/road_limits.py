"""Limits on an agency's road: "Oak Road (Elm Street to Route 10)".

A county or state agency often maintains only part of a road. Matching by name
alone claims all of it, so a resident on the town's end of Oak Road would
be sent to the county. A road entry can therefore carry two limiting cross
streets, and a report matches the agency only when its point lies on the road
between them.

How a limit is resolved, in PostGIS against road_segments:

  1. the road's segments are merged into lines (ST_LineMerge of the union);
  2. each limiting street is found by name, the same way a road entry is
     matched (normalize_road_name / road_matches), and intersected with each
     line; a cross street that stops a few metres short still counts;
  3. if a street crosses the road more than once, the pair of crossings
     closest together along the road is taken;
  4. a report's point is located along the same line (ST_LineLocatePoint)
     and compared against the two crossings, with LIMIT_TOLERANCE_METRES of
     slack at each end.

Anything that cannot be resolved -- the road or a cross street is not in the
data, the crossings sit on different pieces of the road -- falls back to the
whole road, which is what the rule meant before limits existed. That is never
silent: config-check reports it and the admin console shows it on the agency.

The decisions (pair choice, the tolerance test, the fallback wording) are pure
functions, testable without a database. The SQL only gathers fractions.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.road_matching import RoadEntry, parse_road_entry, road_matches

logger = logging.getLogger(__name__)

# Slack at each end of a limited stretch. A crossing is a point on a
# centreline; a pothole in the intersection itself, or a pin dropped on the
# corner, is still "at" the limit.
LIMIT_TOLERANCE_METRES = 25.0

# A cross street whose end sits this close to the road counts as meeting it.
# Publishers do not always snap a T-junction onto the through road.
NEAR_MISS_METRES = 25.0

# Resolutions are cached briefly. Road data changes monthly; a clerk editing
# limits sees the change on the next config-check after this.
_CACHE_SECONDS = 300.0
_cache: Dict[str, Tuple[float, "LimitResolution"]] = {}


RESOLVED = "resolved"
ROAD_NOT_FOUND = "road_not_found"
FROM_NOT_FOUND = "from_not_found"
TO_NOT_FOUND = "to_not_found"
NOT_CONNECTED = "not_connected"
NO_DATA = "no_data"

FALLBACK_NOTE = "Limits not found on the map, so the whole road is treated as theirs."


@dataclass
class LimitResolution:
    entry: str
    road: str
    from_street: str
    to_street: str
    status: str
    # Only when resolved: the line both crossings were found on, and where
    # along it (0..1) the stretch starts and ends.
    line_geojson: Optional[str] = None
    start: Optional[float] = None
    end: Optional[float] = None
    line_length_m: Optional[float] = None
    stretch_geojson: Optional[str] = None
    road_names: List[str] = field(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.status == RESOLVED

    @property
    def stretch_m(self) -> Optional[float]:
        if not self.resolved or self.line_length_m is None:
            return None
        return abs((self.end or 0.0) - (self.start or 0.0)) * self.line_length_m

    @property
    def message(self) -> str:
        return describe(self)

    def as_dict(self) -> Dict[str, Any]:
        stretch = self.stretch_m
        return {
            "entry": self.entry,
            "road": self.road,
            "from_street": self.from_street,
            "to_street": self.to_street,
            "status": self.status,
            "resolved": self.resolved,
            "message": self.message,
            "stretch_m": round(stretch) if stretch is not None else None,
            "road_length_m": round(self.line_length_m) if self.line_length_m else None,
            "stretch_geojson": json.loads(self.stretch_geojson) if self.stretch_geojson else None,
        }


# ---- pure decisions ----------------------------------------------------------

def describe(resolution: LimitResolution) -> str:
    """One sentence for the admin console, saying what the rule will do."""
    r = resolution
    if r.resolved:
        stretch = r.stretch_m
        length = f"{stretch / 1000:.1f} km" if stretch and stretch >= 1000 else f"{int(round(stretch or 0))} m"
        return f"{r.road} from {r.from_street} to {r.to_street}: {length} of road."
    reason = {
        ROAD_NOT_FOUND: f"{r.road} is not in this town's road data",
        FROM_NOT_FOUND: f"{r.from_street} was not found crossing {r.road}",
        TO_NOT_FOUND: f"{r.to_street} was not found crossing {r.road}",
        NOT_CONNECTED: (
            f"{r.from_street} and {r.to_street} meet {r.road} on separate pieces of it, "
            "or at the same point"
        ),
        NO_DATA: "road data is not loaded for this town",
    }.get(r.status, "they could not be checked")
    return f"{r.entry}: {FALLBACK_NOTE} ({reason}.)"


def choose_limit_pair(
    lines: Sequence[Dict[str, Any]],
) -> Optional[Tuple[int, float, float]]:
    """Pick the stretch the limits describe.

    `lines` is one dict per merged line of the road: {index, length_m,
    from: [fractions], to: [fractions]}. Returns (index, start, end) for the
    pair of crossings closest together along the road, or None when no line
    has both. A pair at the same point bounds nothing and is skipped.

    Closest, because a cross street that meets the road twice (a loop, a
    service road at both ends) usually means the shorter stretch is meant;
    taking the longer one would hand the agency extra road nobody listed.
    """
    best: Optional[Tuple[float, int, float, float]] = None
    for line in lines:
        length = float(line.get("length_m") or 0.0)
        if length <= 0:
            continue
        for a in line.get("from") or []:
            for b in line.get("to") or []:
                along = abs(float(b) - float(a)) * length
                if along < 1.0:
                    continue
                candidate = (along, int(line["index"]), float(a), float(b))
                if best is None or candidate < best:
                    best = candidate
    if best is None:
        return None
    _, index, a, b = best
    return index, a, b


def missing_side(lines: Sequence[Dict[str, Any]]) -> str:
    """Why no pair was found: which cross street is absent, if either."""
    has_from = any(line.get("from") for line in lines)
    has_to = any(line.get("to") for line in lines)
    if not has_from:
        return FROM_NOT_FOUND
    if not has_to:
        return TO_NOT_FOUND
    return NOT_CONNECTED


def within_limits(
    fraction: Optional[float],
    start: float,
    end: float,
    line_length_m: float,
    tolerance_m: float = LIMIT_TOLERANCE_METRES,
) -> bool:
    """Is a point at `fraction` along the line inside [start, end], with slack?

    An unknown position passes: a measurement gap is not evidence that the
    point is outside, and the rule falls back to the whole road elsewhere too.
    """
    if fraction is None or not line_length_m:
        return True
    lo, hi = sorted((float(start), float(end)))
    slack = tolerance_m / float(line_length_m)
    return lo - slack <= float(fraction) <= hi + slack


def matching_names(entry_name: str, known_names: Iterable[str]) -> List[str]:
    """Every road name in the data that a configured name refers to."""
    return sorted({n for n in known_names if n and road_matches(entry_name, n)})


def _without_directionals(name: str) -> str:
    from app.services.road_matching import _DIRECTIONS, normalize_road_name

    tokens = normalize_road_name(name).split()
    if len(tokens) > 1 and tokens[0] in _DIRECTIONS.values():
        tokens = tokens[1:]
    if len(tokens) > 1 and tokens[-1] in _DIRECTIONS.values():
        tokens = tokens[:-1]
    return " ".join(tokens)


def cross_street_names(
    street: str, known_names: Iterable[str], exclude: Iterable[str] = (), *, loose: bool = False
) -> List[str]:
    """Road names a limiting cross street may be filed under.

    Exact matching by default. With `loose`, a leading or trailing directional
    is ignored on both sides as well: a clerk writes "Elm Street" where the data
    calls the stretch that actually crosses "East Elm Street". That leniency is
    safe here and only here -- it locates a crossing on a road already named,
    and never decides who owns a road, where "Main St" and "N Main St" can be
    different agencies' roads. It is tried only when exact names find no
    crossing, so a town with both a "Elm St" and an "E Elm St" crossing the
    road gets the one the clerk wrote.
    """
    known = [n for n in known_names if n]
    skip = set(exclude)
    names = {n for n in matching_names(street, known) if n not in skip}
    if loose:
        bare = _without_directionals(street)
        if bare:
            names |= {n for n in known if n not in skip and _without_directionals(n) == bare}
    return sorted(names)


def limited_entries(config: Dict[str, Any]) -> List[Tuple[str, RoadEntry]]:
    """(agency name, entry) for every road entry in a config that has limits."""
    from app.services.road_matching import _as_list, jurisdictions_from_config

    out: List[Tuple[str, RoadEntry]] = []
    for jurisdiction in jurisdictions_from_config(config or {}):
        agency = jurisdiction.get("name") or "Another agency"
        for raw in _as_list(jurisdiction.get("roads")):
            entry = parse_road_entry(raw)
            if entry and entry.has_limits:
                out.append((agency, entry))
    return out


# ---- PostGIS -----------------------------------------------------------------

_LINES_SQL = text("""
    SELECT ST_AsGeoJSON(d.geom) AS geojson,
           ST_Length(d.geom::geography) AS length_m
    FROM (
        SELECT ST_LineMerge(ST_Union(geom)) AS geom
        FROM road_segments WHERE name = ANY(:names)
    ) merged, LATERAL ST_Dump(merged.geom) d
    WHERE GeometryType(d.geom) = 'LINESTRING'
    ORDER BY length_m DESC
""")

# Where a cross street meets one merged line, as fractions along it. Crossings
# first; a cross street that only comes within NEAR_MISS_METRES of the line
# contributes its closest point instead.
_CROSSINGS_SQL = text("""
    WITH line AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:line), 4326) AS g),
         cross_st AS (
             SELECT ST_Union(geom) AS g FROM road_segments WHERE name = ANY(:names)
         )
    SELECT ST_LineLocatePoint(line.g, ST_ClosestPoint(line.g, d.geom)) AS fraction
    FROM line, cross_st, LATERAL ST_Dump(ST_Intersection(line.g, cross_st.g)) d
    WHERE cross_st.g IS NOT NULL AND NOT ST_IsEmpty(d.geom)
    UNION ALL
    SELECT ST_LineLocatePoint(line.g, ST_ClosestPoint(line.g, cross_st.g))
    FROM line, cross_st
    WHERE cross_st.g IS NOT NULL
      AND NOT ST_Intersects(line.g, cross_st.g)
      AND ST_DWithin(line.g::geography, cross_st.g::geography, :near)
""")

_STRETCH_SQL = text("""
    SELECT ST_AsGeoJSON(ST_LineSubstring(ST_SetSRID(ST_GeomFromGeoJSON(:line), 4326), :lo, :hi))
""")

_LOCATE_SQL = text("""
    WITH line AS (SELECT ST_SetSRID(ST_GeomFromGeoJSON(:line), 4326) AS g),
         p AS (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) AS g)
    SELECT ST_LineLocatePoint(line.g, p.g) AS fraction,
           ST_Distance(line.g::geography, p.g::geography) AS distance_m
    FROM line, p
""")


async def _known_names(db: AsyncSession) -> List[str]:
    rows = await db.execute(text("SELECT DISTINCT name FROM road_segments WHERE name IS NOT NULL"))
    return [r[0] for r in rows.all()]


def clear_cache() -> None:
    _cache.clear()


async def resolve_limits(
    db: AsyncSession,
    entry: RoadEntry,
    *,
    known_names: Optional[Sequence[str]] = None,
    use_cache: bool = True,
) -> LimitResolution:
    """Find the stretch of road an entry's limits describe. Never raises."""
    base = LimitResolution(
        entry=entry.label, road=entry.name,
        from_street=entry.from_street or "", to_street=entry.to_street or "",
        status=NO_DATA,
    )
    if not entry.has_limits:
        return base
    key = entry.label.lower()
    now = time.monotonic()
    if use_cache:
        hit = _cache.get(key)
        if hit and now - hit[0] < _CACHE_SECONDS:
            return hit[1]

    try:
        names = list(known_names) if known_names is not None else await _known_names(db)
        if not names:
            return base
        road_names = matching_names(entry.name, names)
        base.road_names = road_names
        if not road_names:
            base.status = ROAD_NOT_FOUND
            result = base
        else:
            result = await _resolve_on_lines(db, base, road_names, names, entry)
    except Exception as exc:
        logger.warning("could not resolve limits for %r, using the whole road: %s", entry.label, exc)
        return base

    if use_cache:
        _cache[key] = (now, result)
    return result


async def _resolve_on_lines(
    db: AsyncSession,
    base: LimitResolution,
    road_names: List[str],
    names: Sequence[str],
    entry: RoadEntry,
) -> LimitResolution:
    road_set = set(road_names)
    rows = (await db.execute(_LINES_SQL, {"names": road_names})).all()
    if not rows:
        base.status = ROAD_NOT_FOUND
        return base
    lines: List[Dict[str, Any]] = [
        {"index": i, "length_m": float(row.length_m or 0), "geojson": row.geojson, "from": [], "to": []}
        for i, row in enumerate(rows)
    ]

    async def crossings(side: str, street: str, loose: bool) -> None:
        # A cross street that is the road itself is no limit at all.
        side_names = cross_street_names(street, names, road_set, loose=loose)
        if not side_names:
            return
        for line in lines:
            found = await db.execute(
                _CROSSINGS_SQL, {"line": line["geojson"], "names": side_names, "near": NEAR_MISS_METRES}
            )
            line[side] = [float(f[0]) for f in found.all() if f[0] is not None]

    for side, street in (("from", entry.from_street or ""), ("to", entry.to_street or "")):
        await crossings(side, street, loose=False)
        if not any(line[side] for line in lines):
            await crossings(side, street, loose=True)

    pair = choose_limit_pair(lines)
    if pair is None:
        base.status = missing_side(lines)
        return base

    index, start, end = pair
    chosen = lines[index]
    lo, hi = sorted((start, end))
    stretch = (await db.execute(_STRETCH_SQL, {"line": chosen["geojson"], "lo": lo, "hi": hi})).scalar()
    base.status = RESOLVED
    base.line_geojson = chosen["geojson"]
    base.start, base.end = start, end
    base.line_length_m = chosen["length_m"]
    base.stretch_geojson = stretch
    return base


async def point_within(
    db: AsyncSession,
    resolution: LimitResolution,
    lat: float,
    lng: float,
    *,
    radius_m: float,
) -> Optional[bool]:
    """True/False when the limits are resolved; None means use the whole road.

    The point must be near the same line the limits were found on -- a road
    split in two by a gap in the data has another piece the limits say nothing
    about -- and between the crossings.
    """
    if not resolution.resolved or not resolution.line_geojson:
        return None
    row = (await db.execute(
        _LOCATE_SQL, {"line": resolution.line_geojson, "lat": lat, "lng": lng}
    )).first()
    if row is None or row.fraction is None:
        return None
    if row.distance_m is not None and float(row.distance_m) > radius_m + LIMIT_TOLERANCE_METRES:
        return False
    return within_limits(
        float(row.fraction), resolution.start or 0.0, resolution.end or 0.0,
        resolution.line_length_m or 0.0,
    )


async def entries_outside(
    db: AsyncSession,
    config: Dict[str, Any],
    road_names: Sequence[str],
    lat: float,
    lng: float,
    *,
    radius_m: float,
) -> set:
    """Limited entries (by label) whose stretch this point is definitely off.

    Only entries naming one of `road_names` -- the roads near the pin -- are
    checked, so a config full of limits costs nothing for a pin on a side
    street. Unresolvable limits are never in the set: they fall back to the
    whole road.
    """
    outside: set = set()
    for _agency, entry in limited_entries(config):
        if not any(road_matches(entry.name, n) for n in road_names if n):
            continue
        resolution = await resolve_limits(db, entry)
        inside = await point_within(db, resolution, lat, lng, radius_m=radius_m)
        if inside is False:
            outside.add(entry.label)
    return outside
