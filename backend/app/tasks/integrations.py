"""Celery tasks that sync service requests with external govtech platforms.

Flow:
  - push_request_to_integrations: fired after a request is created; pushes it
    to every enabled integration whose sync direction includes push.
  - push_status_to_integrations: fired after a status change; propagates the
    new status to every platform the request is linked to.
  - pull_integration_updates: Celery Beat job; polls pull-enabled platforms
    for changed records and mirrors status changes onto linked local requests.

Sync failures are logged to integration_sync_logs and never block the core
request lifecycle.
"""

import logging
from datetime import datetime

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models import (
    IntegrationConfig,
    IntegrationLink,
    IntegrationSyncLog,
    RequestAuditLog,
    ServiceRequest,
)
from app.tasks.service_requests import run_async

logger = logging.getLogger(__name__)


def _build_payload(sr: ServiceRequest, config: dict) -> dict:
    """Normalized outbound payload. PII is only included when the integration
    is explicitly configured to share it (config.share_pii)."""
    payload = {
        "service_request_id": sr.service_request_id,
        "service_code": sr.service_code,
        "service_name": sr.service_name,
        "description": sr.description,
        "address": sr.address,
        "lat": sr.lat,
        "long": sr.long,
        "status": sr.status,
        "requested_datetime": sr.requested_datetime.isoformat() if sr.requested_datetime else None,
        # Base64 blobs are never pushed to third parties — http(s) URLs only
        "media_urls": [u for u in (sr.media_urls or []) if isinstance(u, str) and u.startswith("http")],
    }
    if config.get("share_pii"):
        payload.update({
            "first_name": sr.first_name,
            "last_name": sr.last_name,
            "email": sr.email,
            "phone": sr.phone,
        })
    return payload


async def _log(db, integration_id: int, operation: str, status: str, detail: str = "", count: int = 0):
    db.add(IntegrationSyncLog(
        integration_id=integration_id,
        operation=operation,
        status=status,
        detail=detail[:2000] if detail else None,
        request_count=count,
    ))
    await db.commit()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def push_request_to_integrations(self, request_id: int):
    """Push a newly created request to all enabled push integrations."""
    from app.integrations import build_connector

    async def _push():
        async with SessionLocal() as db:
            sr = (await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )).scalar_one_or_none()
            if not sr:
                return

            integrations = (await db.execute(
                select(IntegrationConfig).where(
                    IntegrationConfig.enabled == True,  # noqa: E712
                    IntegrationConfig.sync_direction.in_(["push", "bidirectional"]),
                )
            )).scalars().all()

            for integration in integrations:
                # Skip if already linked (retries / duplicate dispatch)
                existing = (await db.execute(
                    select(IntegrationLink).where(
                        IntegrationLink.integration_id == integration.id,
                        IntegrationLink.service_request_id == sr.id,
                    )
                )).scalar_one_or_none()
                if existing:
                    continue
                # Never echo a request back to the platform it came from
                if sr.source == f"integration_{integration.platform}":
                    continue

                try:
                    connector = build_connector(
                        integration.platform, integration.config or {}, integration.credentials
                    )
                    if "push" not in connector.capabilities:
                        continue
                    record = await connector.push_request(_build_payload(sr, integration.config or {}))
                    db.add(IntegrationLink(
                        integration_id=integration.id,
                        service_request_id=sr.id,
                        external_id=record.external_id,
                        external_status=record.raw_status,
                        direction="pushed",
                        last_pushed_at=datetime.utcnow(),
                    ))
                    await _log(db, integration.id, "push", "success",
                               f"{sr.service_request_id} -> {record.external_id}", 1)
                    logger.info(f"[Integrations] Pushed {sr.service_request_id} to {integration.platform} as {record.external_id}")
                except Exception as e:
                    await _log(db, integration.id, "push", "error",
                               f"{sr.service_request_id}: {e}")
                    logger.warning(f"[Integrations] Push to {integration.platform} failed: {e}")

    run_async(_push())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def push_status_to_integrations(self, request_id: int, notes: str = None):
    """Propagate a local status change to all platforms the request is linked to."""
    from app.integrations import build_connector

    async def _push_status():
        async with SessionLocal() as db:
            sr = (await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )).scalar_one_or_none()
            if not sr:
                return

            links = (await db.execute(
                select(IntegrationLink, IntegrationConfig)
                .join(IntegrationConfig, IntegrationLink.integration_id == IntegrationConfig.id)
                .where(
                    IntegrationLink.service_request_id == sr.id,
                    IntegrationConfig.enabled == True,  # noqa: E712
                )
            )).all()

            for link, integration in links:
                try:
                    connector = build_connector(
                        integration.platform, integration.config or {}, integration.credentials
                    )
                    if "push_status" not in connector.capabilities:
                        continue
                    await connector.push_status(link.external_id, sr.status, notes)
                    link.external_status = connector.map_status_out(sr.status)
                    link.last_pushed_at = datetime.utcnow()
                    link.sync_error = None
                    await _log(db, integration.id, "push_status", "success",
                               f"{sr.service_request_id} -> {sr.status}", 1)
                except Exception as e:
                    link.sync_error = str(e)[:1000]
                    await _log(db, integration.id, "push_status", "error",
                               f"{sr.service_request_id}: {e}")
                    logger.warning(f"[Integrations] Status push to {integration.platform} failed: {e}")
            await db.commit()

    run_async(_push_status())


