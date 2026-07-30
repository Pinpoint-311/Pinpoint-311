"""Decide whether a report should be redirected, and record it when it is.

Two kinds of redirect, and the statistics page reports them separately because
they mean different things to a clerk:

  * `category` -- the whole service is handled by an outside agency. Nothing
    spatial about it; it applies wherever the resident points.
  * `road_based` -- this particular road belongs to someone else.

Blocking was previously evaluated only in the resident portal's JavaScript, so
a report taken by phone through manual intake, or POSTed straight at the Open311
endpoint, ignored road rules entirely. Deciding it here means every path agrees.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BlockedRequestLog, RoadDataStatus, ServiceDefinition
from app.services.road_geometry import (
    DEFAULT_CORRIDOR_METRES,
    resolve_jurisdiction_spatial,
)

logger = logging.getLogger(__name__)


@dataclass
class BlockDecision:
    blocked: bool
    block_type: Optional[str] = None          # "category" | "road_based"
    jurisdiction: Optional[str] = None
    message: str = ""
    contacts: List[Dict[str, str]] = None
    road_name: Optional[str] = None
    # True when `message` is our generated sentence rather than something the
    # clerk wrote. The string is still filled in, because API clients of the 409
    # get only that field and a blank one explains nothing -- but the portal has
    # a heading that already says the same thing, so it uses this to avoid
    # printing "Cranbury Rd is maintained by County DPW" twice in a row.
    message_is_default: bool = False

    def __post_init__(self) -> None:
        if self.contacts is None:
            self.contacts = []


NOT_BLOCKED = BlockDecision(blocked=False)


async def _corridor_metres(db: AsyncSession) -> float:
    """Per-town corridor half-width. A dense borough and a rural township want
    different numbers, and it also has to absorb disagreement between the road
    data and whatever basemap the resident is looking at."""
    try:
        from sqlalchemy import select

        status = (await db.execute(select(RoadDataStatus).limit(1))).scalar_one_or_none()
        if status and status.corridor_metres:
            return float(status.corridor_metres)
    except Exception:
        pass
    return float(DEFAULT_CORRIDOR_METRES)


async def evaluate(
    db: AsyncSession,
    service: ServiceDefinition,
    lat: Optional[float],
    lng: Optional[float],
) -> BlockDecision:
    """Should this report be redirected instead of filed?

    Fails open on every path. A missing config, an unreachable road table, a
    pin with no coordinates, an unexpected error -- all return "not blocked".
    Turning a resident away who should have been able to report is the worst
    outcome this code can produce and there is no override for them.
    """
    try:
        mode = (service.routing_mode or "township").lower()
        config: Dict[str, Any] = service.routing_config or {}

        if mode == "third_party":
            contacts = config.get("contacts") or []
            # There is no separate agency-name field on this mode, only contacts,
            # so fall back to the first contact's name. "Another agency" reads as
            # the system not knowing, when the clerk did in fact say who.
            first = contacts[0] if contacts and isinstance(contacts[0], dict) else {}
            name = (
                config.get("third_party_name")
                or (first.get("name") or "").strip()
                or "Another agency"
            )
            return BlockDecision(
                blocked=True,
                block_type="category",
                jurisdiction=name,
                # Never empty: API clients of the 409 get only this string, and a
                # blank one tells a resident nothing about why they were stopped.
                message=config.get("message") or f"This service is handled by {name}.",
                message_is_default=not (config.get("message") or "").strip(),
                contacts=contacts,
            )

        if mode != "road_based":
            return NOT_BLOCKED

        radius = await _corridor_metres(db)
        match = await resolve_jurisdiction_spatial(db, config, lat, lng, radius_m=radius)
        if match is None:
            return NOT_BLOCKED

        return BlockDecision(
            blocked=True,
            block_type="road_based",
            jurisdiction=match.name,
            message=match.message or f"This road is maintained by {match.name}.",
            message_is_default=not (match.message or "").strip(),
            contacts=match.contacts or [],
            road_name=match.matched_road,
        )
    except Exception as exc:
        logger.warning("block evaluation failed, allowing the report through: %s", exc)
        return NOT_BLOCKED


async def record(
    db: AsyncSession,
    decision: BlockDecision,
    service: ServiceDefinition,
    lat: Optional[float],
    lng: Optional[float],
) -> None:
    """Log a redirect so the town can count them.

    Not a ServiceRequest: nobody works this, and it must never surface in a
    queue, a feed, an export or the public map. But twenty redirects a month on
    one road is either evidence for a conversation with the county or a sign the
    config is wrong, and without this row there is no way to know either.

    Never raises -- failing to log a redirect must not turn into a 500 on top of
    an already-unhappy resident interaction.
    """
    if not decision.blocked:
        return
    try:
        db.add(BlockedRequestLog(
            service_code=service.service_code,
            service_name=service.service_name,
            jurisdiction_name=decision.jurisdiction,
            road_name=decision.road_name,
            block_type=decision.block_type,
            lat=lat,
            long=lng,
        ))
        await db.commit()
    except Exception as exc:
        logger.warning("could not record blocked request: %s", exc)
        try:
            await db.rollback()
        except Exception:
            pass
