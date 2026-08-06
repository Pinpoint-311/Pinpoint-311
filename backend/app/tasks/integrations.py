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
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, update

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
from app.services import connector_health
from app.services.circuit_breaker import CircuitOpen, guard
from app.services.connector_verification import health_key
from app.tasks.service_requests import run_async

logger = logging.getLogger(__name__)

def _comment_fp(content: str) -> str:
    """Stable content fingerprint used as a fallback echo-dedup marker for
    comments whose platform returns no comment id on create."""
    return "fp:" + hashlib.sha1((content or "").strip().encode("utf-8")).hexdigest()[:16]


def _flag(config: dict, key: str, default: bool = False) -> bool:
    """Read a boolean config value that may arrive as a string from the admin UI."""
    value = (config or {}).get(key)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# How far back a poll reaches beyond the last recorded sync.
#
# These timestamps are not ours and are not transactionally ordered: a vendor
# writes `updated_at` from its own clock, at the moment it edits the row, and
# makes it visible to a query some time later. A poll that asks for "everything
# after the exact instant the last one started" therefore drops records whose
# stamp falls before that instant but which only became queryable after it.
#
# Overlapping re-reads a few records every run, which costs nothing: every
# record is matched to an IntegrationLink by external id and applied only if
# something actually changed, so a replay is a no-op.
PULL_OVERLAP = timedelta(minutes=5)


def _pull_since(integration) -> Optional[datetime]:
    """The window a poll should ask the vendor for."""
    last = integration.last_sync_at
    if last is None:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return last - PULL_OVERLAP


def _newest_change(records) -> Optional[datetime]:
    """The most recent `updated_at` in a batch, for the sync log.

    Every connector populates `ExternalRecord.updated_at` and nothing read it.
    It is reported rather than used as the watermark on purpose: a vendor whose
    clock runs fast would push the watermark into the future, and every change
    between now and then would be skipped -- a worse failure than the one being
    fixed here, and a silent one. `started_at` is a clock we own.
    """
    stamps = []
    for record in records:
        stamp = getattr(record, "updated_at", None)
        if stamp is None:
            continue
        stamps.append(stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp)
    return max(stamps) if stamps else None


_DATA_URI_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", re.DOTALL)
_EXT_BY_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def _build_payload(sr: ServiceRequest, config: dict, dept_name: Optional[str] = None) -> dict:
    """Normalized outbound payload. PII is only included when the integration
    is explicitly configured to share it (config.share_pii). Work-order fields
    (priority, assignment, due date) are carried so a work-order management
    system can open a properly-routed work order."""
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
        # Work-order routing fields
        "priority": sr.manual_priority_score if sr.manual_priority_score is not None else sr.priority,
        "assigned_to": sr.assigned_to,
        "assigned_department": dept_name,
        "due_date": sr.due_datetime.isoformat() if getattr(sr, "due_datetime", None) else None,
        # How and when it was resolved. A work order that syncs the request but
        # not its outcome leaves the external system showing an open job the
        # town closed weeks ago -- and `completion_message` is the sentence the
        # resident was actually given, which is what a county reviewing the
        # record wants to read. It was already being pushed on a status change
        # and was missing from the record itself.
        "closed_datetime": sr.closed_datetime.isoformat() if sr.closed_datetime else None,
        "closed_substatus": sr.closed_substatus,
        "completion_message": sr.completion_message,
        # Same rule as media_urls: a link, never an inline blob.
        "completion_photo_url": (
            sr.completion_photo_url
            if isinstance(sr.completion_photo_url, str) and sr.completion_photo_url.startswith("http")
            else None
        ),
        "updated_datetime": sr.updated_datetime.isoformat() if sr.updated_datetime else None,
        # Where it came from, so a platform that also feeds us can recognise
        # its own records, and what language the resident used, so whoever
        # turns up can be someone who speaks it.
        "source": sr.source,
        "preferred_language": sr.preferred_language,
    }
    if _flag(config, "share_pii"):
        payload.update({
            "first_name": sr.first_name,
            "last_name": sr.last_name,
            "email": sr.email,
            "phone": sr.phone,
        })
    return payload


