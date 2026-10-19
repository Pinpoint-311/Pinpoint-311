"""Upgrade requests, the host updater's token, and the release list it reports.

Phase 3 of docs/design/secure-upgrades.md. The internet-facing app only
*records* what admins ask for. The host updater (updater/, a systemd service
with no listening port) polls /api/internal/updater/* over loopback with the
token minted here, claims approved requests, runs them against this
instance's own compose project, and reports each step and the outcome back.

Rules that live here so the admin routes, the internal routes and the tests
share one copy:

* Tokens: 32 random bytes, only a SHA-256 hash and a display prefix stored,
  compared with ``hmac.compare_digest`` (same reasoning as open311_keys).
* Approval: an upgrade or rollback needs a second admin while
  ``require_two_person_approval`` is on (the default). A restart needs one
  admin: it changes no code and no schema, it is the lever people reach for
  during an incident, and it was a single-admin action before this phase.
* A request can only name a release the updater reported as signature-verified
  and compatible with this instance's schema.
* Claims are a single conditional UPDATE, so exactly one claim wins.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select, text

logger = logging.getLogger(__name__)

ACTIONS = ("upgrade", "rollback", "restart")

PENDING_APPROVAL = "pending_approval"
APPROVED = "approved"
CLAIMED = "claimed"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
ROLLED_BACK = "rolled_back"
NEEDS_APPROVAL = "needs_approval"
CANCELLED = "cancelled"
REFUSED = "refused"

STATUSES = (PENDING_APPROVAL, APPROVED, CLAIMED, RUNNING, SUCCEEDED, FAILED, ROLLED_BACK,
            NEEDS_APPROVAL, CANCELLED, REFUSED)
ACTIVE = (PENDING_APPROVAL, APPROVED, CLAIMED, RUNNING)
IN_FLIGHT = (CLAIMED, RUNNING)
CANCELLABLE = (PENDING_APPROVAL, APPROVED)
TERMINAL = (SUCCEEDED, FAILED, ROLLED_BACK, NEEDS_APPROVAL, CANCELLED, REFUSED)

# The updater's RunOutcome.outcome words (updater/pinpoint_updater/models.py)
# mapped onto request statuses. Anything unknown is a failure: a status that
# claims success has to be earned.
_OUTCOME_STATUS = {
    "succeeded": SUCCEEDED,
    "noop": SUCCEEDED,
    "refused": REFUSED,
    "needs_approval": NEEDS_APPROVAL,
    "rolled_back": ROLLED_BACK,
    "migration_failed": FAILED,
    "rollback_failed": FAILED,
    "error": FAILED,
    "locked": FAILED,
    "not_confirmed": REFUSED,
}

TOKEN_MARKER = "ppu_"
PREFIX_LENGTH = 12  # "ppu_" + 8 characters

MAX_DETAIL = 4000
MAX_SUMMARY = 2000


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands datetimes back naive; every stored value is UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def iso(value: Optional[datetime]) -> Optional[str]:
    v = aware(value)
    return v.isoformat() if v else None


def status_for_outcome(outcome: Optional[str]) -> str:
    return _OUTCOME_STATUS.get((outcome or "").strip().lower(), FAILED)


def clip(value: Any, limit: int) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def generate_token() -> Tuple[str, str, str]:
    """(plaintext, prefix, sha256 hex). The plaintext is never persisted."""
    plaintext = TOKEN_MARKER + secrets.token_urlsafe(32)
    return plaintext, plaintext[:PREFIX_LENGTH], hash_token(plaintext)


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


async def authenticate(db, presented: Optional[str]):
    """The live updater token matching ``presented``, or None.

    Narrowed by prefix, then compared by hash in constant time. Every
    candidate is compared even after a match, so timing does not say which.
    """
    from app.models import UpdaterToken

    if not presented or not isinstance(presented, str):
        return None
    presented = presented.strip()
    if len(presented) < PREFIX_LENGTH or len(presented) > 128:
        return None
    wanted = hash_token(presented)
    rows = (await db.execute(
        select(UpdaterToken).where(UpdaterToken.token_prefix == presented[:PREFIX_LENGTH])
    )).scalars().all()
    match = None
    for row in rows:
        if hmac.compare_digest(str(row.token_hash or ""), wanted) and match is None:
            match = row
    if match is None or match.revoked_at is not None:
        return None
    return match


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

async def settings_row(db, *, create: bool = False):
    """The singleton row, or None (absent reads as the defaults)."""
    from app.models import UpdaterSettings

    row = (await db.execute(select(UpdaterSettings).order_by(UpdaterSettings.id).limit(1))).scalar_one_or_none()
    if row is None and create:
        row = UpdaterSettings(require_two_person_approval=True)
        db.add(row)
        await db.flush()
    return row


async def two_person_required(db) -> bool:
    """Fails closed: a read error answers "required"."""
    try:
        row = await settings_row(db)
    except Exception as exc:
        logger.error("updater settings read failed; treating two-person approval as on: %s", exc)
        return True
    return True if row is None else bool(row.require_two_person_approval)


async def updater_state(db) -> Dict[str, Any]:
    row = await settings_row(db)
    last_seen = aware(row.updater_last_seen_at) if row else None
    return {
        "connected": last_seen is not None,
        "last_seen_at": iso(last_seen),
        "version": row.updater_version if row else None,
        "current": (row.current_report or None) if row else None,
        "require_two_person_approval": True if row is None else bool(row.require_two_person_approval),
    }


async def live_db_revision(db) -> Optional[str]:
    # In a savepoint: a missing alembic_version table (a fresh database) must
    # not roll back, and so expire, everything else the caller has loaded.
    try:
        async with db.begin_nested():
            return (await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).scalar()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _norm_version(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    v = str(v).strip()
    return v[1:] if v[:1] in ("v", "V") and v[1:2].isdigit() else v


_SEMVER = re.compile(r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$")


def version_key(v: Optional[str]) -> Optional[tuple]:
    """Sortable key for a semantic version (``v1.9.0-rc3`` < ``1.9.0``), None
    for anything else. The updater's steps.version_key, kept in step."""
    m = _SEMVER.match(str(v or "").strip())
    if not m:
        return None
    major, minor, patch, pre = m.groups()
    pre_key: tuple = (1,) if pre is None else (
        0, tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in pre.split(".")))
    return (int(major), int(minor), int(patch), pre_key)


