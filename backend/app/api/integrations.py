"""Admin API for external govtech platform integrations, plus the inbound
webhook endpoint that lets connected platforms (e.g. Polimorphic's AI intake)
create and update requests in Pinpoint."""

import logging
import secrets as pysecrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin, get_current_staff
from app.db.session import get_db
from app.integrations import PLATFORM_CATALOG, build_connector
from app.models import (
    IntegrationConfig,
    IntegrationLink,
    IntegrationSyncLog,
    RequestAuditLog,
    ServiceDefinition,
    ServiceRequest,
    User,
)

limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

router = APIRouter()


# ---------- Schemas ----------

class IntegrationCreate(BaseModel):
    platform: str
    display_name: Optional[str] = None
    enabled: bool = False
    sync_direction: str = Field(default="push", pattern="^(push|pull|bidirectional)$")
    config: Dict[str, Any] = {}
    credentials: Dict[str, str] = {}


class IntegrationUpdate(BaseModel):
    display_name: Optional[str] = None
    enabled: Optional[bool] = None
    sync_direction: Optional[str] = Field(default=None, pattern="^(push|pull|bidirectional)$")
    config: Optional[Dict[str, Any]] = None
    # Only keys present are updated; empty-string values are ignored (keep existing)
    credentials: Optional[Dict[str, str]] = None


class WebhookRequestIn(BaseModel):
    """Normalized inbound payload external platforms POST to the webhook."""
    external_id: str = Field(..., max_length=200)
    description: str = Field(..., min_length=1, max_length=10000)
    service_code: Optional[str] = None
    status: Optional[str] = Field(default=None, pattern="^(open|in_progress|closed)$")
    address: Optional[str] = Field(default=None, max_length=500)
    lat: Optional[float] = None
    long: Optional[float] = None
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=30)
    media_urls: Optional[List[str]] = None


def _serialize(integration: IntegrationConfig) -> Dict[str, Any]:
    catalog = PLATFORM_CATALOG.get(integration.platform, {})
    return {
        "id": integration.id,
        "platform": integration.platform,
        "platform_name": catalog.get("name", integration.platform),
        "display_name": integration.display_name,
        "enabled": integration.enabled,
        "sync_direction": integration.sync_direction,
        "config": integration.config or {},
        # Never return secret values — only which keys are set
        "configured_credentials": sorted((integration.credentials or {}).keys()),
        "webhook_path": f"/api/integrations/webhook/{integration.platform}/{integration.webhook_token}",
        "last_sync_at": integration.last_sync_at.isoformat() if integration.last_sync_at else None,
        "last_sync_status": integration.last_sync_status,
        "last_sync_error": integration.last_sync_error,
        "created_at": integration.created_at.isoformat() if integration.created_at else None,
    }


async def _get_integration(db: AsyncSession, integration_id: int) -> IntegrationConfig:
    integration = (await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.id == integration_id)
    )).scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


# ---------- Catalog & CRUD (admin) ----------

@router.get("/catalog")
async def get_platform_catalog(_: User = Depends(get_current_staff)):
    """List all supported govtech platforms and the fields each requires."""
    return [{"platform": key, **meta} for key, meta in PLATFORM_CATALOG.items()]