async def _dept_name(db, sr: ServiceRequest) -> Optional[str]:
    """Resolve the assigned department's name for the outbound payload without
    relying on a lazy relationship load (which errors under the async engine)."""
    if not sr.assigned_department_id:
        return None
    from app.models import Department
    dept = (await db.execute(
        select(Department).where(Department.id == sr.assigned_department_id)
    )).scalar_one_or_none()
    return dept.name if dept else None


async def _apply_work_order_fields(db, sr, record, integration) -> bool:
    """Reflect a work-order update from the vendor into Pinpoint as an internal
    timeline comment (and fill assignment if we don't have one locally), without
    clobbering staff-owned fields. Returns True if anything was recorded."""
    bits = []
    if record.work_order_id:
        bits.append(f"work order {record.work_order_id}")
    if record.assigned_department:
        bits.append(f"dept: {record.assigned_department}")
    if record.assigned_to:
        bits.append(f"assigned to: {record.assigned_to}")
    if record.scheduled_datetime:
        bits.append(f"scheduled: {record.scheduled_datetime.date().isoformat()}")
    if record.due_datetime:
        bits.append(f"due: {record.due_datetime.date().isoformat()}")
    if record.priority:
        bits.append(f"priority: {record.priority}")
    if record.resolution:
        bits.append(f"resolution: {record.resolution}")
    if not bits:
        return False

    # Fill local assignment only if empty — never overwrite a staff assignment.
    if record.assigned_to and not sr.assigned_to:
        sr.assigned_to = record.assigned_to[:100]

    from app.models import RequestComment
    summary = f"[{integration.display_name}] Work order update — " + "; ".join(bits)
    # De-dupe: skip if the most recent integration note is identical.
    last = (await db.execute(
        select(RequestComment).where(
            RequestComment.service_request_id == sr.id,
            RequestComment.username == integration.display_name,
        ).order_by(RequestComment.id.desc()).limit(1)
    )).scalar_one_or_none()
    if last and last.content == summary:
        return False
    db.add(RequestComment(
        service_request_id=sr.id,
        username=integration.display_name,
        content=summary,
        visibility="internal",
    ))
    return True


_MAX_MEDIA = 3
_MAX_MEDIA_BYTES = 15 * 1024 * 1024  # 15 MB per photo


async def _decode_media(sr: ServiceRequest, max_items: int = _MAX_MEDIA):
    """Resolve a request's photos to (filename, bytes, content_type) tuples.

    Handles both embedded base64 data-URIs and http(s)-hosted images — the
    latter are downloaded (SSRF-guarded, size-capped) so an externally-hosted
    photo actually attaches to the work order instead of being skipped."""
    from app.integrations.base import _assert_public_url, HTTP_TIMEOUT
    import httpx

    documents = []
    for i, url in enumerate((sr.media_urls or [])[:max_items]):
        if not isinstance(url, str):
            continue
        match = _DATA_URI_RE.match(url)
        if match:
            mime, b64 = match.groups()
            try:
                content = base64.b64decode(b64)
            except Exception:
                continue
            ext = _EXT_BY_MIME.get(mime, "bin")
            documents.append((f"{sr.service_request_id}-photo-{i + 1}.{ext}", content, mime))
            continue
        if url.startswith(("http://", "https://")):
            try:
                _assert_public_url(url)
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    content = resp.content
                    if not content or len(content) > _MAX_MEDIA_BYTES:
                        continue
                    mime = (resp.headers.get("content-type") or "application/octet-stream").split(";")[0].strip()
                    if not mime.startswith("image/"):
                        continue
                    ext = _EXT_BY_MIME.get(mime, "bin")
                    documents.append((f"{sr.service_request_id}-photo-{i + 1}.{ext}", content, mime))
            except Exception as e:
                logger.debug(f"[Integrations] Could not fetch hosted photo for {sr.service_request_id}: {e}")
                continue
    return documents