def is_downgrade(target: Optional[str], current: Optional[str]) -> bool:
    t, c = version_key(target), version_key(current)
    return t is not None and c is not None and t < c


def release_refusal(release, *, live_revision: Optional[str], running_version: Optional[str]) -> Optional[str]:
    """Why this reported release cannot be requested, or None when it can."""
    if release is None:
        return "That release is not in the list the updater last reported. Refresh, or wait for the updater's next check."
    if release.signature_verified is not True:
        return (f"{release.tag} has not been signature-verified by the updater, so it cannot be deployed."
                if release.signature_verified is None else
                f"{release.tag} failed signature verification. It cannot be deployed.")
    if release.compatible_with_this_instance is not True:
        detail = f" ({release.compatibility_detail})" if release.compatibility_detail else ""
        return f"{release.tag} is not compatible with this instance's database schema{detail}."
    if live_revision and release.min_db_revision and live_revision not in {release.min_db_revision, release.db_revision}:
        return (f"{release.tag} supports schema {release.min_db_revision}..{release.db_revision}, "
                f"but this database is at {live_revision}.")
    if running_version and _norm_version(running_version) in {_norm_version(release.tag), _norm_version(release.version)}:
        return f"This instance already runs {release.tag}."
    if running_version and is_downgrade(release.version or release.tag, running_version):
        # The updater refuses this too (engine: a console request cannot
        # downgrade). Going back is "Roll back", to the previous release only.
        return (f"{release.tag} is older than the running {running_version}. To go back, roll back to the "
                "previous release; an older release than that needs the server operator.")
    return None


def approval_block(req, user, *, two_person: bool) -> Optional[str]:
    """Why ``user`` may not approve ``req`` right now, or None."""
    if req.status != PENDING_APPROVAL:
        return f"This request is {req.status.replace('_', ' ')}, not waiting for approval."
    if two_person and _same_admin(req, user):
        return "You requested this. Two-person approval needs a different admin to approve it."
    return None