@router.get("")
async def list_integrations(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    integrations = (await db.execute(
        select(IntegrationConfig).order_by(IntegrationConfig.created_at.asc())
    )).scalars().all()
    return [_serialize(i) for i in integrations]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_integration(
    data: IntegrationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if data.platform not in PLATFORM_CATALOG:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {data.platform}")

    existing = (await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.platform == data.platform)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail=f"An integration for {data.platform} already exists")

    integration = IntegrationConfig(
        platform=data.platform,
        display_name=data.display_name or PLATFORM_CATALOG[data.platform]["name"],
        enabled=data.enabled,
        sync_direction=data.sync_direction,
        config=data.config,
        webhook_token=pysecrets.token_urlsafe(32),
    )
    integration.credentials = {k: v for k, v in (data.credentials or {}).items() if v}
    db.add(integration)
    await db.commit()
    await db.refresh(integration)
    logger.info(f"[Integrations] {current_user.username} created integration {data.platform}")
    return _serialize(integration)


@router.put("/{integration_id}")
async def update_integration(
    integration_id: int,
    data: IntegrationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)

    if data.display_name is not None:
        integration.display_name = data.display_name
    if data.enabled is not None:
        integration.enabled = data.enabled
    if data.sync_direction is not None:
        integration.sync_direction = data.sync_direction
    if data.config is not None:
        integration.config = {**(integration.config or {}), **data.config}
    if data.credentials:
        merged = integration.credentials
        for key, value in data.credentials.items():
            if value:  # blank means "keep existing"
                merged[key] = value
        integration.credentials = merged

    integration.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(integration)
    logger.info(f"[Integrations] {current_user.username} updated integration {integration.platform}")
    return _serialize(integration)


@router.delete("/{integration_id}")
async def delete_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    platform = integration.platform
    await db.delete(integration)
    await db.commit()
    logger.info(f"[Integrations] {current_user.username} deleted integration {platform}")
    return {"message": "Integration deleted", "platform": platform}


# ---------- Actions ----------

@router.post("/{integration_id}/test")
async def test_integration(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    try:
        connector = build_connector(
            integration.platform, integration.config or {}, integration.credentials
        )
        result = await connector.test_connection()
        log_status, detail = "success", result.get("detail", "OK")
    except Exception as e:
        result = {"ok": False, "detail": str(e)}
        log_status, detail = "error", str(e)

    db.add(IntegrationSyncLog(
        integration_id=integration.id, operation="test", status=log_status, detail=detail[:2000]
    ))
    await db.commit()
    return result


@router.post("/{integration_id}/sync")
async def trigger_sync(
    integration_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    integration = await _get_integration(db, integration_id)
    if not integration.enabled:
        raise HTTPException(status_code=400, detail="Enable the integration before syncing")
    from app.tasks.integrations import pull_integration_updates
    pull_integration_updates.delay()
    return {"message": "Sync started", "platform": integration.platform}


@router.get("/{integration_id}/logs")
async def get_sync_logs(
    integration_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    await _get_integration(db, integration_id)
    logs = (await db.execute(
        select(IntegrationSyncLog)
        .where(IntegrationSyncLog.integration_id == integration_id)
        .order_by(IntegrationSyncLog.created_at.desc())
        .limit(min(limit, 200))
    )).scalars().all()
    return [
        {
            "id": entry.id,
            "operation": entry.operation,
            "status": entry.status,
            "detail": entry.detail,
            "request_count": entry.request_count,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
        for entry in logs
    ]


@router.get("/requests/{service_request_id}/links")
async def get_request_links(
    service_request_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """External platform records linked to a service request (staff view)."""
    sr = (await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == service_request_id)
    )).scalar_one_or_none()
    if not sr:
        raise HTTPException(status_code=404, detail="Request not found")

    rows = (await db.execute(
        select(IntegrationLink, IntegrationConfig)
        .join(IntegrationConfig, IntegrationLink.integration_id == IntegrationConfig.id)
        .where(IntegrationLink.service_request_id == sr.id)
    )).all()
    return [
        {
            "platform": integration.platform,
            "platform_name": integration.display_name,
            "external_id": link.external_id,
            "external_status": link.external_status,
            "direction": link.direction,
            "last_pushed_at": link.last_pushed_at.isoformat() if link.last_pushed_at else None,
            "last_pulled_at": link.last_pulled_at.isoformat() if link.last_pulled_at else None,
            "sync_error": link.sync_error,
        }
        for link, integration in rows
    ]


# ---------- Inbound webhook (no session auth — token in path) ----------

@router.post("/webhook/{platform}/{token}", status_code=status.HTTP_201_CREATED)
@limiter.limit("60/minute")
async def integration_webhook(
    request: Request,
    platform: str,
    token: str,
    payload: WebhookRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Inbound intake from a connected platform.

    Creates a new service request (or updates the status of the already-linked
    one when the same external_id is posted again). Authenticated by the
    per-integration webhook token."""
    integration = (await db.execute(
        select(IntegrationConfig).where(
            IntegrationConfig.platform == platform,
            IntegrationConfig.webhook_token == token,
            IntegrationConfig.enabled == True,  # noqa: E712
        )
    )).scalar_one_or_none()
    if not integration:
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # Existing link -> status update
    link = (await db.execute(
        select(IntegrationLink).where(
            IntegrationLink.integration_id == integration.id,
            IntegrationLink.external_id == payload.external_id,
        )
    )).scalar_one_or_none()
    if link:
        sr = (await db.execute(
            select(ServiceRequest).where(ServiceRequest.id == link.service_request_id)
        )).scalar_one_or_none()
        if sr and payload.status and payload.status != sr.status:
            old_status = sr.status
            sr.status = payload.status
            sr.updated_datetime = datetime.utcnow()
            if payload.status == "closed":
                sr.closed_datetime = datetime.utcnow()
            db.add(RequestAuditLog(
                service_request_id=sr.id,
                action="status_change",
                old_value=old_status,
                new_value=payload.status,
                actor_type="integration",
                actor_name=integration.display_name,
            ))
            await db.commit()
        return {"message": "updated", "service_request_id": sr.service_request_id if sr else None}

    # New record -> create a request
    service_code = payload.service_code or (integration.config or {}).get("default_local_service_code")
    service = None
    if service_code:
        service = (await db.execute(
            select(ServiceDefinition).where(
                ServiceDefinition.service_code == service_code,
                ServiceDefinition.is_active == True,  # noqa: E712
            )
        )).scalar_one_or_none()
    if not service:
        # Fall back to the first active service so intake never bounces
        service = (await db.execute(
            select(ServiceDefinition).where(ServiceDefinition.is_active == True).limit(1)  # noqa: E712
        )).scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=400, detail="No active service categories configured")

    from app.api.open311 import generate_request_id
    sr = ServiceRequest(
        service_request_id=generate_request_id(),
        service_code=service.service_code,
        service_name=service.service_name,
        description=payload.description,
        address=payload.address,
        lat=payload.lat,
        long=payload.long,
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email or f"integration-{integration.platform}@intake.local",
        phone=payload.phone,
        media_urls=[u for u in (payload.media_urls or []) if isinstance(u, str) and u.startswith("http")][:3],
        source=f"integration_{integration.platform}",
        status=payload.status or "open",
        assigned_department_id=service.assigned_department_id,
    )
    db.add(sr)
    await db.commit()
    await db.refresh(sr)

    db.add(IntegrationLink(
        integration_id=integration.id,
        service_request_id=sr.id,
        external_id=payload.external_id,
        external_status=payload.status,
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
    db.add(IntegrationSyncLog(
        integration_id=integration.id,
        operation="webhook",
        status="success",
        detail=f"{payload.external_id} -> {sr.service_request_id}",
        request_count=1,
    ))
    await db.commit()

    # Same post-processing as portal submissions (AI triage)
    try:
        from app.tasks.service_requests import analyze_request
        analyze_request.delay(sr.id)
    except Exception:
        logger.warning("[Integrations] Could not queue AI analysis for webhook intake")

    return {"message": "created", "service_request_id": sr.service_request_id}