async def _push_documents(db, connector, integration, link, sr):
    """Upload any not-yet-pushed photos to the linked external record. Tracks a
    per-link count so photos added after the initial push sync on a later run
    (e.g. on the next status change)."""
    if "documents" not in connector.capabilities:
        return
    already = link.documents_pushed_count or 0
    documents = await _decode_media(sr)
    new_docs = documents[already:]
    if not new_docs:
        return
    pushed = 0
    try:
        for filename, content, mime in new_docs:
            await connector.push_document(link.external_id, filename, content, mime)
            pushed += 1
        link.documents_pushed_count = already + pushed
        await _log(db, integration.id, "push_documents", "success",
                   f"{sr.service_request_id}: {pushed} photo(s) attached", pushed)
    except Exception as e:
        # Persist however many succeeded so a retry doesn't re-upload them.
        link.documents_pushed_count = already + pushed
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
        last_pulled_at=datetime.now(timezone.utc),
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
    from app.integrations import build_connector_for

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
                    connector = await build_connector_for(integration)
                    if "push" not in connector.capabilities:
                        continue
                    # Behind the breaker. Without it a vendor that is properly
                    # down makes every queued report pay the full retry budget --
                    # three attempts and up to eight seconds of backoff each --
                    # before failing anyway, and the worker pool fills behind a
                    # service that is not coming back this minute. This also
                    # records the outcome, so the admin badge reflects real
                    # pushes rather than only whenever someone pressed Test.
                    payload = _build_payload(sr, integration.config or {}, await _dept_name(db, sr))
                    record = await guard(
                        health_key(integration.platform),
                        lambda: connector.push_request(payload),
                        db=db,
                        provider=integration.platform,
                    )
                    link = IntegrationLink(
                        integration_id=integration.id,
                        service_request_id=sr.id,
                        external_id=record.external_id,
                        external_status=record.raw_status,
                        direction="pushed",
                        last_pushed_at=datetime.now(timezone.utc),
                    )
                    db.add(link)
                    await _log(db, integration.id, "push", "success",
                               f"{sr.service_request_id} -> {record.external_id}", 1)
                    logger.info(f"[Integrations] Pushed {sr.service_request_id} to {integration.platform} as {record.external_id}")
                    # Attach embedded photos to the newly created external record
                    await _push_documents(db, connector, integration, link, sr)
                    await db.commit()
                except Exception as e:
                    # Without this a DB-level failure leaves the session in
                    # PendingRollbackError, so `_log`'s own commit raises too and
                    # the remaining integrations in this loop are never tried --
                    # one vendor's problem silently becoming every vendor's.
                    await db.rollback()
                    await _log(db, integration.id, "push", "error",
                               f"{sr.service_request_id}: {e}")
                    logger.warning(f"[Integrations] Push to {integration.platform} failed: {e}")

    run_async(_push())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def push_status_to_integrations(self, request_id: int, notes: str = None):
    """Propagate a local status change to all platforms the request is linked to."""
    from app.integrations import build_connector_for

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
                # Read while the session is certainly usable. After a rollback
                # the instance is expired, and building an UPDATE from it would
                # need to re-read the primary key -- a lazy load, which under the
                # async engine raises rather than quietly querying.
                link_id = link.id
                try:
                    connector = await build_connector_for(integration)
                    if "push_status" not in connector.capabilities:
                        continue
                    await guard(
                        health_key(integration.platform),
                        lambda: connector.push_status(link.external_id, sr.status, notes),
                        db=db,
                        provider=integration.platform,
                    )
                    link.external_status = connector.map_status_out(sr.status)
                    link.last_pushed_at = datetime.now(timezone.utc)
                    link.sync_error = None
                    await _log(db, integration.id, "push_status", "success",
                               f"{sr.service_request_id} -> {sr.status}", 1)
                    # Attach any photos added since the last push (idempotent).
                    await _push_documents(db, connector, integration, link, sr)
                except Exception as e:
                    # Same reason as the create path: a poisoned session makes
                    # `_log` raise on its commit and abandons every integration
                    # after this one.
                    await db.rollback()
                    # By id rather than through the expired instance, and issued
                    # after the rollback so it is not discarded by it.
                    await db.execute(
                        update(IntegrationLink)
                        .where(IntegrationLink.id == link_id)
                        .values(sync_error=str(e)[:1000])
                    )
                    await _log(db, integration.id, "push_status", "error",
                               f"{sr.service_request_id}: {e}")
                    logger.warning(f"[Integrations] Status push to {integration.platform} failed: {e}")
            await db.commit()

    run_async(_push_status())


