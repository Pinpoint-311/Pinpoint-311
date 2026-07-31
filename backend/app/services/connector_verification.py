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


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

async def probe_system(db, *, readings=None, health=None, alerts=None):
    """Record disk, database, cache and backup state as health rows.

    Deliberately the same table, the same escalation and the same mute as the
    connectors, rather than a second alerting path beside the first. Two paths
    would drift, and the town would learn which one to trust the hard way.

    `readings` is injectable so the whole thing runs in CI, which has no disk
    quota worth failing, no PostgreSQL and no Redis.
    """
    from app.services import system_probes as probes

    if health is None:
        from app.services import connector_health as health
    if readings is None:
        readings = await _collect_readings(db)

    recorded = {}
    for connector, outcome in readings.items():
        # "We could not measure this" is not "this is broken" -- the same rule
        # the connector sweep follows for things it cannot check.
        if outcome.get("recorded") is False:
            recorded[connector] = "unmeasured"
            continue
        try:
            if outcome["ok"]:
                await health.record_success(db, connector)
            else:
                await health.record_failure(db, connector, outcome["detail"])
            recorded[connector] = "ok" if outcome["ok"] else "failing"
        except Exception:
            logger.warning("[Probe] could not record %s", sanitize_for_log(connector))
    if alerts is not None:
        await alerts(db)
    return {"probes": recorded, "labels": {k: probes.label_for(k) for k in readings}}


async def _collect_readings(db) -> Dict[str, Dict[str, Any]]:
    """The real measurements. Every one is guarded: a probe that raises must
    not take the other three with it."""
    import shutil

    from sqlalchemy import text

    from app.services import system_probes as probes

    out: Dict[str, Dict[str, Any]] = {}

    # Disk. The path that matters is wherever PostgreSQL and uploads live; with
    # no better answer available from inside the container, the root volume is
    # the one that fills.
    try:
        usage = shutil.disk_usage("/")
        percent = (usage.used / usage.total) * 100 if usage.total else None
        free_gb = usage.free / (1024 ** 3)
        out["system:disk"] = probes.classify_disk(percent, free_label=f"{free_gb:.1f} GB")
    except Exception:
        out["system:disk"] = probes.classify_disk(None)

    try:
        await db.execute(text("SELECT 1"))
        out["system:database"] = probes.classify_reachable("The database", True)
    except Exception as e:
        # Never the exception text.
        #
        # This string is stored in connector_health.last_error, shown on the
        # card, and put in the alert email. A PostgreSQL connection failure
        # routinely quotes the DSN back at you -- host, user and password --
        # so a database that goes down would email its own credentials to
        # every administrator, and leave them in a table and an inbox
        # afterwards. The type is enough to act on; the rest goes to the log,
        # through the sanitiser, where it is already handled.
        logger.warning("[Probe] database unreachable: %s", sanitize_for_log(str(e)[:300]))
        out["system:database"] = probes.classify_reachable(
            "The database", False, probes.failure_summary(e))

    try:
        from app.core.redis_client import redis_client
        if redis_client is None:
            # Not configured is not broken. Redis is optional here.
            out["system:cache"] = {"ok": True, "detail": "No cache configured.", "recorded": False}
        else:
            await redis_client.ping()
            out["system:cache"] = probes.classify_reachable("The cache", True)
    except Exception as e:
        # Same reasoning as the database above: a Redis URL carries a password.
        logger.warning("[Probe] cache unreachable: %s", sanitize_for_log(str(e)[:300]))
        out["system:cache"] = probes.classify_reachable(
            "The cache", False, probes.failure_summary(e))

    try:
        from datetime import datetime, timezone

        from app.services.backup_service import get_backup_status
        status = await get_backup_status()
        last = (status or {}).get("last_backup_at") or (status or {}).get("last_backup")
        if isinstance(last, str):
            from datetime import datetime as _dt
            last = _dt.fromisoformat(last.replace("Z", "+00:00"))
        out["system:backups"] = probes.classify_backup(last, datetime.now(timezone.utc))
    except Exception:
        # Backups not being configured at all is a real and supported state for
        # a town whose host takes them, so this is not reported as a failure.
        out["system:backups"] = {"ok": True, "detail": "Backup status unavailable.", "recorded": False}

    return out
