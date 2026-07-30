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