@celery_app.task
def pull_integration_updates(integration_id: Optional[int] = None):
    """Poll pull-enabled platforms and mirror external status changes.

    Runs on the beat over every enabled integration, or over one of them when an
    admin presses "Check for updates" on a card. Scoping matters beyond
    tidiness: the unscoped version meant pressing the button on a newly
    configured connector also polled every other vendor the town uses, so a
    broken one wrote an error row to its sync log at a moment nobody had asked
    it to do anything -- and the admin watching a different card had no way to
    connect the two.
    """
    from app.integrations import build_connector_for

    async def _pull():
        async with SessionLocal() as db:
            query = select(IntegrationConfig).where(
                IntegrationConfig.enabled == True,  # noqa: E712
                IntegrationConfig.sync_direction.in_(["pull", "bidirectional"]),
            )
            if integration_id is not None:
                query = query.where(IntegrationConfig.id == integration_id)
            integrations = (await db.execute(query)).scalars().all()

            for integration in integrations:
                # Read while the session is certainly usable; see the error
                # handler below for why they cannot be read from the instance
                # after a rollback.
                integration_id, platform = integration.id, integration.platform
                try:
                    connector = await build_connector_for(integration)
                    if "pull" not in connector.capabilities:
                        continue
                    # Stamped before the fetch, not after it. `last_sync_at` used
                    # to be set to now() once the records were in hand, so
                    # anything the vendor changed *while* we were fetching --
                    # a poll spanning several pages of a slow API can take
                    # tens of seconds -- fell into a window that the next run
                    # started after. Those updates were skipped forever, and
                    # nothing anywhere would ever have said so.
                    started_at = datetime.now(timezone.utc)
                    # Behind the same breaker, and recorded to the same health
                    # row, as a resident-report push. The poll used to call the
                    # connector directly, so a vendor that had stopped answering
                    # failed here every fifteen minutes and the only trace was
                    # `last_sync_error` -- which nothing reads. Health said
                    # "working" on the strength of whatever push last succeeded,
                    # the daily sweep was the first thing to notice, and until it
                    # ran the badge was green while nothing came back.
                    records = await guard(
                        health_key(platform),
                        lambda: connector.pull_updates(since=_pull_since(integration)),
                        db=db,
                        provider=platform,
                    )
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
                        link.last_pulled_at = datetime.now(timezone.utc)
                        if record.raw_status and record.raw_status != link.external_status:
                            link.external_status = record.raw_status
                        sr = (await db.execute(
                            select(ServiceRequest).where(ServiceRequest.id == link.service_request_id)
                        )).scalar_one_or_none()
                        if not sr:
                            continue

                        # Reflect work-order fields (assignment/schedule/
                        # resolution) as an internal timeline note — these often
                        # change without a status change, so do it first.
                        if await _apply_work_order_fields(db, sr, record, integration):
                            updated += 1

                        # Status change (if any)
                        if not record.status or sr.status == record.status:
                            continue
                        old_status = sr.status
                        sr.status = record.status
                        sr.updated_datetime = datetime.now(timezone.utc)
                        if record.status == "closed":
                            sr.closed_datetime = datetime.now(timezone.utc)
                            if record.resolution and not sr.completion_message:
                                sr.completion_message = record.resolution
                            elif record.status_notes:
                                sr.completion_message = record.status_notes
                            if not sr.closed_substatus:
                                sr.closed_substatus = "resolved"
                        db.add(RequestAuditLog(
                            service_request_id=sr.id,
                            action="status_change",
                            old_value=old_status,
                            new_value=record.status,
                            actor_type="integration",
                            actor_name=integration.display_name,
                        ))
                        updated += 1

                    integration.last_sync_at = started_at
                    integration.last_sync_status = "success"
                    integration.last_sync_error = None
                    newest = _newest_change(records)
                    await _log(db, integration.id, "pull", "success",
                               f"{len(records)} record(s) fetched, {updated} status change(s) applied, "
                               f"{imported} new request(s) imported"
                               + (f", newest change {newest.isoformat()}" if newest else ""),
                               len(records))
                except CircuitOpen as e:
                    # Already known to be down; `guard` declined the call rather
                    # than making it. Not recorded as a new failure -- the
                    # failures that opened the circuit are in the row already,
                    # and counting a call we chose not to make would inflate the
                    # number that decides blip from outage.
                    await db.rollback()
                    await _log(db, integration_id, "pull", "skipped", str(e))
                    continue
                except Exception as e:
                    # Clear any pending-rollback state before writing the error
                    # log, so one bad record can't poison the whole beat cycle.
                    await db.rollback()
                    # `last_sync_at` is deliberately left where it was. It is the
                    # watermark the next poll reads from, and moving it after a
                    # failed fetch would step over the very window that failed --
                    # so a vendor outage of one beat interval would permanently
                    # lose every change made during it. The status and error
                    # below are what tell the admin the last attempt failed.
                    #
                    # Written by id: after the rollback the instance is expired,
                    # and assembling an UPDATE from it needs a lazy re-read of
                    # the primary key, which raises under the async engine.
                    await db.execute(
                        update(IntegrationConfig)
                        .where(IntegrationConfig.id == integration_id)
                        .values(last_sync_status="error", last_sync_error=str(e)[:1000])
                    )
                    await _log(db, integration_id, "pull", "error", str(e))
                    logger.warning(f"[Integrations] Pull from {platform} failed: {e}")
            await db.commit()

    run_async(_pull())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def refresh_request_from_integrations(self, request_id: int):
    """On-demand: pull the latest work-order state for ONE request from each
    platform it's linked to (uses the connector's fetch_record). Lets staff hit
    "Refresh work order" and see current assignment/schedule/status without
    waiting for the scheduled pull. Returns a small summary dict."""
    from app.integrations import build_connector_for

    async def _refresh():
        applied = 0
        async with SessionLocal() as db:
            sr = (await db.execute(
                select(ServiceRequest).where(ServiceRequest.id == request_id)
            )).scalar_one_or_none()
            if not sr:
                return {"ok": False, "detail": "Request not found"}

            links = (await db.execute(
                select(IntegrationLink).where(IntegrationLink.service_request_id == sr.id)
            )).scalars().all()
            for link in links:
                integration = (await db.execute(
                    select(IntegrationConfig).where(
                        IntegrationConfig.id == link.integration_id,
                        IntegrationConfig.enabled == True,  # noqa: E712
                    )
                )).scalar_one_or_none()
                if not integration:
                    continue
                try:
                    connector = await build_connector_for(integration)
                    record = await connector.fetch_record(link.external_id)
                    if not record:
                        continue
                    if record.raw_status and record.raw_status != link.external_status:
                        link.external_status = record.raw_status
                    link.last_pulled_at = datetime.now(timezone.utc)
                    if await _apply_work_order_fields(db, sr, record, integration):
                        applied += 1
                    if record.status and record.status != sr.status:
                        old = sr.status
                        sr.status = record.status
                        sr.updated_datetime = datetime.now(timezone.utc)
                        if record.status == "closed":
                            sr.closed_datetime = datetime.now(timezone.utc)
                            if record.resolution and not sr.completion_message:
                                sr.completion_message = record.resolution
                            if not sr.closed_substatus:
                                sr.closed_substatus = "resolved"
                        db.add(RequestAuditLog(
                            service_request_id=sr.id, action="status_change",
                            old_value=old, new_value=record.status,
                            actor_type="integration", actor_name=integration.display_name,
                        ))
                        applied += 1
                except Exception as e:
                    logger.warning(f"[Integrations] Refresh from {integration.platform} failed: {e}")
            await db.commit()
        return {"ok": True, "applied": applied}

    return run_async(_refresh())


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def push_comment_to_integrations(self, comment_id: int):
    """Post an external-visibility comment to every platform its request is linked to."""
    from app.integrations import build_connector_for

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
                    connector = await build_connector_for(integration)
                    if "comments" not in connector.capabilities:
                        continue
                    external_comment_id = await connector.push_comment(
                        link.external_id, comment.username, comment.content
                    )
                    # Track what we sent so pulls don't re-import our own
                    # comments. Store the external id when the platform returns
                    # one, plus a content fingerprint as a fallback for
                    # platforms that return no id on create (else our own
                    # comment echoes back as a duplicate on the next pull).
                    markers = [_comment_fp(comment.content)]
                    if external_comment_id:
                        markers.append(external_comment_id)
                    link.pushed_comment_ids = [*(link.pushed_comment_ids or []), *markers]
                    await _log(db, integration.id, "push_comment", "success",
                               f"comment {comment.id} -> {link.external_id}", 1)
                except Exception as e:
                    await db.rollback()
                    await _log(db, integration.id, "push_comment", "error",
                               f"comment {comment.id}: {e}")
                    logger.warning(f"[Integrations] Comment push to {integration.platform} failed: {e}")
            await db.commit()

    run_async(_push_comment())


