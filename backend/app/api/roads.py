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
