"""Keep ArcGIS-sourced map layers in sync, for the layers whose admin asked.

Hourly: each layer set to daily or weekly auto-sync whose interval has passed
is checked. An unchanged source costs a request or two and changes nothing; a
changed one is re-imported through the same path as "Refresh from ArcGIS",
and applied only when it passes the guardrails in
app/services/arcgis_import.py. A held sync keeps the old features, marks the
layer for review and shows on the health panel.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.core.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.arcgis_sync.sync_arcgis_layers", time_limit=3000, soft_time_limit=2900)
def sync_arcgis_layers() -> Dict[str, Any]:
    import asyncio

    from app.db.session import SessionLocal
    from app.services.arcgis_import import run_due_syncs

    async def run() -> Dict[str, Any]:
        async with SessionLocal() as db:
            return await run_due_syncs(db)

    result = asyncio.run(run())
    logger.info("[arcgis sync] %s", {k: v for k, v in result.items() if k != "results"})
    return result