@celery_app.task
def pull_integration_comments(integration_id: Optional[int] = None):
    """Import new external comments on linked, active requests.

    Scoped to one integration when an admin asked for one; see
    pull_integration_updates for why that matters.
    """
    from app.integrations import build_connector_for

    async def _pull_comments():
        async with SessionLocal() as db:
            query = select(IntegrationConfig).where(
                IntegrationConfig.enabled == True,  # noqa: E712
                IntegrationConfig.sync_direction.in_(["pull", "bidirectional"]),
            )
            if integration_id is not None:
                query = query.where(IntegrationConfig.id == integration_id)
            integrations = (await db.execute(query)).scalars().all()

            for integration in integrations:
                try:
                    connector = await build_connector_for(integration)
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
                            # Skip our own outbound comments echoing back —
                            # match on external id or on content fingerprint
                            # (covers platforms that returned no id on create).
                            if ec.external_id in pushed_ids or _comment_fp(ec.content) in pushed_ids:
                                continue
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
                        link.last_pulled_at = datetime.now(timezone.utc)

                    if imported or links:
                        await _log(db, integration.id, "pull_comments", "success",
                                   f"{len(links)} request(s) polled, {imported} comment(s) imported",
                                   imported)
                except Exception as e:
                    await db.rollback()
                    # Recorded, like every other real call to this vendor. A
                    # connector whose comment poll fails every fifteen minutes is
                    # a connector that is not working, and this path used to
                    # write a sync-log line no health surface reads.
                    await connector_health.record_failure(
                        db, health_key(integration.platform), e,
                        provider=integration.platform)
                    await _log(db, integration.id, "pull_comments", "error", str(e))
                    logger.warning(f"[Integrations] Comment pull from {integration.platform} failed: {e}")
            await db.commit()

    run_async(_pull_comments())


