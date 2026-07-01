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

import base64
import logging
import re
from datetime import datetime

from sqlalchemy import select

from app.core.celery_app import celery_app
from app.db.session import SessionLocal
from app.models import (
    IntegrationConfig,
    IntegrationLink,
    IntegrationSyncLog,
    MapLayer,
    RequestAuditLog,
    RequestComment,
    ServiceDefinition,
    ServiceRequest,
)
from app.tasks.service_requests import run_async

logger = logging.getLogger(__name__)

def _flag(config: dict, key: str, default: bool = False) -> bool:
    """Read a boolean config value that may arrive as a string from the admin UI."""
    value = (config or {}).get(key)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


_DATA_URI_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)
_EXT_BY_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


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
        # Base64 blobs are never sent inline — http(s) URLs here; embedded
        # photos go through the document-upload channel where supported
        "media_urls": [u for u in (sr.media_urls or []) if isinstance(u, str) and u.startswith("http")],
        "matched_asset": sr.matched_asset,
        "custom_fields": sr.custom_fields,
        "priority": sr.manual_priority_score,
    }
    if config.get("share_pii"):
        payload.update({
            "first_name": sr.first_name,
            "last_name": sr.last_name,
            "email": sr.email,
            "phone": sr.phone,
        })
    return payload


def _decode_media(sr: ServiceRequest, max_items: int = 3):
    """Extract embedded base64 photos as (filename, bytes, content_type) tuples."""
    documents = []
    for i, url in enumerate((sr.media_urls or [])[:max_items]):
        if not isinstance(url, str):
            continue
        match = _DATA_URI_RE.match(url)
        if not match:
            continue
        mime, b64 = match.groups()
        try:
            content = base64.b64decode(b64)
        except Exception:
            continue
        ext = _EXT_BY_MIME.get(mime, "bin")
        documents.append((f"{sr.service_request_id}-photo-{i + 1}.{ext}", content, mime))
    return documents


async def _push_documents(db, connector, integration, link, sr):
    """Upload the request's embedded photos to the linked external record."""
    if "documents" not in connector.capabilities or link.documents_pushed:
        return
    documents = _decode_media(sr)
    if not documents:
        link.documents_pushed = True
        return
    pushed = 0
    try:
        for filename, content, mime in documents:
            await connector.push_document(link.external_id, filename, content, mime)
            pushed += 1
        link.documents_pushed = True
        await _log(db, integration.id, "push_documents", "success",
                   f"{sr.service_request_id}: {pushed} photo(s) attached", pushed)
    except Exception as e:
        await _log(db, integration.id, "push_documents", "error",
                   f"{sr.service_request_id}: {e} ({pushed} uploaded before failure)")
        logger.warning(f"[Integrations] Document push to {integration.platform} failed: {e}")


