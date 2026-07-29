"""Seed and refresh a town's road centrelines. No clerk ever touches this.

Roads arrive as a side effect of setting the boundary, which a town does during
setup anyway, and then keep themselves current. There is no import screen, no
upload, no "refresh road data" button -- every one of those is a task someone
has to remember, and eventually does not.

Refresh is monthly rather than nightly for two reasons: publishers republish
about that often (New Jersey's statewide NG911 layer is monthly), and stale road
data fails open, so the cost of lag is a new street going unblocked for a few
weeks rather than a resident being turned away.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import delete, func, select, text

from app.core.celery_app import celery_app
from app.models import RoadDataStatus, RoadSegment
from app.services.road_alerts import (
    broken_rules,
    build_alerts,
    configured_roads,
    diff_road_names,
)
from app.services.road_sources import (
    fetch_segments,
    fetch_source_updated_at,
    resolve_source,
)

logger = logging.getLogger(__name__)

# A refresh that loses most of the town's roads is far more likely to be a
# truncated response than a real deletion, so it is refused rather than applied.
SHRINK_REFUSAL_RATIO = 0.7


def refresh_day_of_month(township_name: str) -> int:
    """A stable day in 1..28, derived from the town's name.

    Every deployment refreshing on the 1st would put all of them on the
    publisher's doorstep at the same moment. Hashing the name spreads them out
    while keeping each town's own day predictable. Capped at 28 so February
    behaves.
    """
    digest = hashlib.sha256((township_name or "pinpoint").encode("utf-8")).digest()
    return (digest[0] % 28) + 1


def should_swap(existing_count: int, incoming_count: int) -> Tuple[bool, Optional[str]]:
    """Is this fetch safe to apply over what the town already has?

    An empty or drastically smaller result is nearly always a truncated or
    erroring response. Refusing keeps the previous roads in place, which is the
    difference between "slightly stale" and "road routing silently switched off
    for the whole town".
    """
    if incoming_count == 0:
        return False, "fetch returned no roads; keeping existing data"
    if existing_count and incoming_count < existing_count * SHRINK_REFUSAL_RATIO:
        return False, (
            f"fetch returned {incoming_count} roads against {existing_count} existing "
            f"({incoming_count / existing_count:.0%}); refusing to swap"
        )
    return True, None


def boundary_bbox(geojson: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
    """(minx, miny, maxx, maxy) of a boundary, for the fetch envelope."""
    coordinates: List[List[float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, (list, tuple)):
            if len(node) == 2 and all(isinstance(v, (int, float)) for v in node):
                coordinates.append([float(node[0]), float(node[1])])
            else:
                for child in node:
                    walk(child)

    geometry = (geojson or {}).get("geometry", geojson) or {}
    walk(geometry.get("coordinates"))
    if not coordinates:
        return None
    xs = [c[0] for c in coordinates]
    ys = [c[1] for c in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


async def _load_boundary_and_state(db) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    from app.models import SystemSettings

    row = (await db.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    if not row:
        return None, None, "pinpoint"
    settings_boundary = getattr(row, "township_boundary", None)
    state_code = getattr(row, "state_code", None) or getattr(row, "state", None)
    return settings_boundary, state_code, getattr(row, "township_name", "pinpoint") or "pinpoint"


async def seed_roads_for_boundary(db, *, force: bool = False) -> Dict[str, Any]:
    """Fetch and store every road inside the town boundary.

    Returns a summary dict rather than raising, so a caller wiring this into
    setup can show progress without having to catch. Every failure path leaves
    the existing roads intact.
    """
    boundary, state_code, township = await _load_boundary_and_state(db)
    status = (await db.execute(select(RoadDataStatus).limit(1))).scalar_one_or_none()
    if status is None:
        status = RoadDataStatus()
        db.add(status)

    if not boundary:
        return {"ok": False, "reason": "no township boundary configured"}

    bbox = boundary_bbox(boundary)
    if not bbox:
        return {"ok": False, "reason": "township boundary has no coordinates"}

    entry = resolve_source(state_code)
    status.state_code = (state_code or "")[:2] or None
    status.source_name = entry.get("name")
    status.endpoint = entry.get("url")
    status.source_id = entry.get("schema")

    # One cheap metadata call: if the publisher has not edited the layer since
    # our last import there is nothing to download. This is also what makes
    # "the source published something new" distinguishable from "we re-fetched".
    if not force:
        last_edit = await fetch_source_updated_at(entry)
        if last_edit and status.source_updated_at:
            published = datetime.fromtimestamp(last_edit / 1000, tz=timezone.utc)
            if published <= status.source_updated_at:
                status.fetched_at = datetime.now(timezone.utc)
                await db.commit()
                return {"ok": True, "skipped": "source unchanged since last import"}

    try:
        result = await fetch_segments(entry, bbox)
    except Exception as exc:
        status.consecutive_failures = (status.consecutive_failures or 0) + 1
        status.last_error = str(exc)[:500]
        await db.commit()
        logger.warning("road fetch failed for %s: %s", entry.get("name"), exc)
        await _report(db, township, changes=None, status=status)
        return {"ok": False, "reason": str(exc), "failures": status.consecutive_failures}

    existing = (await db.execute(select(func.count(RoadSegment.id)))).scalar() or 0
    # Snapshot before the swap: the digest diffs names, and after the delete
    # there is nothing left to compare against.
    previous_names = [
        row[0] for row in (await db.execute(select(RoadSegment.name))).all()
    ]

    ok, refusal = should_swap(existing, len(result.segments))
    if not ok:
        status.consecutive_failures = (status.consecutive_failures or 0) + 1
        status.last_error = refusal
        await db.commit()
        logger.warning("refusing road swap: %s", refusal)
        await _report(
            db, township,
            changes=diff_road_names(previous_names, [s.name for s in result.segments]),
            status=status,
        )
        return {"ok": False, "reason": refusal}

    # Swap. Deleting and reinserting inside one transaction means a failure
    # rolls back to the previous roads rather than leaving the table half-built.
    await db.execute(delete(RoadSegment))
    for segment in result.segments:
        wkt = "LINESTRING(" + ",".join(f"{x} {y}" for x, y in segment.coordinates) + ")"
        db.add(RoadSegment(
            source_id=result.source_id,
            source_feature_id=segment.source_feature_id,
            name=segment.name,
            name_norm=segment.name_norm or None,
            ref=segment.ref,
            ref_norm=segment.ref_norm or None,
            highway_class=segment.highway_class,
            geom=func.ST_GeomFromText(wkt, 4326),
        ))

    status.segment_count = len(result.segments)
    status.fetched_at = datetime.now(timezone.utc)
    status.consecutive_failures = 0
    status.last_error = None
    if result.source_updated_at:
        status.source_updated_at = result.source_updated_at
    await db.commit()

    await _report(
        db, township,
        changes=diff_road_names(previous_names, [s.name for s in result.segments]),
        status=status,
    )

    logger.info("seeded %s roads for %s from %s", len(result.segments), township, result.source_name)
    return {
        "ok": True,
        "segments": len(result.segments),
        "source": result.source_name,
        "truncated": result.truncated,
    }


@celery_app.task(name="app.tasks.road_data.seed_roads", time_limit=900, soft_time_limit=840)
def seed_roads(force: bool = False) -> Dict[str, Any]:
    """Triggered when a boundary is saved, and by the admin refresh button.

    Its own time limit: the global 300 s would kill a large township's fetch
    partway. Safe to kill regardless -- nothing is written until the swap.
    """
    import asyncio

    from app.db.session import SessionLocal

    async def run() -> Dict[str, Any]:
        async with SessionLocal() as db:
            return await seed_roads_for_boundary(db, force=force)

    return asyncio.run(run())


@celery_app.task(name="app.tasks.road_data.refresh_roads_monthly", time_limit=900, soft_time_limit=840)
def refresh_roads_monthly() -> Dict[str, Any]:
    """Runs daily, acts on one day a month -- the town's hashed day.

    Beat schedules here are intervals, not wall-clock crontabs, so the day check
    lives in the task rather than the schedule.
    """
    import asyncio

    from app.db.session import SessionLocal

    async def run() -> Dict[str, Any]:
        async with SessionLocal() as db:
            _, _, township = await _load_boundary_and_state(db)
            today = datetime.now(timezone.utc).day
            if today != refresh_day_of_month(township):
                return {"ok": True, "skipped": f"not this town's refresh day ({today})"}
            return await seed_roads_for_boundary(db)

    return asyncio.run(run())


async def _report(db, township: str, *, changes, status) -> None:
    """Email admins, but only when there is a decision to make or something is
    broken. Never raises -- a failure to send must not roll back a good refresh.

    A rule whose road has vanished is checked here rather than in the alert
    module because it needs the service configs, which only the caller has.
    """
    try:
        from sqlalchemy import select as _select

        from app.models import ServiceDefinition, User
        from app.services.notifications import notification_service
        from app.tasks.service_requests import configure_notifications

        names = [row[0] for row in (await db.execute(_select(RoadSegment.name))).all()]
        configs = [
            row[0] for row in (
                await db.execute(_select(ServiceDefinition.routing_config))
            ).all() if row[0]
        ]
        newly_broken = broken_rules(configured_roads(configs), names)

        alerts = build_alerts(
            changes=changes,
            consecutive_failures=status.consecutive_failures or 0,
            last_error=status.last_error,
            newly_broken_rules=newly_broken,
            township=township,
        )
        if not alerts:
            return

        admins = [
            a for a in (
                await db.execute(
                    _select(User).where(User.role == "admin", User.is_active.is_(True))
                )
            ).scalars().all() if a.email
        ]
        if not admins:
            logger.info("road alerts raised but no admin has an email address")
            return

        await configure_notifications(db)
        for alert in alerts:
            for admin in admins:
                try:
                    notification_service.send_email(
                        to=admin.email,
                        subject=alert.subject,
                        body_html=f"<p>{alert.body}</p>".replace("\n\n", "</p><p>"),
                    )
                except Exception as exc:
                    logger.warning("could not email road alert to %s: %s", admin.email, exc)
    except Exception as exc:
        logger.warning("road alert reporting failed: %s", exc)
