"""Road resolution endpoints: the pre-submit check, config validation, status.

The resident portal calls `/road-check` when a pin settles so someone learns
they are on a county road before typing a description, not after. The create
endpoint re-evaluates the same rules server-side regardless -- this is a
courtesy, never the enforcement point.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin, get_current_staff
from app.db.session import get_db
from app.models import RoadDataStatus, RoadSegment, ServiceDefinition, User
from app.services import road_blocking
from app.services.road_geometry import check_config, resolve_road

logger = logging.getLogger(__name__)
router = APIRouter()


class RoadCheckRequest(BaseModel):
    service_code: str
    lat: Optional[float] = None
    long: Optional[float] = None


@router.post("/road-check")
async def road_check(payload: RoadCheckRequest, db: AsyncSession = Depends(get_db)):
    """Would a report here be redirected, and which road decided that?

    Unauthenticated: residents use it before submitting. It reveals only what a
    clerk already published -- which roads belong to which agency.
    """
    service = (
        await db.execute(
            select(ServiceDefinition).where(ServiceDefinition.service_code == payload.service_code)
        )
    ).scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Unknown service")

    decision = await road_blocking.evaluate(db, service, payload.lat, payload.long)

    # The detected road is returned even when nothing is blocked, so the picker
    # can show "Road detected: Cranbury Rd" and a resident can see for themselves
    # that the pin landed where they meant it to.
    detected = None
    if payload.lat is not None and payload.long is not None:
        match = await resolve_road(db, payload.lat, payload.long)
        if match:
            detected = {"name": match.label, "distance_m": round(match.distance_m, 1)}

    return {
        "blocked": decision.blocked,
        "block_type": decision.block_type,
        "jurisdiction": decision.jurisdiction,
        "message": decision.message,
        "contacts": decision.contacts,
        "road": decision.road_name,
        "detected_road": detected,
    }


@router.get("/roads/search")
async def search_roads(
    q: str = Query("", min_length=0, max_length=80),
    limit: int = Query(15, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """Autocomplete for the clerk configuring which roads belong to whom.

    Returns distinct road NAMES, not segments. Cranbury Rd may be forty segments
    in the data and showing forty rows would be unusable; the clerk picks the
    name once and every segment comes along. Segment-level control lives on the
    map, where they can click an individual piece off.
    """
    query = (
        select(
            RoadSegment.name,
            RoadSegment.ref,
            func.count(RoadSegment.id).label("segments"),
        )
        .where(RoadSegment.name.isnot(None))
        .group_by(RoadSegment.name, RoadSegment.ref)
        .order_by(func.count(RoadSegment.id).desc())
        .limit(limit)
    )
    if q:
        query = query.where(RoadSegment.name_norm.ilike(f"%{q.strip().lower()}%"))

    try:
        rows = (await db.execute(query)).all()
    except Exception as exc:
        # No road table yet is a normal state during setup, not an error the
        # clerk should see as a failure.
        logger.info("road search unavailable: %s", exc)
        return {"roads": [], "available": False}

    return {
        "available": True,
        "roads": [
            {"name": row.name, "ref": row.ref, "segments": row.segments}
            for row in rows
        ],
    }


class ConfigCheckRequest(BaseModel):
    routing_config: Dict[str, Any]


@router.post("/roads/config-check")
async def config_check(
    payload: ConfigCheckRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """Problems in a routing config, before it is saved.

    Errors block the save; warnings and info do not. The warning that matters
    most is a road matching nothing -- a typo produces a rule that fires never,
    and today there is no indication of it at all.
    """
    try:
        names = [
            row[0]
            for row in (
                await db.execute(
                    select(RoadSegment.name).where(RoadSegment.name.isnot(None)).distinct()
                )
            ).all()
        ]
    except Exception:
        names = []  # cannot tell a typo from a real road; suppress those warnings

    issues = check_config(payload.routing_config or {}, names)
    return {
        "issues": [
            {"severity": i.severity, "kind": i.kind, "message": i.message, "roads": i.roads}
            for i in issues
        ],
        "can_save": not any(i.severity == "error" for i in issues),
        "roads_known": len(names),
    }


@router.get("/roads/status")
async def road_status(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Read-only line for admin System Health. Never a task, just information.

    `fetched_at` and `source_updated_at` are deliberately both shown: re-fetching
    unchanged data forever looks healthy while the publisher has quietly stopped
    maintaining the layer.
    """
    status = (await db.execute(select(RoadDataStatus).limit(1))).scalar_one_or_none()
    if not status:
        return {"configured": False}
    return {
        "configured": True,
        "source": status.source_name,
        "state": status.state_code,
        "endpoint": status.endpoint,
        "segments": status.segment_count,
        "fetched_at": status.fetched_at.isoformat() if status.fetched_at else None,
        "source_updated_at": (
            status.source_updated_at.isoformat() if status.source_updated_at else None
        ),
        "corridor_metres": status.corridor_metres,
        "consecutive_failures": status.consecutive_failures,
        "last_error": status.last_error,
    }


