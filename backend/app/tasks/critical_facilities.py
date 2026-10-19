"""Keep the town's critical-facility store current. Nobody has to press anything.

The store is filled once soon after the worker starts (when it is empty) and
then checked daily, refreshing when it is a week old -- so a refresh that fails
because Overpass was busy is retried tomorrow, not next week. Every failure
keeps the previous set; see app/services/critical_facilities.py.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


# Its own limit: Overpass may take its full 90 s server budget on each of two
# rounds, plus the client's margin, before the swap even starts.
@celery_app.task(name="app.tasks.critical_facilities.refresh_critical_facilities",
                 time_limit=600, soft_time_limit=540)
def refresh_critical_facilities(only_if_empty: bool = False, force: bool = False) -> Dict[str, Any]:
    import asyncio

    from app.db.session import SessionLocal
    from app.services.critical_facilities import refresh_if_due

    async def run() -> Dict[str, Any]:
        async with SessionLocal() as db:
            return await refresh_if_due(db, only_if_empty=only_if_empty, force=force)

    result = asyncio.run(run())
    logger.info("[critical facilities] %s", result)
    return result