async def _import_external_record(db, integration, record):
    """Create a local service request from a platform-originated record."""
    config = integration.config or {}
    service_code_map = config.get("service_code_map") or {}
    local_code = None
    if record.service_name and record.service_name in service_code_map:
        local_code = service_code_map[record.service_name]
    local_code = local_code or config.get("default_local_service_code")

    service = None
    if local_code:
        service = (await db.execute(
            select(ServiceDefinition).where(
                ServiceDefinition.service_code == local_code,
                ServiceDefinition.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
    if not service:
        service = (await db.execute(
            select(ServiceDefinition).where(ServiceDefinition.is_active == True).limit(1)  # noqa: E712
        )).scalar_one_or_none()
    if not service:
        return None

    from app.api.open311 import generate_request_id
    sr = ServiceRequest(
        service_request_id=generate_request_id(),
        service_code=service.service_code,
        service_name=service.service_name,
        description=record.description or f"Imported from {integration.display_name} (#{record.external_id})",
        address=record.address,
        lat=record.lat,
        long=record.long,
        email=f"integration-{integration.platform}@intake.local",
        source=f"integration_{integration.platform}",
        status=record.status or "open",
        assigned_department_id=service.assigned_department_id,
    )
    db.add(sr)
    await db.flush()
    db.add(IntegrationLink(
        integration_id=integration.id,
        service_request_id=sr.id,
        external_id=record.external_id,
        external_status=record.raw_status,
        direction="pulled",
        last_pulled_at=datetime.utcnow(),
    ))
    db.add(RequestAuditLog(
        service_request_id=sr.id,
        action="submitted",
        new_value=sr.status,
        actor_type="integration",
        actor_name=integration.display_name,
    ))
    return sr


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
                    link = IntegrationLink(
                        integration_id=integration.id,
                        service_request_id=sr.id,
                        external_id=record.external_id,
                        external_status=record.raw_status,
                        direction="pushed",
                        last_pushed_at=datetime.utcnow(),
                    )
                    db.add(link)
                    await _log(db, integration.id, "push", "success",
                               f"{sr.service_request_id} -> {record.external_id}", 1)
                    logger.info(f"[Integrations] Pushed {sr.service_request_id} to {integration.platform} as {record.external_id}")
                    # Attach embedded photos to the newly created external record
                    await _push_documents(db, connector, integration, link, sr)
                    await db.commit()
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
                    imported = 0
                    for record in records:
                        link = (await db.execute(
                            select(IntegrationLink).where(
                                IntegrationLink.integration_id == integration.id,
                                IntegrationLink.external_id == record.external_id,
                            )
                        )).scalar_one_or_none()
                        if not link:
                            # Platform-originated record we've never seen — import it
                            # as a new local request when enabled
                            if _flag(integration.config, "import_new_records"):
                                new_sr = await _import_external_record(db, integration, record)
                                if new_sr:
                                    imported += 1
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
                               f"{len(records)} record(s) fetched, {updated} status change(s) applied, "
                               f"{imported} new request(s) imported",
                               len(records))
                except Exception as e:
                    integration.last_sync_at = datetime.utcnow()
                    integration.last_sync_status = "error"
                    integration.last_sync_error = str(e)[:1000]
                    await _log(db, integration.id, "pull", "error", str(e))
                    logger.warning(f"[Integrations] Pull from {integration.platform} failed: {e}")
            await db.commit()

    run_async(_pull())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def push_comment_to_integrations(self, comment_id: int):
    """Post an external-visibility comment to every platform its request is linked to."""
    from app.integrations import build_connector

    async def _push_comment():
        async with SessionLocal() as db:
            comment = (await db.execute(
                select(RequestComment).where(RequestComment.id == comment_id)
            )).scalar_one_or_none()
            if not comment or comment.visibility != "external" or comment.external_ref:
                return  # only outbound-eligible comments; never echo imported ones

            links = (await db.execute(
                select(IntegrationLink, IntegrationConfig)
                .join(IntegrationConfig, IntegrationLink.integration_id == IntegrationConfig.id)
                .where(
                    IntegrationLink.service_request_id == comment.service_request_id,
                    IntegrationConfig.enabled == True,  # noqa: E712
                )
            )).all()

            for link, integration in links:
                try:
                    connector = build_connector(
                        integration.platform, integration.config or {}, integration.credentials
                    )
                    if "comments" not in connector.capabilities:
                        continue
                    external_comment_id = await connector.push_comment(
                        link.external_id, comment.username, comment.content
                    )
                    # Track what we sent so pulls don't re-import our own comments
                    sent_marker = external_comment_id or f"local:{comment.id}"
                    link.pushed_comment_ids = [*(link.pushed_comment_ids or []), sent_marker]
                    await _log(db, integration.id, "push_comment", "success",
                               f"comment {comment.id} -> {link.external_id}", 1)
                except Exception as e:
                    await _log(db, integration.id, "push_comment", "error",
                               f"comment {comment.id}: {e}")
                    logger.warning(f"[Integrations] Comment push to {integration.platform} failed: {e}")
            await db.commit()

    run_async(_push_comment())


@celery_app.task
def pull_integration_comments():
    """Beat task: import new external comments on linked, active requests."""
    from app.integrations import build_connector

    async def _pull_comments():
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
                    if "comments" not in connector.capabilities:
                        continue

                    # Only poll comments for requests still in flight (bounded per run)
                    links = (await db.execute(
                        select(IntegrationLink)
                        .join(ServiceRequest, IntegrationLink.service_request_id == ServiceRequest.id)
                        .where(
                            IntegrationLink.integration_id == integration.id,
                            ServiceRequest.status.in_(["open", "in_progress"]),
                            ServiceRequest.deleted_at.is_(None),
                        )
                        .limit(100)
                    )).scalars().all()

                    imported = 0
                    for link in links:
                        external_comments = await connector.pull_comments(link.external_id)
                        pushed_ids = set(link.pushed_comment_ids or [])
                        for ec in external_comments:
                            if ec.external_id in pushed_ids:
                                continue  # our own comment echoed back
                            ref = f"{integration.id}:{ec.external_id}"
                            exists = (await db.execute(
                                select(RequestComment.id).where(RequestComment.external_ref == ref)
                            )).scalar_one_or_none()
                            if exists:
                                continue
                            db.add(RequestComment(
                                service_request_id=link.service_request_id,
                                username=(ec.author or integration.display_name)[:100],
                                content=ec.content[:5000],
                                visibility="external",
                                external_ref=ref,
                            ))
                            imported += 1
                        link.last_pulled_at = datetime.utcnow()

                    if imported or links:
                        await _log(db, integration.id, "pull_comments", "success",
                                   f"{len(links)} request(s) polled, {imported} comment(s) imported",
                                   imported)
                except Exception as e:
                    await _log(db, integration.id, "pull_comments", "error", str(e))
                    logger.warning(f"[Integrations] Comment pull from {integration.platform} failed: {e}")
            await db.commit()

    run_async(_pull_comments())


@celery_app.task
def sync_integration_assets():
    """Beat task: mirror external asset inventories into Pinpoint map layers.

    Synced assets become a point layer usable for asset-linked request intake
    (residents pick the exact hydrant/streetlight/sign the report is about).
    Enabled per integration via config.sync_assets = true."""
    from app.integrations import build_connector

    async def _sync_assets():
        async with SessionLocal() as db:
            integrations = (await db.execute(
                select(IntegrationConfig).where(IntegrationConfig.enabled == True)  # noqa: E712
            )).scalars().all()

            for integration in integrations:
                config = integration.config or {}
                if not _flag(config, "sync_assets"):
                    continue
                try:
                    connector = build_connector(integration.platform, config, integration.credentials)
                    if "assets" not in connector.capabilities:
                        continue
                    features = await connector.pull_assets()
                    if not features:
                        await _log(db, integration.id, "sync_assets", "success",
                                   "0 mappable assets returned")
                        continue

                    geojson = {"type": "FeatureCollection", "features": features}
                    layer_id = config.get("asset_layer_id")
                    layer = None
                    if layer_id:
                        layer = (await db.execute(
                            select(MapLayer).where(MapLayer.id == layer_id)
                        )).scalar_one_or_none()
                    if layer:
                        layer.geojson = geojson
                        layer.updated_at = datetime.utcnow()
                    else:
                        layer = MapLayer(
                            name=f"{integration.display_name} Assets"[:100],
                            description=f"Asset inventory synced from {integration.display_name}",
                            layer_type="point",
                            geojson=geojson,
                            is_active=True,
                            show_on_resident_portal=_flag(config, "assets_on_resident_portal", default=True),
                            service_codes=config.get("asset_service_codes") or [],
                        )
                        db.add(layer)
                        await db.flush()
                        integration.config = {**config, "asset_layer_id": layer.id}
                    await _log(db, integration.id, "sync_assets", "success",
                               f"{len(features)} asset(s) synced to layer '{layer.name}'",
                               len(features))
                except Exception as e:
                    await _log(db, integration.id, "sync_assets", "error", str(e))
                    logger.warning(f"[Integrations] Asset sync from {integration.platform} failed: {e}")
            await db.commit()

    run_async(_sync_assets())