@router.get("/roads/geometry")
async def road_geometry(
    names: str = Query("", description="Comma-separated road names"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """GeoJSON for the roads a clerk has selected, so they can see what a rule
    covers before saving it.

    Returns one feature per segment rather than merging them. A clerk needs to
    switch an individual piece off -- the data lumps a service spur or a stretch
    the town actually maintains under the same name -- and that is impossible if
    the geometry arrives already dissolved.
    """
    from app.services.road_matching import normalize_road_name

    wanted = [n.strip() for n in names.split(",") if n.strip()]
    if not wanted:
        return {"type": "FeatureCollection", "features": []}

    normalized = [normalize_road_name(n) for n in wanted]
    normalized = [n for n in normalized if n]
    if not normalized:
        return {"type": "FeatureCollection", "features": []}

    try:
        rows = (
            await db.execute(
                select(
                    RoadSegment.id,
                    RoadSegment.source_feature_id,
                    RoadSegment.name,
                    RoadSegment.ref,
                    func.ST_AsGeoJSON(RoadSegment.geom).label("geojson"),
                ).where(
                    RoadSegment.name_norm.in_(normalized) | RoadSegment.ref_norm.in_(normalized)
                ).limit(5000)
            )
        ).all()
    except Exception as exc:
        logger.info("road geometry unavailable: %s", exc)
        return {"type": "FeatureCollection", "features": [], "available": False}

    import json as _json

    return {
        "type": "FeatureCollection",
        "available": True,
        "features": [
            {
                "type": "Feature",
                "geometry": _json.loads(row.geojson),
                "properties": {
                    "segment_id": row.id,
                    "feature_id": row.source_feature_id,
                    "name": row.name,
                    "ref": row.ref,
                },
            }
            for row in rows
        ],
    }


@router.post("/roads/corridor-check")
async def corridor_check(
    payload: ConfigCheckRequest,
    corridor_m: int = Query(20, ge=3, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """Find corridors that run alongside each other at the chosen width.

    Roads crossing is normal -- every intersection overlaps -- so only sustained
    parallel overlap is reported. Computed in PostGIS by intersecting buffered
    geometries and measuring the length of the result, which is what separates
    a junction (a small patch) from a frontage road (a long ribbon).
    """
    from sqlalchemy import text

    from app.services.road_geometry import parallel_overlap_flags
    from app.services.road_matching import _as_list, normalize_road_name

    config = payload.routing_config or {}
    names: List[str] = []
    for jurisdiction in config.get("jurisdictions") or []:
        if isinstance(jurisdiction, dict):
            names.extend(_as_list(jurisdiction.get("roads")))
    names.extend(_as_list(config.get("exclusion_list")))
    normalized = sorted({n for n in (normalize_road_name(x) for x in names) if n})

    if len(normalized) < 2:
        return {"issues": [], "corridor_metres": corridor_m}

    # Pairwise, on the buffered union of each road. Only listed roads are
    # considered, so this stays a handful of geometries however large the town.
    sql = text("""
        WITH roads AS (
            SELECT name_norm, ST_Union(geom::geography::geometry) AS geom
            FROM road_segments
            WHERE name_norm = ANY(:names)
            GROUP BY name_norm
        )
        SELECT a.name_norm AS road_a, b.name_norm AS road_b,
               ST_Length(
                   ST_Intersection(
                       ST_Buffer(a.geom::geography, :radius)::geometry,
                       ST_Buffer(b.geom::geography, :radius)::geometry
                   )::geography
               ) AS overlap_length_m
        FROM roads a JOIN roads b ON a.name_norm < b.name_norm
        WHERE ST_Intersects(
            ST_Buffer(a.geom::geography, :radius)::geometry,
            ST_Buffer(b.geom::geography, :radius)::geometry
        )
    """)

    try:
        rows = (await db.execute(sql, {"names": normalized, "radius": corridor_m})).mappings().all()
    except Exception as exc:
        # No PostGIS, no road table, or a geometry error. The clerk can still
        # save -- this check is advisory, not a gate.
        logger.info("corridor overlap check unavailable: %s", exc)
        return {"issues": [], "corridor_metres": corridor_m, "available": False}

    flags = parallel_overlap_flags([dict(r) for r in rows], corridor_m=corridor_m)
    return {
        "available": True,
        "corridor_metres": corridor_m,
        "issues": [
            {"severity": f.severity, "kind": f.kind, "message": f.message, "roads": f.roads}
            for f in flags
        ],
    }


class CorridorWidthRequest(BaseModel):
    corridor_metres: int


@router.put("/roads/corridor-width")
async def set_corridor_width(
    payload: CorridorWidthRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """How far from a centreline still counts as being on that road.

    Per town because a dense borough with 8 m rights-of-way and a rural township
    with wide shoulders want different numbers, and because it has to absorb
    disagreement between the road data and whatever basemap the resident sees.
    """
    width = max(3, min(100, payload.corridor_metres))
    status = (await db.execute(select(RoadDataStatus).limit(1))).scalar_one_or_none()
    if status is None:
        status = RoadDataStatus()
        db.add(status)
    status.corridor_metres = width
    await db.commit()
    return {"corridor_metres": width}


@router.post("/roads/seed")
async def trigger_road_seed(
    force: bool = Query(True, description="Force re-download even if unchanged"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    from app.tasks.road_data import seed_roads_for_boundary
    result = await seed_roads_for_boundary(db, force=force)
    return result