async def actor_refusal(db, req) -> Optional[str]:
    """Why ``req`` may no longer run because the admin who requested it, or
    the one who approved it, is no longer an active admin; None when both
    still are. A request outlives the account that filed it otherwise: an
    admin removed after a compromise could leave behind an approved or
    scheduled upgrade that still runs. Fails closed on an unknown account."""
    from app.models import User

    checks = [("requested", req.requested_by_id, req.requested_by)]
    if req.status != PENDING_APPROVAL:
        checks.append(("approved", req.approved_by_id, req.approved_by))
    for verb, uid, name in checks:
        if uid is None:
            return f"the admin who {verb} it cannot be identified"
        row = (await db.execute(select(User.role, User.is_active).where(User.id == uid))).first()
        if row is None or row.role != "admin" or not row.is_active:
            return f"{name or f'user {uid}'}, who {verb} it, is no longer an active admin"
    return None


def _same_admin(req, user) -> bool:
    if req.requested_by_id is not None and getattr(user, "id", None) is not None:
        return req.requested_by_id == user.id
    return (req.requested_by or "") == (getattr(user, "username", None) or "")


def actor_name(user) -> str:
    return (getattr(user, "username", None) or getattr(user, "email", None) or f"user-{getattr(user, 'id', '?')}")[:100]


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def request_dict(req, *, user=None, two_person: bool = True, steps: Optional[Iterable] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": req.id,
        "action": req.action,
        "target_tag": req.target_tag,
        "reason": req.reason,
        "requested_by": req.requested_by,
        "requested_at": iso(req.requested_at),
        "scheduled_for": iso(req.scheduled_for),
        "status": req.status,
        "approved_by": req.approved_by,
        "approved_at": iso(req.approved_at),
        "cancelled_by": req.cancelled_by,
        "claimed_at": iso(req.claimed_at),
        "last_report_at": iso(req.last_report_at),
        "finished_at": iso(req.finished_at),
        "outcome": req.outcome,
        "outcome_summary": req.outcome_summary,
        "allow_destructive": bool(req.allow_destructive),
    }
    if user is not None:
        block = approval_block(req, user, two_person=two_person)
        d["can_approve"] = block is None
        d["approve_blocked_reason"] = None if req.status != PENDING_APPROVAL else block
        d["can_cancel"] = req.status in CANCELLABLE
        d["can_mark_failed"] = req.status in IN_FLIGHT
    if steps is not None:
        d["steps"] = [step_dict(s) for s in steps]
    return d


def step_dict(step) -> Dict[str, Any]:
    return {"step": step.step, "status": step.status, "detail": step.detail, "at": iso(step.at)}


def release_dict(rel) -> Dict[str, Any]:
    return {
        "tag": rel.tag,
        "version": rel.version,
        "name": rel.name,
        "published_at": iso(rel.published_at),
        "notes": rel.notes,
        "url": rel.url,
        "prerelease": bool(rel.prerelease),
        "signature_verified": rel.signature_verified,
        "gate_passed": rel.gate_passed,
        "attested": rel.attested,
        "db_revision": rel.db_revision,
        "min_db_revision": rel.min_db_revision,
        "compatible_with_this_instance": rel.compatible_with_this_instance,
        "compatibility_detail": rel.compatibility_detail,
        "backend_digest": rel.backend_digest,
        "frontend_digest": rel.frontend_digest,
        "reported_at": iso(rel.reported_at),
    }


