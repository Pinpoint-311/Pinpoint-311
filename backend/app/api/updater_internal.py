"""The host updater's channel: /api/internal/updater/*.

Implements the contract in updater/pinpoint_updater/request_source.py
(``HttpRequestSource``):

* ``GET  /requests``             approved requests that are due, oldest first
* ``POST /requests/{id}/claim``  exactly one claim wins (409 for the others)
* ``POST /requests/{id}/steps``  one StepResult
* ``POST /requests/{id}/heartbeat`` still working (renews the lease only)
* ``POST /requests/{id}/outcome`` the RunOutcome; sets the final status
* ``PUT  /releases``             the normalised, verified release list

Who can reach it: only a caller presenting a live updater token (bearer,
hashed at rest, constant-time compare). Three more fences, because the token
is the only credential the updater has:

* Caddy answers 404 for ``/api/internal/*`` from the internet (Caddyfile,
  ``pinpoint_site``); the updater talks to the backend's loopback port.
* A request that arrived through a reverse proxy (it carries
  X-Forwarded-For / Forwarded / X-Real-IP / Via) is answered 404 here too, so
  an edited or regenerated Caddyfile does not reopen the prefix.
* In managed mode the orchestrator runs upgrades; every route here is 404.

None of these routes can start anything. The worst a stolen token does is
claim this instance's approved requests (so they do not run) or post a
misleading report, and it is revoked from the console.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.services import upgrades as U

logger = logging.getLogger(__name__)

router = APIRouter()

_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "via", "x-forwarded-host", "x-forwarded-proto")


async def require_updater_token(
    request: Request,
    authorization: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    """Bearer updater token, or 404/401. Records that the updater checked in."""
    from app.core.config import get_settings

    if get_settings().managed_mode:
        raise HTTPException(status_code=404, detail="Not Found")
    if any(h in request.headers for h in _PROXY_HEADERS):
        # Present at all, even empty: a proxy that blanks the value still
        # marks the request as having come through it.
        # Came through Caddy (or some other proxy): the internet side. The
        # updater talks to the backend directly over loopback.
        raise HTTPException(status_code=404, detail="Not Found")
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not presented.strip():
        raise HTTPException(status_code=401, detail="Updater token required",
                            headers={"WWW-Authenticate": "Bearer"})
    token = await U.authenticate(db, presented.strip())
    if token is None:
        logger.warning("[Updater] refused a call with an unknown or revoked token (prefix %s)",
                       presented.strip()[: U.PREFIX_LENGTH].replace("\n", " "))
        raise HTTPException(status_code=401, detail="Invalid or revoked updater token",
                            headers={"WWW-Authenticate": "Bearer"})
    now = U.now_utc()
    token.last_used_at = now
    settings = await U.settings_row(db, create=True)
    settings.updater_last_seen_at = now
    agent = (request.headers.get("user-agent") or "")
    if agent.startswith("pinpoint-updater/"):
        settings.updater_version = agent.split("/", 1)[1][:32]
    await db.commit()
    return token


def _updater_actor(token) -> str:
    return f"updater:{token.token_prefix}"


async def _audit(db, event_type: str, token, *, success: bool = True, details: Optional[Dict[str, Any]] = None,
                 failure_reason: Optional[str] = None) -> None:
    try:
        from app.services.audit_service import AuditService

        await AuditService.log_event(db, event_type=event_type, success=success, username=_updater_actor(token),
                                     failure_reason=failure_reason, details=details or {})
    except Exception as exc:  # never fail the updater's report over the audit write
        logger.warning("[Updater] could not audit %s: %s", event_type, exc)


def _due():
    from app.models import UpgradeRequest

    return or_(UpgradeRequest.scheduled_for.is_(None), UpgradeRequest.scheduled_for <= U.now_utc())


def _email_expired(background: BackgroundTasks, ids) -> None:
    for rid in ids:
        background.add_task(U.notify_admins, "finished", rid)


@router.get("/requests")
async def pending_requests(background: BackgroundTasks, db: AsyncSession = Depends(get_db),
                           token=Depends(require_updater_token)):
    """Approved requests whose time has come, oldest first, in the shape the
    updater's ``UpgradeRequest`` takes."""
    from app.models import UpgradeRequest

    _email_expired(background, await U.expire_stale(db))

    two_person = await U.two_person_required(db)
    rows = (await db.execute(
        select(UpgradeRequest).where(UpgradeRequest.status == U.APPROVED, _due()).order_by(UpgradeRequest.id)
    )).scalars().all()
    out = []
    for r in rows:
        if await _refuse_if_actor_gone(db, r, token, background):
            continue
        approvals = [r.approved_by] if r.approved_by else []
        out.append({
            "id": str(r.id),
            "action": r.action,
            "tag": r.target_tag,
            "requested_by": r.requested_by,
            "reason": r.reason,
            "approvals": approvals,
            "allow_destructive": bool(r.allow_destructive),
            # Restarts are a one-admin action by design (see services/upgrades.py).
            "policy": "two_person" if (two_person and r.action != "restart") else "single",
            "scheduled_for": U.iso(r.scheduled_for),
        })
    return {"requests": out, "require_two_person_approval": two_person}


