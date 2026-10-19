"""Beat entry for the upgrade-request lease (docs/design/secure-upgrades.md).

Every five minutes: a claimed or running request whose updater has not
reported for its lease (UPGRADE_LEASE_MINUTES, 45; restarts
UPGRADE_RESTART_LEASE_MINUTES, 10) becomes failed, is audited, and every admin
is emailed. The same rule is applied lazily wherever requests are read; this
makes sure it happens even when nobody is looking. The logic lives in
app.services.upgrades.expire_stale.
"""

from __future__ import annotations

import logging

from app.core.celery_app import celery_app
from app.core.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)


async def run_lease_sweep() -> list:
    from app.db.session import SessionLocal
    from app.services import upgrades as U

    async with SessionLocal() as db:
        expired = await U.expire_stale(db)
    for rid in expired:
        await U.notify_admins("finished", rid)
    return expired


@celery_app.task(name="app.tasks.upgrades.expire_stale_upgrade_requests")
def expire_stale_upgrade_requests():
    """Never raises, so a bad sweep cannot stop the beat."""
    import asyncio

    try:
        return {"expired": asyncio.run(run_lease_sweep())}
    except Exception as exc:
        logger.error("[Upgrades] lease sweep could not run: %s", sanitize_for_log(str(exc)[:300]))
        return {"expired": [], "error": True}