def parse_time(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def describe(req) -> str:
    """A request as a person reads it: "Upgrade to v1.8.0", "Restart"."""
    if req.action == "upgrade":
        return f"Upgrade to {req.target_tag}"
    if req.action == "rollback":
        return "Roll back to the previous release"
    return "Restart the app containers"


# ---------------------------------------------------------------------------
# Lease: a claimed request whose updater stopped reporting
# ---------------------------------------------------------------------------

LEASE_EXPIRED = "lease_expired"
MARKED_FAILED = "marked_failed"
ACTOR_REVOKED = "actor_not_admin"
LEASE_SUMMARY = "The updater stopped reporting; check the server"


def lease_minutes(action: str) -> int:
    """How long an in-flight request may go without a step or outcome report.

    UPGRADE_LEASE_MINUTES (default 45) for upgrades and rollbacks,
    UPGRADE_RESTART_LEASE_MINUTES (default 10) for restarts. Long steps
    (backup, pull, migrate) stay alive through the updater's heartbeat, which
    renews the lease every minute while a run is in progress.
    """
    import os

    name, default = (("UPGRADE_RESTART_LEASE_MINUTES", 10) if action == "restart"
                     else ("UPGRADE_LEASE_MINUTES", 45))
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        value = default
    return max(1, value)


async def expire_stale(db, *, now: Optional[datetime] = None, request_id: Optional[int] = None) -> List[int]:
    """Fail every claimed/running request whose lease ran out. Returns their ids.

    Applied lazily wherever requests are read and by a beat task every five
    minutes. Each expiry is one conditional UPDATE (still in flight, still the
    same last report), so it cannot race a report that just arrived. The
    caller emails admins about the returned ids.
    """
    from datetime import timedelta

    from sqlalchemy import update

    from app.models import UpgradeRequest

    now = now or now_utc()
    q = select(UpgradeRequest).where(UpgradeRequest.status.in_(IN_FLIGHT))
    if request_id is not None:
        q = q.where(UpgradeRequest.id == request_id)
    rows = (await db.execute(q)).scalars().all()
    expired: List[int] = []
    for r in rows:
        last = aware(r.last_report_at) or aware(r.claimed_at) or aware(r.requested_at)
        if last is None or last + timedelta(minutes=lease_minutes(r.action)) > now:
            continue
        cond = [UpgradeRequest.id == r.id, UpgradeRequest.status.in_(IN_FLIGHT)]
        cond.append(UpgradeRequest.last_report_at.is_(None) if r.last_report_at is None
                    else UpgradeRequest.last_report_at == r.last_report_at)
        result = await db.execute(
            update(UpgradeRequest).where(*cond)
            .values(status=FAILED, outcome=LEASE_EXPIRED, outcome_summary=LEASE_SUMMARY, finished_at=now)
            .execution_options(synchronize_session=False))
        if result.rowcount == 1:
            expired.append(r.id)
    if not expired:
        return []
    await db.commit()
    for rid in expired:
        req = await db.get(UpgradeRequest, rid)
        if req is not None:
            await db.refresh(req)
        logger.warning("[Upgrades] request %s: the updater stopped reporting; marked failed", rid)
        try:
            from app.services.audit_service import AuditService

            await AuditService.log_event(
                db, event_type="upgrade_request_finished", success=False, username="system:lease",
                failure_reason=LEASE_SUMMARY,
                details={"request_id": rid, "action": getattr(req, "action", None),
                         "target_tag": getattr(req, "target_tag", None), "status": FAILED, "outcome": LEASE_EXPIRED,
                         "lease_minutes": lease_minutes(getattr(req, "action", "upgrade"))})
        except Exception as exc:
            logger.warning("[Upgrades] could not audit the lease expiry of %s: %s", rid, exc)
    return expired


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

async def notify_admins(kind: str, request_id: Optional[int] = None, actor: Optional[str] = None) -> None:
    """Email every active admin. Never raises.

    kind: created | needs_approval | finished (about request ``request_id``),
    or two_person_disabled (``actor`` turned the approval rule off). Runs
    after the response (a BackgroundTask) or from the beat task, in its own
    session, and sends one message per admin so one town's administrators are
    not disclosed to each other.
    """
    try:
        from app.db.session import SessionLocal
        from app.models import SystemSettings, UpgradeRequest
        from app.services import email_layout as L
        from app.services.connector_alerts import admin_emails

        async with SessionLocal() as db:
            req = None
            if kind != "two_person_disabled":
                req = await db.get(UpgradeRequest, request_id)
                if req is None:
                    return
            recipients = await admin_emails(db)
            if not recipients:
                logger.warning("[Upgrades] no admin address to tell about %s %s", kind, request_id)
                return
            town_row = (await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))).scalar_one_or_none()
            town = (town_row.township_name if town_row else None) or "Pinpoint 311"
            if req is None:
                subject, blocks = compose_settings_email(actor or "an admin", town=town, L=L)
            else:
                subject, blocks = compose_email(kind, req, town=town, L=L)
            body = L.build_email(subject=subject, township_name=town, blocks=blocks,
                                 logo_url=getattr(town_row, "logo_url", None),
                                 primary_color=getattr(town_row, "primary_color", None) or L.DEFAULT_BRAND)
            try:
                from app.tasks.service_requests import configure_notifications
                await configure_notifications(db)
            except Exception as exc:
                logger.debug("[Upgrades] could not configure the email sender: %s", str(exc)[:200])
        from app.services.notifications import NotificationService
        send = NotificationService.get_instance().send_email
        for address in recipients:
            try:
                await asyncio.to_thread(send, to=address, subject=body["subject"],
                                        body_html=body["html"], body_text=body["text"])
            except Exception as exc:
                logger.warning("[Upgrades] could not send a request email: %s", str(exc)[:200])
    except Exception as exc:
        logger.warning("[Upgrades] request email failed: %s", str(exc)[:300])


