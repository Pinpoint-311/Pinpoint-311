"""Schedule the connector sweep.

Thin on purpose. The logic is in `app.services.connector_verification`, which
imports neither Celery nor FastAPI and can therefore be tested in CI, where
neither is installed. All this file adds is "once a day".
"""

from __future__ import annotations

import logging

from app.core.celery_app import celery_app
from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.connector_checks.verify_connectors")
def verify_connectors():
    """Daily entry point. Never raises, so a bad sweep cannot stop the beat."""
    import asyncio

    from app.services.connector_verification import verify_all

    async def run():
        from app.db.session import SessionLocal
        async with SessionLocal() as db:
            return await verify_all(db)

    try:
        return asyncio.run(run())
    except Exception as exc:
        logger.error("[Health] daily connector check could not run: %s",
                     sanitize_for_log(str(exc)[:300]))
        return {"checked": {}, "failing": [], "error": True}


@celery_app.task(name="app.tasks.connector_checks.probe_system")
def probe_system():
    """Hourly infrastructure probe.

    Hourly rather than daily because a disk fills in hours, and each of these
    costs a syscall rather than a call to somebody else's API. It does not make
    the email hourly: the cadence is set by how long something has been in a
    state, not by how often it is measured.
    """
    import asyncio

    from app.services.connector_verification import probe_system as run_probe

    async def run():
        from app.db.session import SessionLocal
        from app.services import capability_switches, connector_alerts

        # Keeps `wanted_sync` current in this process. Sentry's `before_send`
        # cannot await a database read, so it answers from the last map anything
        # here happened to load -- and a process whose job is probing may never
        # dispatch a notification, which is what otherwise refreshes it.
        await capability_switches.refresh_snapshot()

        async with SessionLocal() as db:
            # Alerting is handed in rather than left to a second scheduled job.
            # A probe that records a full disk and does not send the email is
            # the same silence this replaces, one layer further in.
            #
            # The dispatcher itself, with its real signature. probe_system
            # routes it through notify, which loads the snapshot, the town
            # name and the settings link, and filters switched-off
            # capabilities -- an earlier wiring called the dispatcher as
            # `alerts(db)` and raised TypeError on the email step of every
            # hourly probe: the full disk was recorded, the dashboard showed
            # it, and the email this task exists to send was never sent.
            return await run_probe(db, alerts=connector_alerts.dispatch)

    try:
        return asyncio.run(run())
    except Exception as exc:
        logger.error("[Probe] hourly system probe could not run: %s",
                     sanitize_for_log(str(exc)[:300]))
        return {"probes": {}, "error": True}
