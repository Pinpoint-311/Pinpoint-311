"""Invite emails for new staff accounts.

An account an administrator creates is useless until the person knows it
exists, where to sign in and with which account. This sends them that, once,
when the account is made (and again from "Resend invite").

Two halves:

  * `queue_invite` runs in the request. It decides whether an invite can go
    and hands it to the worker. It never raises and never waits on mail: the
    account is already committed when it is called, and an SMTP outage must
    not turn "user created" into an error.
  * `deliver_invite` runs in the worker (app/tasks/staff_invites.py). It
    renders the message, sends it, stamps `users.invited_at`, and records
    `staff_invite_sent` or `staff_invite_failed` in the admin audit log.

The audit payload is the account id and the domain of its address -- not the
address. The address is on the row; the log is exported and kept longer.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.sanitize import sanitize_for_log
from app.services.admin_audit import record_admin_action

logger = logging.getLogger(__name__)

QUEUED = "queued"
SKIPPED_EMAIL_OFF = "skipped_email_off"
NOT_REQUESTED = "not_requested"
QUEUE_FAILED = "queue_failed"


def email_domain(address: Optional[str]) -> Optional[str]:
    """The part after the @, lower-cased; None for anything without one."""
    if not address or "@" not in address:
        return None
    return address.rsplit("@", 1)[1].strip().lower() or None


def audit_details(user_id: Optional[int], address: Optional[str]) -> Dict[str, Any]:
    """The account id and the address's domain -- never the address itself.
    Why a failure happened goes in the entry's failure_reason."""
    return {"user_id": user_id, "email_domain": email_domain(address)}


async def _email_enabled() -> bool:
    from app.services import capability_switches
    return await capability_switches.enabled("email")


def _task():
    from app.tasks.staff_invites import send_staff_invite
    return send_staff_invite


async def queue_invite(db, user, actor) -> str:
    """Hand an invite for `user` to the worker. Never raises.

    Returns one of QUEUED, SKIPPED_EMAIL_OFF or QUEUE_FAILED, which the API
    passes back so the admin console can say what happened.
    """
    user_id = getattr(user, "id", None)
    address = getattr(user, "email", None)
    try:
        if not await _email_enabled():
            logger.info("[Invite] email is switched off; no invite for user %s", user_id)
            return SKIPPED_EMAIL_OFF
        from app.services.enqueue import enqueue
        if enqueue(_task(), user_id, getattr(actor, "id", None)):
            return QUEUED
        reason = "queue_unavailable"
    except Exception as exc:  # noqa: BLE001 -- the account is saved; this is optional
        logger.warning("[Invite] could not queue an invite for user %s: %s",
                       user_id, sanitize_for_log(str(exc)))
        reason = "queue_error"

    await record_admin_action(
        db, event_type="staff_invite_failed", actor=actor, success=False,
        failure_reason=reason, details=audit_details(user_id, address),
    )
    return QUEUE_FAILED


async def _provider_name() -> Optional[str]:
    """The town's sign-in provider as staff would know it, or None.

    "Generic OIDC" is a setup-screen label, not something an employee has an
    account with, so it reads as "your work account" instead.
    """
    try:
        from app.services.identity import IDENTITY_CATALOG, IDENTITY_PROVIDER_KEY
        from app.services.secret_manager import get_secret
        provider = ((await get_secret(IDENTITY_PROVIDER_KEY)) or "auth0").strip().lower()
    except Exception:  # noqa: BLE001
        return None
    if provider == "oidc":
        return None
    return IDENTITY_CATALOG.get(provider, {}).get("name")


async def _origin(db) -> Optional[str]:
    from app.api.system import public_origin
    try:
        return await public_origin(db)
    except Exception:  # noqa: BLE001
        return None


async def deliver_invite(db, user_id: int, actor_id: Optional[int], send_email) -> Dict[str, Any]:
    """Render and send one invite, and record the outcome. Worker side.

    `send_email` is the transport (notification_service.send_email), passed in
    so this can be exercised without a mail server.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models import SystemSettings, User
    from app.services.email_templates import build_staff_invite_email

    user = (await db.execute(
        select(User).where(User.id == user_id).options(selectinload(User.departments))
    )).scalar_one_or_none()
    actor = None
    if actor_id is not None:
        actor = (await db.execute(select(User).where(User.id == actor_id))).scalar_one_or_none()

    async def failed(reason: str, address: Optional[str] = None) -> Dict[str, Any]:
        await record_admin_action(
            db, event_type="staff_invite_failed", actor=actor, success=False,
            failure_reason=reason, details=audit_details(user_id, address),
        )
        return {"status": "failed", "reason": reason}

    if user is None:
        return await failed("account_not_found")
    if not user.is_active:
        return await failed("account_inactive", user.email)
    if not await _email_enabled():
        return await failed("email_turned_off", user.email)

    settings = (await db.execute(
        select(SystemSettings).order_by(SystemSettings.id).limit(1)
    )).scalar_one_or_none()
    origin = await _origin(db)
    if not origin:
        logger.warning("[Invite] the site's public address is not set (custom domain or "
                       "DOMAIN); sending the invite for user %s without a sign-in link", user_id)

    message = build_staff_invite_email(
        township_name=(getattr(settings, "township_name", None) or ""),
        logo_url=getattr(settings, "logo_url", None),
        primary_color=(getattr(settings, "primary_color", None) or "#6366f1"),
        invitee_email=user.email,
        invitee_name=user.full_name,
        role=user.role,
        department_names=[d.name for d in (user.departments or [])],
        invited_by=(getattr(actor, "full_name", None) or getattr(actor, "username", None)),
        provider_name=await _provider_name(),
        origin=origin,
    )
    try:
        sent = send_email(to=user.email, subject=message["subject"],
                          body_html=message["html"], body_text=message["text"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Invite] sending the invite for user %s failed: %s",
                       user_id, sanitize_for_log(str(exc)))
        sent = False
    if sent is False:
        return await failed("delivery_failed", user.email)

    user.invited_at = datetime.now(timezone.utc)
    await db.commit()
    await record_admin_action(
        db, event_type="staff_invite_sent", actor=actor,
        details=audit_details(user_id, user.email),
    )
    return {"status": "sent", "with_link": bool(origin)}
