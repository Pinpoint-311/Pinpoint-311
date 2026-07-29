"""Decide which road a pin is on, and whose road it is.

This replaces reading a road name out of a reverse-geocoded address string.
The old approach answered "what is the nearest address", which is a different
question and got two cases wrong every time:

  * a corner lot's address belongs to the cross street, so a pin on Main St
    resolved to Oak Ave and blocked against the wrong jurisdiction;
  * a park's mailing address is on the road out front, so a pothole 30 m up the
    park driveway blocked as though it were on that road.

Both outcomes wrongly turned a resident away, and there is no override for them.

The rule, in order:

  1. Roads the town has explicitly claimed win outright -- a municipality
     sometimes maintains one stretch of an otherwise county road.
  2. Otherwise the nearest centreline wins, which is what "which road are you
     on" actually means.
  3. Ties go to the town. Near an intersection a pin is close to two roads, and
     although the higher agency usually does own the intersection in practice,
     being wrong that way turns a resident away, while being wrong toward the
     town costs one reassignment. Configurable for towns that know their
     maintenance agreements.

Everything fails open. No road within range, no data, a broken config, a query
error -- all resolve to "the municipality handles it".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RoadSegment
from app.services.road_matching import JurisdictionMatch, road_matches, _as_list

logger = logging.getLogger(__name__)

DEFAULT_CORRIDOR_METRES = 20

# Two roads whose nearest points are within this of each other are, for our
# purposes, equidistant -- an intersection rather than a clear answer.
TIE_TOLERANCE_METRES = 2.0

# Overlap longer than this multiple of the corridor width is two roads running
# parallel, not two roads crossing. Crossings are normal and must not be
# flagged; parallel corridors are a genuine ambiguity a clerk should resolve.
PARALLEL_OVERLAP_RATIO = 2.0


@dataclass
class RoadMatch:
    name: Optional[str]
    ref: Optional[str]
    distance_m: float
    segment_id: int
    source_feature_id: str
    highway_class: Optional[str]

    @property
    def label(self) -> str:
        return self.name or self.ref or "unnamed road"


def _point(lat: float, lng: float):
    return func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)


def nearest_roads_query(lat: float, lng: float, radius_m: float, limit: int = 8):
    """Roads within `radius_m` of a point, nearest first.

    ST_DWithin on geography does the index-accelerated cut-off; ordering by the
    `<->` KNN operator keeps the GIST index in play instead of sorting every
    candidate. Distances come back in true metres from the geography cast, so
    there is no per-state projected SRID to configure.
    """
    point = _point(lat, lng)
    distance = func.ST_Distance(cast(RoadSegment.geom, Geography), cast(point, Geography))
    return (
        select(
            RoadSegment.id,
            RoadSegment.name,
            RoadSegment.ref,
            RoadSegment.source_feature_id,
            RoadSegment.highway_class,
            distance.label("distance_m"),
        )
        .where(func.ST_DWithin(cast(RoadSegment.geom, Geography), cast(point, Geography), radius_m))
        .order_by(RoadSegment.geom.op("<->")(point))
        .limit(limit)
    )


async def nearest_roads(
    db: AsyncSession, lat: float, lng: float, *, radius_m: float = DEFAULT_CORRIDOR_METRES, limit: int = 8
) -> List[RoadMatch]:
    """Every road within range, nearest first. Empty when the pin is off-road."""
    try:
        rows = (await db.execute(nearest_roads_query(lat, lng, radius_m, limit))).all()
    except Exception as exc:
        # No road table yet, PostGIS missing, a bad geometry -- none of these
        # should stop someone reporting a pothole.
        logger.warning("nearest_roads failed, treating pin as off-road: %s", exc)
        return []
    return [
        RoadMatch(
            name=row.name,
            ref=row.ref,
            distance_m=float(row.distance_m),
            segment_id=row.id,
            source_feature_id=row.source_feature_id,
            highway_class=row.highway_class,
        )
        for row in rows
    ]


async def resolve_road(
    db: AsyncSession, lat: float, lng: float, *, radius_m: float = DEFAULT_CORRIDOR_METRES
) -> Optional[RoadMatch]:
    """The road this pin is on, or None if it is not on one.

    None is the park-driveway answer and it is a normal outcome, not an error.
    """
    matches = await nearest_roads(db, lat, lng, radius_m=radius_m, limit=1)
    return matches[0] if matches else None


def _municipal_entries(config: Dict[str, Any]) -> List[str]:
    return _as_list(config.get("municipal_roads")) or _as_list(config.get("inclusion_list"))


def _jurisdictions(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    jurisdictions = config.get("jurisdictions")
    if isinstance(jurisdictions, list) and jurisdictions:
        return [j for j in jurisdictions if isinstance(j, dict)]
    # Pre-multi-jurisdiction config: one unnamed third party.
    roads = _as_list(config.get("exclusion_list"))
    if not roads:
        return []
    return [{
        "name": config.get("third_party_name") or "Another agency",
        "roads": roads,
        "message": config.get("third_party_message") or "",
        "contacts": config.get("third_party_contacts") or [],
    }]


def _matching_jurisdiction(
    jurisdictions: Sequence[Dict[str, Any]],
    road: RoadMatch,
    excluded: Optional[set] = None,
) -> Optional[Tuple[Dict[str, Any], str]]:
    if excluded and road.source_feature_id in excluded:
        return None  # switched off in the coverage map
    for jurisdiction in jurisdictions:
        for entry in _as_list(jurisdiction.get("roads")):
            if road_matches(entry, road.name or "") or (road.ref and road_matches(entry, road.ref)):
                return jurisdiction, entry
    return None


def excluded_feature_ids(config: Dict[str, Any]) -> set:
    """Stretches a clerk switched off in the coverage map.

    Keyed to the publisher's own feature id rather than our row id, because the
    row id changes on every monthly refresh and would orphan the correction.
    """
    raw = config.get("excluded_segments")
    return {str(v) for v in raw} if isinstance(raw, list) else set()


def choose_road(
    candidates: Sequence[RoadMatch],
    config: Dict[str, Any],
    *,
    tie_tolerance_m: float = TIE_TOLERANCE_METRES,
    town_wins_ties: bool = True,
) -> Optional[Tuple[RoadMatch, Optional[Tuple[Dict[str, Any], str]]]]:
    """Pick the road that decides routing, and the jurisdiction claiming it.

    Pure, so the precedence rules are testable without a database.

    Returns (road, None) when the town is responsible and (road, (jurisdiction,
    matched_entry)) when someone else is. Returns None when there is no road.
    """
    if not candidates:
        return None

    # A stretch the clerk switched off is not removed from consideration -- it
    # can still be the nearest road, and the town is still responsible for it.
    # It just cannot be claimed by a jurisdiction.
    excluded = excluded_feature_ids(config)

    ordered = sorted(candidates, key=lambda r: r.distance_m)
    municipal = _municipal_entries(config)
    jurisdictions = _jurisdictions(config)

    # A road the town explicitly claims wins even if it is not the nearest --
    # this is the town-maintained stretch of a county road.
    for road in ordered:
        for entry in municipal:
            if road_matches(entry, road.name or "") or (road.ref and road_matches(entry, road.ref)):
                return road, None

    nearest = ordered[0]
    tied = [r for r in ordered if r.distance_m - nearest.distance_m <= tie_tolerance_m]

    if town_wins_ties and len(tied) > 1:
        # Near an intersection: if any tied road is unclaimed, the town keeps it.
        # Being wrong this way costs a reassignment; being wrong the other way
        # turns a resident away with no recourse.
        for road in tied:
            if _matching_jurisdiction(jurisdictions, road, excluded) is None:
                return road, None

    for road in tied:
        claim = _matching_jurisdiction(jurisdictions, road, excluded)
        if claim is not None:
            return road, claim

    return nearest, None


async def resolve_jurisdiction_spatial(
    db: AsyncSession,
    config: Optional[Dict[str, Any]],
    lat: Optional[float],
    lng: Optional[float],
    *,
    radius_m: float = DEFAULT_CORRIDOR_METRES,
    town_wins_ties: bool = True,
) -> Optional[JurisdictionMatch]:
    """Whose road is this pin on? None means the municipality's.

    Same contract as road_matching.resolve_jurisdiction, decided by geometry
    instead of by string-matching an address. Fails open on every path.
    """
    if not config or lat is None or lng is None:
        return None

    # A per-rule width set in the coverage map beats the town default: one
    # service may cover a highway with wide shoulders while another covers
    # residential streets.
    rule_width = config.get("corridor_metres")
    if isinstance(rule_width, (int, float)) and 3 <= rule_width <= 100:
        radius_m = float(rule_width)

    try:
        candidates = await nearest_roads(db, lat, lng, radius_m=radius_m)
        chosen = choose_road(candidates, config, town_wins_ties=town_wins_ties)
    except Exception as exc:
        logger.warning("spatial jurisdiction resolution failed, defaulting to municipality: %s", exc)
        return None

    if chosen is None:
        return None  # off-road: no listed road can reach this pin
    road, claim = chosen
    if claim is None:
        return None

    jurisdiction, matched_entry = claim
    return JurisdictionMatch(
        name=jurisdiction.get("name") or "Another agency",
        message=jurisdiction.get("message") or "",
        contacts=jurisdiction.get("contacts") or [],
        matched_road=road.label,
        matched_entry=matched_entry,
    )


# ---- configuration conflicts -------------------------------------------------

@dataclass
class ConfigIssue:
    severity: str      # "error" blocks saving, "warning" and "info" do not
    kind: str
    message: str
    roads: List[str]


def check_config(config: Dict[str, Any], known_road_names: Sequence[str]) -> List[ConfigIssue]:
    """Problems a clerk should see before their routing config is accepted.

    Deliberately does not flag geometric overlap at intersections: every
    crossing overlaps, so flagging it would be pure noise. What matters is a
    *rule* conflict -- the same road claimed twice -- and a rule that silently
    matches nothing, which is the most common real misconfiguration and today
    fires never with no indication.
    """
    issues: List[ConfigIssue] = []
    jurisdictions = _jurisdictions(config)
    municipal = _municipal_entries(config)

    claimed: Dict[str, List[str]] = {}
    for jurisdiction in jurisdictions:
        name = jurisdiction.get("name") or "Another agency"
        for entry in _as_list(jurisdiction.get("roads")):
            key = entry.strip().lower()
            claimed.setdefault(key, []).append(name)

    for key, owners in claimed.items():
        if len(set(owners)) > 1:
            issues.append(ConfigIssue(
                severity="error",
                kind="road_claimed_twice",
                message=(
                    f"\"{key}\" is assigned to {' and '.join(sorted(set(owners)))}. "
                    "Reports on it would route to whichever was checked first. "
                    "Assign it to one."
                ),
                roads=[key],
            ))

    known = [n for n in known_road_names if n]
    for jurisdiction in jurisdictions:
        for entry in _as_list(jurisdiction.get("roads")):
            if known and not any(road_matches(entry, name) for name in known):
                issues.append(ConfigIssue(
                    severity="warning",
                    kind="road_matches_nothing",
                    message=(
                        f"\"{entry}\" does not match any road in this town's data, so this "
                        "rule will never apply. Check the spelling."
                    ),
                    roads=[entry],
                ))

    for entry in municipal:
        for jurisdiction in jurisdictions:
            if any(road_matches(entry, other) for other in _as_list(jurisdiction.get("roads"))):
                issues.append(ConfigIssue(
                    severity="info",
                    kind="municipal_override",
                    message=(
                        f"\"{entry}\" is listed as town-maintained and also claimed by "
                        f"{jurisdiction.get('name')}. The town takes precedence."
                    ),
                    roads=[entry],
                ))

    return issues


def parallel_overlap_flags(
    overlaps: Sequence[Dict[str, Any]], corridor_m: float
) -> List[ConfigIssue]:
    """Flag corridors that run alongside each other, not ones that merely cross.

    `overlaps` is [{road_a, road_b, overlap_length_m}] computed in PostGIS. Two
    roads crossing produce a short overlap around the junction; two roads
    running parallel produce a long ribbon, and a pin between them is inside
    both corridors. Only the second is a real ambiguity, and the usual fix is a
    narrower corridor for that town rather than editing any road.
    """
    threshold = corridor_m * PARALLEL_OVERLAP_RATIO
    flags: List[ConfigIssue] = []
    for overlap in overlaps:
        length = float(overlap.get("overlap_length_m") or 0)
        if length <= threshold:
            continue  # an intersection; normal
        a, b = overlap.get("road_a"), overlap.get("road_b")
        flags.append(ConfigIssue(
            severity="warning",
            kind="parallel_corridors",
            message=(
                f"{a} and {b} run alongside each other for {int(length)} m, so their "
                f"{int(corridor_m)} m corridors overlap. A report between them could match "
                "either. Narrow the corridor width or confirm which road takes precedence."
            ),
            roads=[str(a), str(b)],
        ))
    return flags
