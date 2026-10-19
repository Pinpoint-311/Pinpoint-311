"""Request, approve and observe upgrades: the console half of Phase 3.

Mounted at /api/system (docs/design/secure-upgrades.md section 4). Admin only.
The app records and audits; the host updater executes (app/api/
updater_internal.py is its side of the channel). Nothing here runs git,
docker or any other process.

  GET  /releases                       what the updater last reported, with badges
  GET  /upgrade-requests               history and the active request
  GET  /upgrade-requests/{id}          one request with its step log
  POST /upgrade-requests               upgrade | rollback | restart
  POST /upgrade-requests/{id}/approve  a different admin while two-person approval is on
  POST /upgrade-requests/{id}/cancel   before the updater claims it
  POST /upgrade-requests/{id}/fail     mark an in-flight request failed (the updater is gone)
  GET  /upgrade-settings, PUT /upgrade-settings
  GET  /updater-tokens, POST /updater-tokens, POST /updater-tokens/{id}/revoke

Managed (state-hosted) mode: every write here is refused. Upgrades there come
from the orchestrator, and the panel stays read-only.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin
from app.db.session import get_db
from app.services import upgrades as U
from app.services.admin_audit import record_admin_action

logger = logging.getLogger(__name__)

router = APIRouter()


def _not_managed() -> None:
    from app.core.managed import ensure_not_managed

    ensure_not_managed("Upgrading")


async def _running_version() -> Optional[str]:
    from app.core.config import get_settings

    return get_settings().app_version


# ---------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------

@router.get("/releases")
async def list_releases(db: AsyncSession = Depends(get_db), _=Depends(get_current_admin)):
    """Releases the updater last reported, newest first, with signature, gate,
    attestation and schema-compatibility badges. The app never calls GitHub or
    GitLab itself."""
    from app.models import UpdaterRelease

    rows = (await db.execute(select(UpdaterRelease))).scalars().all()
    rows.sort(key=lambda r: (U.aware(r.published_at) or U.aware(r.reported_at) or U.now_utc()), reverse=True)
    running = await _running_version()
    live = await U.live_db_revision(db)
    releases = []
    for r in rows:
        d = U.release_dict(r)
        refusal = U.release_refusal(r, live_revision=live, running_version=running)
        d["requestable"] = refusal is None
        d["refusal"] = refusal
        d["current"] = bool(running) and U._norm_version(running) in {U._norm_version(r.tag), U._norm_version(r.version)}
        releases.append(d)
    return {"releases": releases, "updater": await U.updater_state(db), "db_revision": live}


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class UpgradeRequestCreate(BaseModel):
    action: Literal["upgrade", "rollback", "restart"] = "upgrade"
    target_tag: Optional[str] = Field(None, max_length=128)
    reason: str = Field(..., min_length=1, max_length=2000)
    scheduled_for: Optional[datetime] = None
    allow_destructive: bool = False

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Say why, in a few words: the reason goes to every admin and the audit log.")
        return v


async def _expire(db, background: BackgroundTasks) -> None:
    """Apply the lease before answering, so nobody reads "running" for a job
    whose updater has gone quiet."""
    for rid in await U.expire_stale(db):
        background.add_task(U.notify_admins, "finished", rid)


@router.get("/upgrade-requests")
async def list_upgrade_requests(background: BackgroundTasks, limit: int = 50, db: AsyncSession = Depends(get_db),
                                user=Depends(get_current_admin)):
    """History, newest first, with whether the caller may approve or cancel each."""
    from app.models import UpgradeRequest

    await _expire(db, background)
    limit = max(1, min(limit, 200))
    two_person = await U.two_person_required(db)
    rows = (await db.execute(select(UpgradeRequest).order_by(UpgradeRequest.id.desc()).limit(limit))).scalars().all()
    return {
        "requests": [U.request_dict(r, user=user, two_person=two_person) for r in rows],
        "updater": await U.updater_state(db),
        "require_two_person_approval": two_person,
    }


async def _load(db, request_id: int):
    from app.models import UpgradeRequest

    req = await db.get(UpgradeRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="No such upgrade request")
    return req


async def _steps(db, request_id: int):
    from app.models import UpgradeRequestStep

    return (await db.execute(
        select(UpgradeRequestStep).where(UpgradeRequestStep.request_id == request_id).order_by(UpgradeRequestStep.id)
    )).scalars().all()


@router.get("/upgrade-requests/{request_id}")
async def get_upgrade_request(request_id: int, background: BackgroundTasks, db: AsyncSession = Depends(get_db),
                              user=Depends(get_current_admin)):
    """One request and every step the updater reported for it."""
    await _expire(db, background)
    req = await _load(db, request_id)
    two_person = await U.two_person_required(db)
    return U.request_dict(req, user=user, two_person=two_person, steps=await _steps(db, request_id))


async def _refuse(db, user, body: UpgradeRequestCreate, status_code: int, reason: str):
    await record_admin_action(db, event_type="upgrade_request_refused", actor=user, success=False,
                              failure_reason=reason[:255],
                              details={"action": body.action, "target_tag": body.target_tag})
    raise HTTPException(status_code=status_code, detail=reason)


@router.post("/upgrade-requests", status_code=201)
async def create_upgrade_request(body: UpgradeRequestCreate, background: BackgroundTasks,
                                 db: AsyncSession = Depends(get_db), user=Depends(get_current_admin)):
    """File an upgrade, rollback or restart for the host updater to run.

    An upgrade must name a release the updater reported as signature-verified
    and schema-compatible. Upgrades and rollbacks need a second admin while
    two-person approval is on; restarts need one admin.
    """
    from app.models import UpdaterRelease, UpgradeRequest

    _not_managed()
    state = await U.updater_state(db)
    if not state["connected"]:
        await _refuse(db, user, body, 409, "No updater has checked in from this server yet, so nothing could run "
                                           "this request. Install and connect the updater first (see docs/RELEASES.md).")
    now = U.now_utc()
    scheduled = U.aware(body.scheduled_for)
    if scheduled is not None and scheduled <= now:
        await _refuse(db, user, body, 422, "The scheduled time is in the past. Leave it empty to run on the "
                                           "updater's next check.")

    tag = (body.target_tag or "").strip() or None
    if body.action == "upgrade":
        if not tag:
            await _refuse(db, user, body, 422, "Choose a release to upgrade to.")
        release = (await db.execute(select(UpdaterRelease).where(UpdaterRelease.tag == tag))).scalar_one_or_none()
        refusal = U.release_refusal(release, live_revision=await U.live_db_revision(db),
                                    running_version=await _running_version())
        if refusal:
            await _refuse(db, user, body, 422, refusal)
    else:
        tag = None
        if body.allow_destructive:
            await _refuse(db, user, body, 422, "Only an upgrade can carry a destructive migration.")

    # One change at a time. A restart may wait behind a pending upgrade's
    # approval, but never runs alongside something the updater is executing.
    active = (await db.execute(select(UpgradeRequest).where(UpgradeRequest.status.in_(U.ACTIVE)))).scalars().all()
    for other in active:
        clash = (other.status in U.IN_FLIGHT
                 or (body.action == "restart") == (other.action == "restart"))
        if clash:
            await _refuse(db, user, body, 409, f"Request #{other.id} ({U.describe(other)}) is {other.status.replace('_', ' ')}. "
                                               "Wait for it to finish or cancel it first.")

    two_person = await U.two_person_required(db)
    needs_second = two_person and body.action != "restart"
    who = U.actor_name(user)
    req = UpgradeRequest(
        action=body.action, target_tag=tag, reason=body.reason, requested_by=who, requested_by_id=user.id,
        requested_at=now, scheduled_for=scheduled, allow_destructive=bool(body.allow_destructive),
        status=U.PENDING_APPROVAL if needs_second else U.APPROVED,
    )
    if not needs_second:
        req.approved_by, req.approved_by_id, req.approved_at = who, user.id, now
    db.add(req)
    await db.commit()
    await db.refresh(req)
    await record_admin_action(db, event_type="upgrade_request_created", actor=user, details={
        "request_id": req.id, "action": req.action, "target_tag": req.target_tag, "status": req.status,
        "scheduled_for": U.iso(req.scheduled_for), "allow_destructive": req.allow_destructive,
        "two_person_approval": needs_second,
    })
    background.add_task(U.notify_admins, "created", req.id)
    return U.request_dict(req, user=user, two_person=two_person, steps=[])


@router.post("/upgrade-requests/{request_id}/approve")
async def approve_upgrade_request(request_id: int, db: AsyncSession = Depends(get_db),
                                  user=Depends(get_current_admin)):
    """Approve a pending request. While two-person approval is on, the approver
    must be a different admin from the requester."""
    from sqlalchemy import update

    from app.models import UpgradeRequest

    _not_managed()
    req = await _load(db, request_id)
    two_person = await U.two_person_required(db)
    block = U.approval_block(req, user, two_person=two_person)
    status_code = 403 if req.status == U.PENDING_APPROVAL else 409
    if block is None:
        gone = await U.actor_refusal(db, req)
        if gone:
            block, status_code = f"This request cannot be approved: {gone}. File a new one.", 409
    if block:
        await record_admin_action(db, event_type="upgrade_request_approval_refused", actor=user, success=False,
                                  failure_reason=block[:255],
                                  details={"request_id": req.id, "action": req.action, "target_tag": req.target_tag})
        raise HTTPException(status_code=status_code, detail=block)
    # Conditional, like the claim: a cancel that lands between the read above
    # and this write must win, never be overwritten back to "approved".
    result = await db.execute(
        update(UpgradeRequest).where(UpgradeRequest.id == req.id, UpgradeRequest.status == U.PENDING_APPROVAL)
        .values(status=U.APPROVED, approved_by=U.actor_name(user), approved_by_id=user.id, approved_at=U.now_utc())
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()  # expires req: use the id from the path
        raise HTTPException(status_code=409, detail=f"Request #{request_id} changed while you were deciding. Refresh.")
    await db.commit()
    await db.refresh(req)
    await record_admin_action(db, event_type="upgrade_request_approved", actor=user, details={
        "request_id": req.id, "action": req.action, "target_tag": req.target_tag,
        "requested_by": req.requested_by, "two_person_approval": two_person,
    })
    return U.request_dict(req, user=user, two_person=two_person, steps=await _steps(db, req.id))


@router.post("/upgrade-requests/{request_id}/cancel")
async def cancel_upgrade_request(request_id: int, db: AsyncSession = Depends(get_db),
                                 user=Depends(get_current_admin)):
    """Cancel a request the updater has not claimed yet. Any admin may cancel:
    stopping a change never needs a second person."""
    from sqlalchemy import update

    from app.models import UpgradeRequest

    _not_managed()
    req = await _load(db, request_id)

    def _refused():
        return HTTPException(status_code=409, detail=(
            f"Request #{req.id} is {req.status.replace('_', ' ')}. "
            + ("The updater is already running it; it cannot be stopped from here."
               if req.status in U.IN_FLIGHT else "Only a request that has not started can be cancelled.")))

    if req.status not in U.CANCELLABLE:
        raise _refused()
    # Conditional: if the updater claimed it a moment ago, the claim stands
    # and the admin is told so. Writing "cancelled" over a claimed request
    # would show it stopped while the updater runs it.
    result = await db.execute(
        update(UpgradeRequest).where(UpgradeRequest.id == req.id, UpgradeRequest.status.in_(U.CANCELLABLE))
        .values(status=U.CANCELLED, cancelled_by=U.actor_name(user), finished_at=U.now_utc())
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()
        await db.refresh(req)
        raise _refused()
    await db.commit()
    await db.refresh(req)
    await record_admin_action(db, event_type="upgrade_request_cancelled", actor=user, details={
        "request_id": req.id, "action": req.action, "target_tag": req.target_tag,
    })
    two_person = await U.two_person_required(db)
    return U.request_dict(req, user=user, two_person=two_person, steps=await _steps(db, req.id))


class MarkFailed(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)


@router.post("/upgrade-requests/{request_id}/fail")
async def mark_upgrade_request_failed(request_id: int, background: BackgroundTasks, body: Optional[MarkFailed] = None,
                                      db: AsyncSession = Depends(get_db), user=Depends(get_current_admin)):
    """Mark a claimed or running request failed, when its updater has stopped
    and nobody wants to wait for the lease. A late report from that updater is
    then refused. It does not stop anything on the server: check it there."""
    from sqlalchemy import update

    from app.models import UpgradeRequest

    _not_managed()
    req = await _load(db, request_id)
    if req.status not in U.IN_FLIGHT:
        raise HTTPException(status_code=409, detail=f"Request #{req.id} is {req.status.replace('_', ' ')}, not in progress.")
    who = U.actor_name(user)
    note = (body.reason or "").strip() if body else ""
    summary = f"Marked failed by {who}" + (f": {note}" if note else "") + ". Check the server before retrying."
    result = await db.execute(
        update(UpgradeRequest).where(UpgradeRequest.id == req.id, UpgradeRequest.status.in_(U.IN_FLIGHT))
        .values(status=U.FAILED, outcome=U.MARKED_FAILED, outcome_summary=U.clip(summary, U.MAX_SUMMARY),
                finished_at=U.now_utc())
        .execution_options(synchronize_session=False))
    if result.rowcount != 1:
        await db.rollback()  # expires req: use the id from the path
        raise HTTPException(status_code=409, detail=f"Request #{request_id} finished while you were deciding.")
    await db.commit()
    await db.refresh(req)
    await record_admin_action(db, event_type="upgrade_request_marked_failed", actor=user, details={
        "request_id": req.id, "action": req.action, "target_tag": req.target_tag, "note": note or None,
    })
    background.add_task(U.notify_admins, "finished", req.id)
    two_person = await U.two_person_required(db)
    return U.request_dict(req, user=user, two_person=two_person, steps=await _steps(db, req.id))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

class UpgradeSettingsUpdate(BaseModel):
    require_two_person_approval: bool


@router.get("/upgrade-settings")
async def get_upgrade_settings(db: AsyncSession = Depends(get_db), _=Depends(get_current_admin)):
    """Two-person approval and what the updater last reported (admin)."""
    return await U.updater_state(db)


@router.put("/upgrade-settings")
async def update_upgrade_settings(body: UpgradeSettingsUpdate, background: BackgroundTasks,
                                  db: AsyncSession = Depends(get_db), user=Depends(get_current_admin)):
    """Turn two-person approval on or off. Audited; turning it off also emails
    every admin, because it is the change a compromised admin account would
    make first. Turning it back on is only audited."""
    _not_managed()
    row = await U.settings_row(db, create=True)
    old = bool(row.require_two_person_approval)
    row.require_two_person_approval = body.require_two_person_approval
    row.updated_by = U.actor_name(user)
    await db.commit()
    await record_admin_action(db, event_type="upgrade_settings_changed", actor=user, details={
        "require_two_person_approval": body.require_two_person_approval, "previous": old,
    })
    if old and not body.require_two_person_approval:
        background.add_task(U.notify_admins, "two_person_disabled", None, U.actor_name(user))
    return await U.updater_state(db)


# ---------------------------------------------------------------------------
# Updater tokens
# ---------------------------------------------------------------------------

class UpdaterTokenCreate(BaseModel):
    label: Optional[str] = Field(None, max_length=100)


def _token_dict(t) -> dict:
    return {
        "id": t.id, "label": t.label, "token_prefix": t.token_prefix, "created_by": t.created_by,
        "created_at": U.iso(t.created_at), "last_used_at": U.iso(t.last_used_at),
        "revoked_at": U.iso(t.revoked_at), "revoked_by": t.revoked_by,
        "status": "revoked" if t.revoked_at else "active",
    }


@router.get("/updater-tokens")
async def list_updater_tokens(db: AsyncSession = Depends(get_db), _=Depends(get_current_admin)):
    """Updater tokens: prefix, label and use, never the token (admin)."""
    from app.models import UpdaterToken

    rows = (await db.execute(select(UpdaterToken).order_by(UpdaterToken.id.desc()))).scalars().all()
    return {"tokens": [_token_dict(t) for t in rows], "updater": await U.updater_state(db)}


@router.post("/updater-tokens", status_code=201)
async def create_updater_token(body: UpdaterTokenCreate, db: AsyncSession = Depends(get_db),
                               user=Depends(get_current_admin)):
    """Mint a token for the host updater. The plaintext is in this response
    only; it is stored as a SHA-256 hash."""
    from app.models import UpdaterToken

    _not_managed()
    plaintext, prefix, digest = U.generate_token()
    row = UpdaterToken(label=(body.label or "").strip() or None, token_prefix=prefix, token_hash=digest,
                       created_by=U.actor_name(user), created_at=U.now_utc())
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await record_admin_action(db, event_type="updater_token_created", actor=user,
                              details={"updater_id": row.id, "prefix": prefix, "label": row.label})
    return {**_token_dict(row), "token": plaintext}


@router.post("/updater-tokens/{token_id}/revoke")
async def revoke_updater_token(token_id: int, db: AsyncSession = Depends(get_db), user=Depends(get_current_admin)):
    """Revoke an updater token; the updater is refused from its next call (admin)."""
    from app.models import UpdaterToken

    _not_managed()
    row = await db.get(UpdaterToken, token_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such updater token")
    if row.revoked_at is None:
        row.revoked_at = U.now_utc()
        row.revoked_by = U.actor_name(user)
        await db.commit()
        await record_admin_action(db, event_type="updater_token_revoked", actor=user,
                                  details={"updater_id": row.id, "prefix": row.token_prefix, "label": row.label})
    return _token_dict(row)