async def _refuse_if_actor_gone(db, req, token, background: BackgroundTasks) -> bool:
    """Refuse an approved request whose requester or approver has since been
    removed, deactivated or demoted (services/upgrades.actor_refusal). True
    when it was refused (or someone else moved it on first)."""
    from app.models import UpgradeRequest

    why = await U.actor_refusal(db, req)
    if why is None:
        return False
    summary = f"Not run: {why}. File a new request if it is still wanted."
    result = await db.execute(
        update(UpgradeRequest).where(UpgradeRequest.id == req.id, UpgradeRequest.status == U.APPROVED)
        .values(status=U.REFUSED, outcome=U.ACTOR_REVOKED, outcome_summary=U.clip(summary, U.MAX_SUMMARY),
                finished_at=U.now_utc())
        .execution_options(synchronize_session=False))
    await db.commit()
    if result.rowcount == 1:
        logger.warning("[Updater] request %s refused: %s", req.id, why)
        await _audit(db, "upgrade_request_refused", token, success=False, failure_reason=why[:255],
                     details={"request_id": req.id, "action": req.action, "target_tag": req.target_tag,
                              "outcome": U.ACTOR_REVOKED})
        background.add_task(U.notify_admins, "finished", req.id)
    return True


def _request_id(raw: str) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="No such request")
    if value < 1:
        raise HTTPException(status_code=404, detail="No such request")
    return value