def compose_settings_email(actor: str, *, town: str, L) -> Tuple[str, List[Dict[str, Any]]]:
    subject = f"{town}: two-person approval for upgrades was turned off"
    blocks = [
        L.callout(f"{actor} turned off two-person approval. One admin can now upgrade or roll back this "
                  "instance without anyone else approving.", tone="warning", title="Two-person approval is off"),
        L.paragraph("If you did not expect this, turn it back on in Admin Console → Version Control and review "
                    "the audit log. An unexpected change here can mean an admin account is being misused."),
        L.note("The server operator can make two-person approval non-negotiable for this instance by setting "
               "require_two_person_approval: true in /etc/pinpoint-updater/instances.yml. The updater then refuses "
               "an upgrade or rollback approved only by its requester, whatever this setting says."),
    ]
    return subject, blocks


def compose_email(kind: str, req, *, town: str, L) -> Tuple[str, List[Dict[str, Any]]]:
    what = describe(req)
    rows = [("Request", f"#{req.id}: {what}"), ("Requested by", req.requested_by), ("Reason", req.reason)]
    if req.scheduled_for:
        rows.append(("Scheduled for", iso(req.scheduled_for)))
    if req.allow_destructive:
        rows.append(("Destructive migration", "allowed by the requester"))
    if kind == "created":
        if req.status == PENDING_APPROVAL:
            subject = f"{town}: {what} needs a second admin's approval"
            lead = (f"{req.requested_by} asked for this change. It runs only after a different "
                    "admin approves it in Admin Console → Version Control.")
        else:
            subject = f"{town}: {what} requested"
            lead = (f"{req.requested_by} asked for this change. The host updater will run it "
                    + ("at the scheduled time." if req.scheduled_for else "on its next check (within about a minute)."))
        blocks = [L.lede(lead), L.fields(rows),
                  L.note("If you did not expect this, cancel it in Version Control and review the audit log.")]
        return subject, blocks
    if kind == "needs_approval":
        subject = f"{town}: {what} is on hold: destructive migration"
        blocks = [L.lede("The updater stopped before changing anything: this release's database migration is "
                         "destructive. The current version is still serving."),
                  L.fields(rows + [("Updater", req.outcome_summary or "")]),
                  L.note("To go ahead, file a new request with \"allow destructive migration\" checked, "
                         "after taking and checking a backup.")]
        return subject, blocks
    word = {SUCCEEDED: "succeeded", ROLLED_BACK: "was rolled back", REFUSED: "was refused",
            FAILED: "failed"}.get(req.status, req.status.replace("_", " "))
    subject = f"{town}: {what} {word}"
    tone = "success" if req.status == SUCCEEDED else "warning"
    blocks = [L.callout(req.outcome_summary or word, tone=tone, title=f"{what} {word}"), L.fields(rows),
              L.note("The step-by-step log is in Admin Console → Version Control.")]
    return subject, blocks
