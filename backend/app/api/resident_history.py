"""Resident history: a resident's earlier reports, and search by resident.

An optional module, off by default (system_settings.modules.resident_history).
Two staff-only endpoints:

    GET  /api/resident-history/requests/{id}   earlier reports from the same
                                                 email as this one
    POST /api/resident-history/search          exact search by full email
                                                 address or full name

Resident PII stays encrypted with a random nonce per value; matching uses the
keyed fingerprints in ServiceRequest.resident_*_index (see core/resident_index).
The safeguards a government deployment expects, each enforced here rather than
in the UI:

  * Off unless the town turns it on, checked on every call (404 when off, the
    same as a route that does not exist).
  * Department scoping: only reports the caller could already open. The same
    filter as the request list, so the card never reveals that a Police
    complaint exists to a Parks clerk.
  * Minimum necessary: id, category, status and date. Never another report's
    description, address or contact details -- staff open the report itself
    (scoped and as usual) if they need it.
  * Exact match only. A partial or fuzzy match over PII would need the values
    in the clear; this needs only a fingerprint.
  * Every lookup is audited -- who, which report or which kind of search, how
    many results -- and never the email or name searched for. If the audit
    record cannot be written, the results are not returned (fail closed).
  * Search is POST so the email or name never appears in a URL, a proxy log
    or browser history.
  * Rate limited.
  * Retention: scrubbed reports have no fingerprint, so they never match.
"""
import asyncio
import hashlib
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.scoping import department_scope_filters, scoped_request
from app.core.auth import get_current_staff
from app.core.client_ip import rate_limit_key
from app.db.session import get_db
from app.models import ServiceRequest, SystemSettings, User
from app.services.admin_audit import record_admin_action

logger = logging.getLogger(__name__)

router = APIRouter()


def _per_account_key(request: Request) -> str:
    """Rate-limit per signed-in account, not per address: staff behind one town
    hall NAT would otherwise share a single allowance, and one account could
    spread its lookups across machines. The bearer token is hashed, never kept."""
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer ") and len(auth) > 7:
        return "acct:" + hashlib.sha256(auth[7:].encode("utf-8")).hexdigest()[:32]
    return rate_limit_key(request)


limiter = Limiter(key_func=_per_account_key)

MODULE_KEY = "resident_history"
CARD_LIMIT = 20
SEARCH_LIMIT = 50


class HistoryItem(BaseModel):
    service_request_id: str
    service_name: Optional[str] = None
    status: Optional[str] = None
    requested_datetime: Optional[datetime] = None


class HistoryResponse(BaseModel):
    matched_by: Optional[str] = None  # "email", or None when the report has no usable email
    total: int = 0
    reports: List[HistoryItem] = []


class ResidentSearch(BaseModel):
    email: Optional[str] = Field(default=None, max_length=320)
    name: Optional[str] = Field(default=None, max_length=200)


class SearchResponse(BaseModel):
    searched_by: str
    total: int = 0
    reports: List[HistoryItem] = []


async def _module_enabled(db: AsyncSession) -> bool:
    try:
        row = (
            await db.execute(select(SystemSettings).order_by(SystemSettings.id).limit(1))
        ).scalar_one_or_none()
        return bool(((row.modules if row else None) or {}).get(MODULE_KEY, False))
    except Exception as exc:  # pragma: no cover - defensive
        # Fail closed: an unreadable settings row must not switch PII lookup on.
        logger.warning("resident_history module check failed, treating as off: %s", exc)
        return False


def _off() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _key_unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                         detail="Resident lookup is unavailable because the key service can't be reached.")


def _audit_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="This lookup couldn't be recorded in the audit log, so it wasn't run. Try again shortly.",
    )


async def _matches(db: AsyncSession, user: User, column, fingerprint: str,
                   limit: int, exclude_id: Optional[int] = None):
    """Scoped reports sharing a fingerprint: (total, first `limit` rows)."""
    filters = [column == fingerprint, ServiceRequest.deleted_at.is_(None)]
    if exclude_id is not None:
        filters.append(ServiceRequest.id != exclude_id)
    filters.extend(await department_scope_filters(db, user))

    total = (await db.execute(select(func.count(ServiceRequest.id)).where(*filters))).scalar() or 0
    rows = (await db.execute(
        select(ServiceRequest.service_request_id, ServiceRequest.service_name,
               ServiceRequest.status, ServiceRequest.requested_datetime)
        .where(*filters)
        .order_by(ServiceRequest.requested_datetime.desc())
        .limit(limit)
    )).all()
    return total, [HistoryItem(service_request_id=r[0], service_name=r[1], status=r[2],
                               requested_datetime=r[3]) for r in rows]


@router.get("/requests/{service_request_id}", response_model=HistoryResponse)
@limiter.limit("60/minute")
async def history_for_request(
    request: Request,
    service_request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff),
):
    """Earlier reports from the same email address as this report.

    By email only, not name: two residents can share a name, and showing one
    person's reports on another's record is the error this card must not make.
    """
    if not await _module_enabled(db):
        raise _off()
    target = await scoped_request(db, current_user, service_request_id=service_request_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service request not found")

    from app.core import resident_index
    try:
        # Off the event loop: the first call in a process reads the key through
        # the town's KMS.
        key = await asyncio.to_thread(resident_index.ensure_key)
    except resident_index.IndexKeyUnavailable:
        raise _key_unavailable()
    # From the stored fingerprint, or computed now for a report written before
    # maintenance reached it -- the card should not say "no email" for that.
    fingerprint = target.resident_email_index or resident_index.email_index(target.email, key=key)

    if not fingerprint:
        result = HistoryResponse(matched_by=None)
    else:
        total, reports = await _matches(db, current_user, ServiceRequest.resident_email_index,
                                        fingerprint, CARD_LIMIT, exclude_id=target.id)
        result = HistoryResponse(matched_by="email", total=total, reports=reports)

    recorded = await record_admin_action(
        db, event_type="resident_history_viewed", actor=current_user,
        details={"service_request_id": target.service_request_id, "results": result.total},
    )
    if not recorded:
        raise _audit_failed()
    return result


@router.post("/search", response_model=SearchResponse)
@limiter.limit("20/minute")
async def search_by_resident(
    request: Request,
    body: ResidentSearch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff),
):
    """Reports filed under one full email address, or one full name."""
    if not await _module_enabled(db):
        raise _off()

    from app.core import resident_index

    email = (body.email or "").strip()
    name = (body.name or "").strip()
    if bool(email) == bool(name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Search by either a full email address or a full name.")

    try:
        key = await asyncio.to_thread(resident_index.ensure_key)
    except resident_index.IndexKeyUnavailable:
        raise _key_unavailable()

    if email:
        searched_by, column = "email", ServiceRequest.resident_email_index
        fingerprint = resident_index.email_index(email, key=key)
        if not fingerprint:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Enter the resident's full email address.")
    else:
        searched_by, column = "name", ServiceRequest.resident_name_index
        fingerprint = resident_index.name_index_from_full(name, key=key)
        if not fingerprint:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Enter the resident's first and last name.")

    total, reports = await _matches(db, current_user, column, fingerprint, SEARCH_LIMIT)

    # The kind of search and the count -- never the value searched for. The
    # audit log is itself read by administrators, and writing the email there
    # would make it a second, unencrypted copy of the PII.
    recorded = await record_admin_action(
        db, event_type="resident_search", actor=current_user,
        details={"searched_by": searched_by, "results": total},
    )
    if not recorded:
        raise _audit_failed()
    return SearchResponse(searched_by=searched_by, total=total, reports=reports)