@router.post("/requests/{request_id}/claim")
async def claim_request(request_id: str, background: BackgroundTasks, db: AsyncSession = Depends(get_db),
                        token=Depends(require_updater_token)):
    """Take an approved, due request. One conditional UPDATE: under concurrency
    exactly one caller sees a row change; everyone else gets 409."""
    from app.models import UpgradeRequest

    rid = _request_id(request_id)
    pending = await db.get(UpgradeRequest, rid)
    if pending is not None and pending.status == U.APPROVED and await _refuse_if_actor_gone(db, pending, token, background):
        raise HTTPException(status_code=409, detail=f"Request {rid} was refused: its requester or approver is no "
                                                    "longer an active admin")
    now = U.now_utc()
    result = await db.execute(
        update(UpgradeRequest)
        .where(UpgradeRequest.id == rid, UpgradeRequest.status == U.APPROVED, _due())
        .values(status=U.CLAIMED, claimed_at=now, last_report_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        await db.rollback()
        req = await db.get(UpgradeRequest, rid)
        if req is None:
            raise HTTPException(status_code=404, detail="No such request")
        raise HTTPException(status_code=409, detail=f"Request {rid} is {req.status}, not claimable")
    await db.commit()
    req = await db.get(UpgradeRequest, rid)
    await _audit(db, "upgrade_request_claimed", token,
                 details={"request_id": rid, "action": req.action, "target_tag": req.target_tag})
    return {"claimed": True, "id": str(rid)}


class StepReport(BaseModel):
    # The updater's StepResult (updater/pinpoint_updater/models.py). Extra keys
    # (data, duration) are accepted and not stored: data can carry whole
    # release descriptions and is already in the updater's own JSONL log.
    name: str = Field(..., min_length=1, max_length=64)
    status: str = Field(..., min_length=1, max_length=24)
    detail: Optional[str] = ""
    at: Optional[str] = None

    model_config = {"extra": "ignore"}


async def _in_flight(db, rid: int, background: BackgroundTasks, token, *, audit_late: bool = True):
    """The request, if it is still the updater's to report on. A lease that ran
    out is applied first, so a late report from a revived updater is refused
    (409) and logged, never applied over the failure admins were told about."""
    from app.models import UpgradeRequest

    _email_expired(background, await U.expire_stale(db, request_id=rid))
    req = await db.get(UpgradeRequest, rid)
    if req is None:
        raise HTTPException(status_code=404, detail="No such request")
    if req.status not in U.IN_FLIGHT:
        if req.outcome in (U.LEASE_EXPIRED, U.MARKED_FAILED):
            logger.warning("[Updater] refused a late report for request %s (%s; token %s)",
                           rid, req.outcome, token.token_prefix)
            if audit_late:
                    await _audit(db, "upgrade_request_late_report", token, success=False,
                             failure_reason=f"request already {req.outcome}",
                             details={"request_id": rid, "outcome": req.outcome})
            raise HTTPException(status_code=409, detail=(
                f"Request {rid} was marked failed ({req.outcome.replace('_', ' ')}); this report was not applied."))
        raise HTTPException(status_code=409, detail=f"Request {rid} is {req.status}; claim it first")
    return req


@router.post("/requests/{request_id}/steps")
async def report_step(request_id: str, body: StepReport, background: BackgroundTasks,
                      db: AsyncSession = Depends(get_db), token=Depends(require_updater_token)):
    """Record one step the updater finished; the first moves the request to running."""
    from app.models import UpgradeRequestStep

    rid = _request_id(request_id)
    await _in_flight(db, rid, background, token)
    # Conditional on still being in flight: a lease expiry or "mark failed"
    # that lands after the check above must not be turned back into running.
    await _renew(db, rid, status=U.RUNNING)
    db.add(UpgradeRequestStep(request_id=rid, step=body.name, status=body.status,
                              detail=U.clip(body.detail, U.MAX_DETAIL), at=U.parse_time(body.at) or U.now_utc()))
    await db.commit()
    return {"ok": True, "status": U.RUNNING}


@router.post("/requests/{request_id}/heartbeat")
async def heartbeat(request_id: str, background: BackgroundTasks, db: AsyncSession = Depends(get_db),
                    token=Depends(require_updater_token)):
    """The updater is still working on a long step: renew the lease. No step row
    and no audit entry, so the step log and the audit trail stay readable. 409
    if the request already finished or its lease ran out."""
    rid = _request_id(request_id)
    # Not audited when refused either: a revived updater beats every minute.
    req = await _in_flight(db, rid, background, token, audit_late=False)
    status = req.status
    await _renew(db, rid)
    await db.commit()
    return {"ok": True, "status": status}


async def _renew(db, rid: int, **values) -> None:
    """Record a report on an in-flight request: one conditional UPDATE, 409
    if the request stopped being in flight since _in_flight looked."""
    from app.models import UpgradeRequest

    result = await db.execute(
        update(UpgradeRequest).where(UpgradeRequest.id == rid, UpgradeRequest.status.in_(U.IN_FLIGHT))
        .values(last_report_at=U.now_utc(), **values)
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"Request {rid} finished while this report was in transit; "
                                                    "it was not applied.")


class OutcomeReport(BaseModel):
    outcome: str = Field(..., min_length=1, max_length=32)
    summary: Optional[str] = ""
    finished_at: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None

    model_config = {"extra": "ignore"}


@router.post("/requests/{request_id}/outcome")
async def report_outcome(request_id: str, body: OutcomeReport, background: BackgroundTasks,
                         db: AsyncSession = Depends(get_db), token=Depends(require_updater_token)):
    """Record how the run ended; sets the final status, audits it and emails admins."""
    rid = _request_id(request_id)
    req = await _in_flight(db, rid, background, token)
    await _renew(db, rid, status=U.status_for_outcome(body.outcome), outcome=body.outcome[:32],
                 outcome_summary=U.clip(body.summary, U.MAX_SUMMARY),
                 finished_at=U.parse_time(body.finished_at) or U.now_utc())
    await db.commit()
    await db.refresh(req)
    await _audit(db, "upgrade_request_finished", token, success=req.status == U.SUCCEEDED,
                 failure_reason=None if req.status == U.SUCCEEDED else (req.outcome_summary or req.status)[:255],
                 details={"request_id": rid, "action": req.action, "target_tag": req.target_tag,
                          "status": req.status, "outcome": req.outcome})
    background.add_task(U.notify_admins, "needs_approval" if req.status == U.NEEDS_APPROVAL else "finished", rid)
    return {"ok": True, "status": req.status}


class ReleaseReport(BaseModel):
    # The updater's own tag grammar (pinpoint_updater.config.TAG_RE). The tag
    # reaches email subjects and the audit log, so nothing else is accepted.
    tag: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
    version: Optional[str] = None
    name: Optional[str] = None
    published_at: Optional[str] = None
    notes: Optional[str] = None
    url: Optional[str] = None
    prerelease: bool = False
    signature_verified: Optional[bool] = None
    gate_passed: Optional[bool] = None
    attested: Optional[bool] = None
    db_revision: Optional[str] = None
    min_db_revision: Optional[str] = None
    compatible: Optional[bool] = None
    compatibility: Optional[str] = None
    backend_digest: Optional[str] = None
    frontend_digest: Optional[str] = None

    model_config = {"extra": "ignore"}


class ReleasesReport(BaseModel):
    releases: List[ReleaseReport] = Field(default_factory=list, max_length=100)
    # What release.lock says this instance runs: {version, backend, frontend}.
    current: Optional[Dict[str, Any]] = None


@router.put("/releases")
async def publish_releases(body: ReleasesReport, db: AsyncSession = Depends(get_db),
                           token=Depends(require_updater_token)):
    """Replace the stored release list with what the updater verified now."""
    from app.models import UpdaterRelease

    now = U.now_utc()
    await db.execute(delete(UpdaterRelease))
    seen = set()
    for r in body.releases:
        if r.tag in seen:
            continue
        seen.add(r.tag)
        db.add(UpdaterRelease(
            tag=r.tag, version=U.clip(r.version, 64), name=U.clip(r.name, 200),
            published_at=U.parse_time(r.published_at), notes=U.clip(r.notes, 20000),
            url=(r.url or None) if (r.url or "").startswith("https://") else None,
            prerelease=bool(r.prerelease), signature_verified=r.signature_verified, gate_passed=r.gate_passed,
            attested=r.attested, db_revision=U.clip(r.db_revision, 64), min_db_revision=U.clip(r.min_db_revision, 64),
            compatible_with_this_instance=r.compatible, compatibility_detail=U.clip(r.compatibility, 1000),
            backend_digest=U.clip(r.backend_digest, 80), frontend_digest=U.clip(r.frontend_digest, 80),
            reported_at=now,
        ))
    settings = await U.settings_row(db, create=True)
    if body.current is not None:
        settings.current_report = {k: U.clip(body.current.get(k), 300) for k in ("version", "backend", "frontend")
                                   if body.current.get(k)}
    await db.commit()
    return {"ok": True, "stored": len(seen)}
