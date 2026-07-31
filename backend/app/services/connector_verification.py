"""Test every configured connector, and record what happened.

The setup page could always answer "are the credentials stored". That is a
question about our own database, and it stays green forever. Whether the
credentials still *work* is a question about somebody else's service, and the
answer changes without anyone here doing anything: a client secret expires, a
card on file lapses, a departing employee's key is revoked, a vendor tightens a
scope.

Until now the only ways to learn that were an admin opening the settings page
and pressing Test -- at a moment chosen by the person least likely to be
surprised by the answer -- or a resident reporting that no email ever arrived.

Three things this deliberately does not do, each of which is a way a health
sweep can be worse than none at all:

  * It does not test what is not configured. A town that never set up text
    messages has not made a mistake, and an amber badge on something switched
    off is the noise that teaches people to ignore badges.
  * It does not record "cannot be checked from here" as a failure. Apple
    MapKit, ACS and a generic HTTP gateway genuinely cannot be verified from
    the server, and a red badge that can never go green is worse than none.
  * It does not stop at the first check that raises. Aborting there would leave
    the other seven connectors unreported, which is the state this replaces.

Nothing here sends anything to a resident: the email and text checks
authenticate and query rather than delivering a message.

The checks and the is-it-configured predicate are injected rather than imported
at module scope. That keeps this importable -- and therefore testable -- without
FastAPI or Celery, neither of which CI installs.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional

from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

Check = Callable[..., Awaitable[Dict[str, Any]]]


async def verify_all(
    db,
    *,
    checks: Optional[Mapping[str, Check]] = None,
    is_configured: Optional[Callable[[str], Awaitable[bool]]] = None,
    health=None,
    alerts=None,
) -> Dict[str, Any]:
    """Run each capability's live check. Returns a summary; never raises."""
    if checks is None or is_configured is None:
        from app.api.system import _CAPABILITY_TESTS, capability_is_configured
        checks = checks if checks is not None else _CAPABILITY_TESTS
        is_configured = is_configured or capability_is_configured
    if health is None:
        from app.services import connector_health as health

    checked: Dict[str, str] = {}
    for capability, check in checks.items():
        try:
            if not await is_configured(capability):
                checked[capability] = "not-configured"
                continue
        except Exception:
            # If we cannot tell, test it. A missed check is worse than a
            # redundant one.
            pass

        try:
            outcome = await check(db)
        except Exception as exc:
            # The provider's own words. A clerk searching the web for their
            # error needs the real string, not our paraphrase of it.
            await health.record_failure(db, capability, str(exc)[:300])
            checked[capability] = "error"
            logger.info("[Health] %s raised during the daily check: %s",
                        sanitize_for_log(capability), sanitize_for_log(str(exc)[:200]))
            continue

        if outcome.get("recorded") is False:
            checked[capability] = "unverifiable"
        elif outcome.get("ok"):
            await health.record_success(db, capability)
            checked[capability] = "working"
        else:
            await health.record_failure(db, capability, outcome.get("detail", ""))
            checked[capability] = "failing"

    failing = sorted(k for k, v in checked.items() if v in ("failing", "error"))
    if failing:
        logger.warning("[Health] daily connector check found problems: %s",
                       sanitize_for_log(", ".join(failing)))

    # Having found out, tell somebody.
    #
    # Writing the result to a table and a log line and then waiting for an
    # administrator to open the settings page is how the original failure mode
    # survived this whole subsystem: the software knew on Tuesday and the town
    # found out on Monday, from a resident.
    alerted = await notify(db, health=health, alerts=alerts)
    return {"checked": checked, "failing": failing, "alerted": alerted}


async def notify(db, *, health=None, alerts=None) -> Dict[str, Any]:
    """Send the digest for whatever the sweep just recorded. Never raises."""
    try:
        if health is None:
            from app.services import connector_health as health
        if alerts is None:
            from app.services import connector_alerts as alerts

        snapshot = await health.snapshot(db)
        return await alerts.dispatch(
            db,
            healths=list(snapshot.values()),
            town=await _town_name(db),
            settings_url=await _settings_url(db),
        )
    except Exception as exc:
        logger.warning("[Health] could not send connector alerts: %s",
                       sanitize_for_log(str(exc)[:300]))
        return {"sent": False, "reason": "error"}


async def _town_name(db) -> str:
    try:
        from sqlalchemy import select

        from app.models import SystemSettings

        result = await db.execute(select(SystemSettings.township_name).limit(1))
        return result.scalar_one_or_none() or "Pinpoint 311"
    except Exception:
        return "Pinpoint 311"


async def _settings_url(db) -> Optional[str]:
    """The real address of the settings page, not wherever a browser happened
    to be. A link built from an internal hostname is a link nobody can open."""
    try:
        from app.api.system import public_origin

        origin = await public_origin(db)
        return f"{origin.rstrip('/')}/admin?tab=integration" if origin else None
    except Exception:
        return None