@celery_app.task
def sync_integration_assets(integration_id: Optional[int] = None):
    """Mirror external asset inventories into Pinpoint map layers.

    Synced assets become a point layer usable for asset-linked request intake
    (residents pick the exact hydrant/streetlight/sign the report is about).

    On the nightly beat this covers every integration with config.sync_assets
    set. Called with an `integration_id` it runs that one regardless of the flag:
    an admin pressing "Sync assets now" is asking for this run and only this run.
    The endpoint used to grant the request by *setting* the flag, which enrolled
    the integration in the nightly job permanently, with no UI indication and no
    way back.
    """
    from app.integrations import build_connector_for

    async def _sync_assets():
        async with SessionLocal() as db:
            query = select(IntegrationConfig).where(
                IntegrationConfig.enabled == True  # noqa: E712
            )
            if integration_id is not None:
                query = query.where(IntegrationConfig.id == integration_id)
            integrations = (await db.execute(query)).scalars().all()

            for integration in integrations:
                config = integration.config or {}
                # The flag governs the unattended nightly pass only. A one-off
                # asked for by name does not need permission to be asked for.
                if integration_id is None and not _flag(config, "sync_assets"):
                    continue
                try:
                    connector = await build_connector_for(integration)
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
                        layer.updated_at = datetime.now(timezone.utc)
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
                    await db.rollback()
                    await connector_health.record_failure(
                        db, health_key(integration.platform), e,
                        provider=integration.platform)
                    await _log(db, integration.id, "sync_assets", "error", str(e))
                    logger.warning(f"[Integrations] Asset sync from {integration.platform} failed: {e}")
            await db.commit()

    run_async(_sync_assets())