@celery_app.task
def pull_integration_updates():
    """Beat task: poll pull-enabled platforms and mirror external status changes."""
    from app.integrations import build_connector

    async def _pull():
        async with SessionLocal() as db:
            integrations = (await db.execute(
                select(IntegrationConfig).where(
                    IntegrationConfig.enabled == True,  # noqa: E712
                    IntegrationConfig.sync_direction.in_(["pull", "bidirectional"]),
                )
            )).scalars().all()

            for integration in integrations:
                try:
                    connector = build_connector(
                        integration.platform, integration.config or {}, integration.credentials
                    )
                    if "pull" not in connector.capabilities:
                        continue
                    records = await connector.pull_updates(since=integration.last_sync_at)
                    updated = 0
                    for record in records:
                        link = (await db.execute(
                            select(IntegrationLink).where(
                                IntegrationLink.integration_id == integration.id,
                                IntegrationLink.external_id == record.external_id,
                            )
                        )).scalar_one_or_none()
                        if not link:
                            continue
                        link.last_pulled_at = datetime.utcnow()
                        if record.raw_status and record.raw_status != link.external_status:
                            link.external_status = record.raw_status
                        if not record.status:
                            continue
                        sr = (await db.execute(
                            select(ServiceRequest).where(ServiceRequest.id == link.service_request_id)
                        )).scalar_one_or_none()
                        if not sr or sr.status == record.status:
                            continue
                        old_status = sr.status
                        sr.status = record.status
                        sr.updated_datetime = datetime.utcnow()
                        if record.status == "closed":
                            sr.closed_datetime = datetime.utcnow()
                            if record.status_notes:
                                sr.completion_message = record.status_notes
                        db.add(RequestAuditLog(
                            service_request_id=sr.id,
                            action="status_change",
                            old_value=old_status,
                            new_value=record.status,
                            actor_type="integration",
                            actor_name=integration.display_name,
                        ))
                        updated += 1

                    integration.last_sync_at = datetime.utcnow()
                    integration.last_sync_status = "success"
                    integration.last_sync_error = None
                    await _log(db, integration.id, "pull", "success",
                               f"{len(records)} record(s) fetched, {updated} status change(s) applied",
                               len(records))
                except Exception as e:
                    integration.last_sync_at = datetime.utcnow()
                    integration.last_sync_status = "error"
                    integration.last_sync_error = str(e)[:1000]
                    await _log(db, integration.id, "pull", "error", str(e))
                    logger.warning(f"[Integrations] Pull from {integration.platform} failed: {e}")
            await db.commit()

    run_async(_pull())
