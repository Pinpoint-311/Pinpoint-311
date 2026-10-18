"""Admin endpoints for the Open311 interface: API keys and the Open311 switches.

Mounted by app/api/open311.py at /api/open311/v2/admin. Admin-only. Keys are
shown in plaintext exactly once, in the create response; every list and
revoke answer carries the prefix and metadata only. Each create, revoke and
settings change writes an AuditService entry naming the admin -- the
/api/open311/ prefix is skipped by the catch-all audit middleware, so these
handlers record their own.
"""

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_admin
from app.db.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


class Open311KeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    contact_email: EmailStr
    rate_limit_per_minute: Optional[int] = Field(None, ge=1, le=600)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        return v


class Open311KeyResponse(BaseModel):
    id: int
    name: str
    contact_email: str
    key_prefix: str
    rate_limit_per_minute: Optional[int] = None
    effective_rate_limit_per_minute: int
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    status: str


class Open311KeyCreated(Open311KeyResponse):
    # The only time the plaintext exists outside the integrator's hands.
    api_key: str


class Open311SettingsResponse(BaseModel):
    allow_anonymous_submissions: bool
    jurisdiction_id: Optional[str] = None
    anonymous_rate_limit: str
    default_key_rate_limit_per_minute: int


class Open311SettingsUpdate(BaseModel):
    allow_anonymous_submissions: Optional[bool] = None
    # "" clears it.
    jurisdiction_id: Optional[str] = Field(None, max_length=100)


def _describe(row) -> dict:
    from app.services import open311_keys
    return {
        "id": row.id,
        "name": row.name,
        "contact_email": row.contact_email,
        "key_prefix": row.key_prefix,
        "rate_limit_per_minute": row.rate_limit_per_minute,
        "effective_rate_limit_per_minute": open311_keys.key_limit_per_minute(row),
        "created_by": row.created_by,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "revoked_at": row.revoked_at,
        "revoked_by": row.revoked_by,
        "status": "revoked" if row.revoked_at else "active",
    }


async def _audit(db, request: Request, admin, event_type: str, details: dict) -> None:
    """One AuditService line. A failure is logged, never surfaced: the change
    it describes has already been committed."""
    try:
        from app.core.client_ip import client_ip
        ip = client_ip(request)
    except Exception:
        ip = None
    try:
        from app.services.audit_service import AuditService
        await AuditService.log_event(
            db,
            event_type=event_type,
            success=True,
            username=getattr(admin, "username", None),
            user_id=getattr(admin, "id", None),
            ip_address=ip,
            user_agent=(request.headers.get("user-agent") or "")[:500] or None,
            details=details,
        )
    except Exception:
        logger.warning("[Open311] could not write the %s audit entry", event_type, exc_info=True)


@router.get("/keys", response_model=List[Open311KeyResponse])
async def list_open311_keys(
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """List Open311 API keys: prefix and metadata, never the key (admin)."""
    from app.models import Open311ApiKey
    rows = (await db.execute(select(Open311ApiKey).order_by(Open311ApiKey.created_at.desc(),
                                                             Open311ApiKey.id.desc()))).scalars().all()
    return [_describe(r) for r in rows]


@router.post("/keys", response_model=Open311KeyCreated, status_code=status.HTTP_201_CREATED)
async def create_open311_key(
    body: Open311KeyCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Issue an Open311 API key. The plaintext is in this response and nowhere else (admin)."""
    from app.models import Open311ApiKey
    from app.services import open311_keys

    plaintext, prefix, digest = open311_keys.generate_key()
    row = Open311ApiKey(
        name=body.name,
        contact_email=str(body.contact_email),
        key_prefix=prefix,
        key_hash=digest,
        rate_limit_per_minute=body.rate_limit_per_minute,
        created_by=getattr(admin, "username", None),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    await _audit(db, request, admin, "open311_api_key_created", {
        "key_id": row.id, "name": row.name, "key_prefix": row.key_prefix,
        "contact_email": row.contact_email, "rate_limit_per_minute": row.rate_limit_per_minute,
    })
    return {**_describe(row), "api_key": plaintext}


@router.post("/keys/{key_id}/revoke", response_model=Open311KeyResponse)
async def revoke_open311_key(
    key_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Revoke an Open311 API key. Takes effect on the next request (admin).

    Revoking an already-revoked key changes nothing and is not re-audited.
    """
    from datetime import timezone
    from app.models import Open311ApiKey

    row = (await db.execute(select(Open311ApiKey).where(Open311ApiKey.id == key_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_by = getattr(admin, "username", None)
        await db.commit()
        await db.refresh(row)
        await _audit(db, request, admin, "open311_api_key_revoked", {
            "key_id": row.id, "name": row.name, "key_prefix": row.key_prefix,
        })
    return _describe(row)


def _settings_payload(config) -> dict:
    from app.services import open311_keys
    return {
        "allow_anonymous_submissions": config.allow_anonymous_submissions,
        "jurisdiction_id": config.jurisdiction_id,
        "anonymous_rate_limit": open311_keys.ANONYMOUS_LIMIT,
        "default_key_rate_limit_per_minute": open311_keys.DEFAULT_KEY_LIMIT_PER_MINUTE,
    }


@router.get("/settings", response_model=Open311SettingsResponse)
async def get_open311_settings(
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """The Open311 switches (admin)."""
    from app.services import open311_keys
    return _settings_payload(await open311_keys.read_settings(db))


@router.put("/settings", response_model=Open311SettingsResponse)
async def update_open311_settings(
    body: Open311SettingsUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin=Depends(get_current_admin),
):
    """Change the Open311 switches; each change is audited (admin)."""
    from app.models import Open311Settings
    from app.services import open311_keys

    row = (await db.execute(select(Open311Settings).order_by(Open311Settings.id).limit(1))).scalar_one_or_none()
    if row is None:
        row = Open311Settings(allow_anonymous_submissions=False, jurisdiction_id=None)
        db.add(row)

    changes = []
    if body.allow_anonymous_submissions is not None and \
            bool(row.allow_anonymous_submissions) != body.allow_anonymous_submissions:
        changes.append(("open311_anonymous_submissions_changed", {
            "from": bool(row.allow_anonymous_submissions), "to": body.allow_anonymous_submissions}))
        row.allow_anonymous_submissions = body.allow_anonymous_submissions
    if body.jurisdiction_id is not None:
        new_id = body.jurisdiction_id.strip() or None
        if (row.jurisdiction_id or None) != new_id:
            changes.append(("open311_jurisdiction_changed", {"from": row.jurisdiction_id, "to": new_id}))
            row.jurisdiction_id = new_id
    if changes:
        row.updated_by = getattr(admin, "username", None)
    await db.commit()
    for event_type, details in changes:
        await _audit(db, request, admin, event_type, details)
    return _settings_payload(await open311_keys.read_settings(db))
