from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime
import uuid

from app.db.session import get_db
from app.models import ServiceRequest, ServiceDefinition, User, RequestAuditLog, Department
from app.schemas import (
    ServiceRequestCreate, ServiceRequestResponse, ServiceRequestDetailResponse,
    ServiceRequestUpdate, ServiceRequestDelete, ManualIntakeCreate, PublicServiceRequestResponse,
    RequestAuditLogResponse
)
from app.core.auth import get_current_staff

router = APIRouter()


def generate_request_id() -> str:
    """Generate unique request ID"""
    timestamp = datetime.now().strftime("%Y%m%d")
    unique = uuid.uuid4().hex[:8].upper()
    return f"REQ-{timestamp}-{unique}"


from app.core.config import get_settings
import redis.asyncio as redis
import json

# Redis cache for public requests (60s TTL)
_settings = get_settings()
redis_client = redis.from_url(_settings.redis_url, decode_responses=True)
CACHE_TTL = 60  # seconds


@router.get("/public/requests")
async def list_public_requests(
    status: Optional[str] = Query(None, description="Filter by status"),
    service_code: Optional[str] = Query(None, description="Filter by service category"),
    limit: Optional[int] = Query(None, ge=1, description="Max number of results (no limit by default)"),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """Public endpoint - List all requests WITHOUT personal information (cached)"""
    # Build cache key
    cache_key = f"public_requests:{status or 'all'}:{service_code or 'all'}:{limit}:{offset}"
    
    # Try cache first
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass  # Redis unavailable, proceed without cache
    
    query = select(ServiceRequest).where(ServiceRequest.deleted_at.is_(None))
    
    if status:
        query = query.where(ServiceRequest.status == status)
    if service_code:
        query = query.where(ServiceRequest.service_code == service_code)
    
    query = query.order_by(ServiceRequest.requested_datetime.desc())
    if limit:
        query = query.limit(limit)
    if offset:
        query = query.offset(offset)
    result = await db.execute(query)
    requests = result.scalars().all()
    
    # Build response - EXCLUDE large base64 media data for performance
    # Use has_media flags instead so frontend knows if media exists
    response_data = [
        {
            "service_request_id": r.service_request_id,
            "service_code": r.service_code,
            "service_name": r.service_name,
            "description": r.description[:500] if r.description else None,  # Truncate long descriptions
            "status": r.status,
            "address": r.address,
            "lat": r.lat,
            "long": r.long,
            "requested_datetime": r.requested_datetime.isoformat() if r.requested_datetime else None,
            "updated_datetime": r.updated_datetime.isoformat() if r.updated_datetime else None,
            "closed_substatus": r.closed_substatus,
            "media_urls": [],  # Excluded from list - use photo_count
            "photo_count": len(r.media_urls or []),  # Number of photos attached
            "completion_message": r.completion_message[:200] if r.completion_message else None,
            "completion_photo_url": None,  # Excluded from list - use has_completion_photo flag
            "has_completion_photo": bool(r.completion_photo_url),  # Flag indicating completion photo exists
            # Fields for map filtering
            "assigned_department_id": r.assigned_department_id,
            "assigned_to": r.assigned_to,
        }
        for r in requests
    ]
    
    # Cache the response
    try:
        await redis_client.setex(cache_key, CACHE_TTL, json.dumps(response_data))
    except Exception:
        pass  # Redis unavailable, continue without caching
    
    return response_data


@router.get("/public/requests/{request_id}")
async def get_public_request_detail(request_id: str, db: AsyncSession = Depends(get_db)):
    """Get full public request details including media - for detail view"""
    result = await db.execute(
        select(ServiceRequest).options(
            selectinload(ServiceRequest.assigned_department)
        ).where(
            ServiceRequest.service_request_id == request_id,
            ServiceRequest.deleted_at.is_(None)
        )
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Return full details including media and assignment (but still excluding PII)
    return {
        "service_request_id": request.service_request_id,
        "service_code": request.service_code,
        "service_name": request.service_name,
        "description": request.description,  # Full description
        "status": request.status,
        "address": request.address,
        "lat": request.lat,
        "long": request.long,
        "requested_datetime": request.requested_datetime.isoformat() if request.requested_datetime else None,
        "updated_datetime": request.updated_datetime.isoformat() if request.updated_datetime else None,
        "closed_substatus": request.closed_substatus,
        "media_urls": request.media_urls or [],  # Full array of photo data for detail view
        "completion_message": request.completion_message,
        "completion_photo_url": request.completion_photo_url,  # Full completion photo
        "assigned_to": request.assigned_to,
        "assigned_department_name": request.assigned_department.name if request.assigned_department else None,
    }


from app.models import RequestComment
from app.schemas import RequestCommentCreate, RequestCommentResponse


@router.get("/public/requests/{request_id}/comments", response_model=List[RequestCommentResponse])
async def get_public_comments(request_id: str, db: AsyncSession = Depends(get_db)):
    """Get external/public comments for a request - no auth required"""
    # Find the request
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Get only external comments
    comments_result = await db.execute(
        select(RequestComment)
        .where(RequestComment.service_request_id == request.id)
        .where(RequestComment.visibility == 'external')
        .order_by(RequestComment.created_at.asc())
    )
    return comments_result.scalars().all()


@router.post("/public/requests/{request_id}/comments", response_model=RequestCommentResponse)
async def add_public_comment(
    request_id: str,
    content: str = Query(..., min_length=1, max_length=1000),
    db: AsyncSession = Depends(get_db)
):
    """Add a public comment to a request - no auth required, always external visibility"""
    # Find the request
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Create external comment (anonymous - "Resident")
    comment = RequestComment(
        service_request_id=request.id,
        username="Resident",
        content=content,
        visibility="external"
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


# ============ Audit Log Endpoints ============

@router.get("/requests/{request_id}/audit-log", response_model=List[RequestAuditLogResponse])
async def get_audit_log(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Get audit log for a request (staff only - full history)"""
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    audit_result = await db.execute(
        select(RequestAuditLog)
        .where(RequestAuditLog.service_request_id == request.id)
        .order_by(RequestAuditLog.created_at.asc())
    )
    return audit_result.scalars().all()


@router.get("/public/requests/{request_id}/audit-log", response_model=List[RequestAuditLogResponse])
async def get_public_audit_log(request_id: str, db: AsyncSession = Depends(get_db)):
    """Get public audit log for a request - shows status changes only, no internal details"""
    result = await db.execute(
        select(ServiceRequest).where(
            ServiceRequest.service_request_id == request_id,
            ServiceRequest.deleted_at.is_(None)
        )
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Only return submitted and status_change events (not assignments which may be internal)
    audit_result = await db.execute(
        select(RequestAuditLog)
        .where(RequestAuditLog.service_request_id == request.id)
        .where(RequestAuditLog.action.in_(["submitted", "status_change"]))
        .order_by(RequestAuditLog.created_at.asc())
    )
    return audit_result.scalars().all()



@router.get("/services.json")
async def list_open311_services(db: AsyncSession = Depends(get_db)):
    """Open311 v2 compatible - List services"""
    result = await db.execute(
        select(ServiceDefinition).where(ServiceDefinition.is_active == True)
    )
    services = result.scalars().all()
    return [
        {
            "service_code": s.service_code,
            "service_name": s.service_name,
            "description": s.description,
            "type": "realtime",
            "keywords": s.service_name.lower(),
            "group": "municipal"
        }
        for s in services
    ]


@router.post("/requests.json", response_model=ServiceRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_request(
    request_data: ServiceRequestCreate,
    db: AsyncSession = Depends(get_db)
):
    """Open311 v2 compatible - Create a new service request (public)"""
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[CREATE REQUEST] Received: service_code={request_data.service_code}")
    
    # Validate service code
    result = await db.execute(
        select(ServiceDefinition).where(
            ServiceDefinition.service_code == request_data.service_code,
            ServiceDefinition.is_active == True
        )
    )
    service = result.scalar_one_or_none()
    
    if not service:
        logger.error(f"[CREATE REQUEST] Invalid service code: {request_data.service_code}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid service code: {request_data.service_code}"
        )
    
    # Auto-assignment based on service routing config
    assigned_department_id = service.assigned_department_id
    assigned_to = None
    
    if service.routing_config:
        config = service.routing_config
        # If routing to specific staff, pick the first one
        if config.get('route_to') == 'specific_staff' and config.get('staff_ids'):
            from app.models import User
            staff_ids = config.get('staff_ids', [])
            if staff_ids:
                # Get the first available staff member
                staff_result = await db.execute(
                    select(User).where(User.id == staff_ids[0])
                )
                staff = staff_result.scalar_one_or_none()
                if staff:
                    assigned_to = staff.username
    
    # Create request with auto-assignment
    service_request = ServiceRequest(
        service_request_id=generate_request_id(),
        service_code=request_data.service_code,
        service_name=service.service_name,
        description=request_data.description,
        address=request_data.address,
        lat=request_data.lat,
        long=request_data.long,
        first_name=request_data.first_name,
        last_name=request_data.last_name,
        email=request_data.email,
        phone=request_data.phone,
        preferred_language=request_data.preferred_language or "en",  # Capture user's UI language
        media_urls=request_data.media_urls[:3] if request_data.media_urls else [],  # Limit to 3 photos
        matched_asset=request_data.matched_asset,
        custom_fields=request_data.custom_fields,
        source="resident_portal",
        assigned_department_id=assigned_department_id,
        assigned_to=assigned_to
    )
    
    db.add(service_request)
    await db.commit()
    await db.refresh(service_request)
    
    # Create audit log entry for submission
    audit_entry = RequestAuditLog(
        service_request_id=service_request.id,
        action="submitted",
        new_value="open",
        actor_type="resident",
        actor_name="Resident"
    )
    db.add(audit_entry)
    await db.commit()
    
    # Trigger Celery task for AI analysis
    from app.tasks.service_requests import analyze_request, send_branded_notification
    analyze_request.delay(service_request.id)
    
    # Send branded confirmation email to resident
    send_branded_notification.delay(service_request.id, "confirmation")
    
    return service_request


@router.get("/requests.json", response_model=List[ServiceRequestResponse])
async def list_requests(
    status_filter: Optional[str] = Query(None, alias="status"),
    service_code: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    include_deleted: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Open311 v2 compatible - List service requests (staff only)"""
    query = select(ServiceRequest).order_by(ServiceRequest.requested_datetime.desc())
    
    # Filter out deleted unless admin requests them
    if not include_deleted or current_user.role != "admin":
        query = query.where(ServiceRequest.deleted_at.is_(None))
    
    if status_filter:
        query = query.where(ServiceRequest.status == status_filter)
    
    if service_code:
        query = query.where(ServiceRequest.service_code == service_code)
    
    if start_date:
        query = query.where(ServiceRequest.requested_datetime >= start_date)
    
    if end_date:
        query = query.where(ServiceRequest.requested_datetime <= end_date)
    
    result = await db.execute(query.limit(100))
    return result.scalars().all()


@router.get("/requests/{request_id}.json", response_model=ServiceRequestDetailResponse)
async def get_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get service request details (staff only)"""
    result = await db.execute(
        select(ServiceRequest)
        .options(selectinload(ServiceRequest.assigned_department))
        .where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


@router.put("/requests/{request_id}/status", response_model=ServiceRequestDetailResponse)
async def update_request_status(
    request_id: str,
    update_data: ServiceRequestUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Update service request status (staff only)"""
    result = await db.execute(
        select(ServiceRequest).options(selectinload(ServiceRequest.assigned_department)).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    update_dict = update_data.model_dump(exclude_unset=True)
    
    # Restrict flagged (legal hold) to admin only
    if "flagged" in update_dict and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only administrators can toggle legal hold status")
    
    # Track old values for audit log
    old_status = request.status
    old_department_id = request.assigned_department_id
    old_assigned_to = request.assigned_to
    old_department_name = request.assigned_department.name if request.assigned_department else None
    old_flagged = request.flagged
    
    for field, value in update_dict.items():
        if value is not None:
            if field == "status":
                value = value.value
                if value == "closed" and request.status != "closed":
                    request.closed_datetime = datetime.utcnow()
            elif field == "closed_substatus":
                value = value.value  # Convert enum to string
            # Special handling for boolean flagged field
            if field == "flagged":
                print(f"[LEGAL HOLD DEBUG] Setting flagged from {request.flagged} to {value} for request {request.service_request_id}")
            setattr(request, field, value)
    
    request.updated_datetime = datetime.utcnow()
    
    # Force flush to ensure changes are written
    await db.flush()
    await db.commit()
    
    # Create audit log entries for changes
    # Status change
    if "status" in update_dict and update_dict["status"] and update_dict["status"].value != old_status:
        new_status = update_dict["status"].value
        extra_data = None
        if new_status == "closed" and "closed_substatus" in update_dict:
            extra_data = {
                "substatus": update_dict["closed_substatus"].value if update_dict["closed_substatus"] else None,
                "completion_message": update_dict.get("completion_message")
            }
        audit_entry = RequestAuditLog(
            service_request_id=request.id,
            action="status_change",
            old_value=old_status,
            new_value=new_status,
            actor_type="staff",
            actor_name=current_user.username,
            extra_data=extra_data
        )
        db.add(audit_entry)
    
    # Department assignment change
    if "assigned_department_id" in update_dict and update_dict["assigned_department_id"] != old_department_id:
        new_dept_id = update_dict["assigned_department_id"]
        new_dept_name = None
        if new_dept_id:
            dept_result = await db.execute(select(Department).where(Department.id == new_dept_id))
            new_dept = dept_result.scalar_one_or_none()
            new_dept_name = new_dept.name if new_dept else str(new_dept_id)
        audit_entry = RequestAuditLog(
            service_request_id=request.id,
            action="department_assigned",
            old_value=old_department_name,
            new_value=new_dept_name,
            actor_type="staff",
            actor_name=current_user.username
        )
        db.add(audit_entry)
    
    # Staff assignment change - only log if new value is non-empty
    if "assigned_to" in update_dict and update_dict["assigned_to"] != old_assigned_to:
        # Only log if new staff is actually assigned (not cleared)
        if update_dict["assigned_to"]:
            audit_entry = RequestAuditLog(
                service_request_id=request.id,
                action="staff_assigned",
                old_value=old_assigned_to,
                new_value=update_dict["assigned_to"],
                actor_type="staff",
                actor_name=current_user.username
            )
            db.add(audit_entry)
    
    # Legal hold change
    if "flagged" in update_dict and update_dict["flagged"] != old_flagged:
        audit_entry = RequestAuditLog(
            service_request_id=request.id,
            action="legal_hold",
            old_value="enabled" if old_flagged else "disabled",
            new_value="enabled" if update_dict["flagged"] else "disabled",
            actor_type="admin",
            actor_name=current_user.username
        )
        db.add(audit_entry)
    
    await db.commit()
    
    # Send notification if status changed
    if "status" in update_dict and update_dict["status"] and update_dict["status"].value != old_status:
        from app.tasks.service_requests import send_branded_notification
        send_branded_notification.delay(
            request.id, 
            "status_update", 
            old_status=old_status,
            completion_message=update_dict.get("completion_message")
        )
    
    # Reload with relationship for response
    await db.refresh(request)
    # Reload the relationship if department was set
    if request.assigned_department_id:
        await db.refresh(request, ['assigned_department'])
    return request


@router.post("/requests/manual", response_model=ServiceRequestResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_intake(
    intake_data: ManualIntakeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Create a request from manual intake (phone/walk-in) - staff only"""
    # Validate service code
    result = await db.execute(
        select(ServiceDefinition).where(
            ServiceDefinition.service_code == intake_data.service_code,
            ServiceDefinition.is_active == True
        )
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid service code"
        )
    
    service_request = ServiceRequest(
        service_request_id=generate_request_id(),
        service_code=intake_data.service_code,
        service_name=service.service_name,
        description=intake_data.description,
        address=intake_data.address,
        first_name=intake_data.first_name,
        last_name=intake_data.last_name,
        email=intake_data.email or f"manual-{uuid.uuid4().hex[:8]}@intake.local",
        phone=intake_data.phone,
        source=intake_data.source.value
    )
    
    db.add(service_request)
    await db.commit()
    await db.refresh(service_request)
    return service_request


@router.delete("/requests/{request_id}")
async def delete_request(
    request_id: str,
    delete_data: ServiceRequestDelete,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Soft delete a service request with justification (staff/admin)"""
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if request.deleted_at:
        raise HTTPException(status_code=400, detail="Request already deleted")
    
    # Soft delete
    request.deleted_at = datetime.utcnow()
    request.deleted_by = current_user.username
    request.delete_justification = delete_data.justification
    request.updated_datetime = datetime.utcnow()
    
    # Add audit log entry
    audit_entry = RequestAuditLog(
        service_request_id=request.id,
        action="deleted",
        actor_type="staff",
        actor_name=current_user.username,
        new_value=delete_data.justification
    )
    db.add(audit_entry)
    
    await db.commit()
    await db.refresh(request)
    
    return {"message": "Request deleted", "request_id": request_id}


@router.post("/requests/{request_id}/restore")
async def restore_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Restore a soft-deleted service request (staff/admin)"""
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    if not request.deleted_at:
        raise HTTPException(status_code=400, detail="Request is not deleted")
    
    # Restore the request
    request.deleted_at = None
    request.deleted_by = None
    request.delete_justification = None
    request.updated_datetime = datetime.utcnow()
    
    # Add audit log entry
    audit_entry = RequestAuditLog(
        service_request_id=request.id,
        action="restored",
        actor_type="staff",
        actor_name=current_user.username,
        new_value=f"Restored by {current_user.username}"
    )
    db.add(audit_entry)
    
    await db.commit()
    await db.refresh(request)
    
    return {"message": "Request restored", "request_id": request_id}


@router.post("/requests/{request_id}/accept-ai-priority")
async def accept_ai_priority(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Accept AI-suggested priority score (copies to manual_priority_score)"""
    result = await db.execute(
        select(ServiceRequest).where(ServiceRequest.service_request_id == request_id)
    )
    request = result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    
    # Get AI priority from stored analysis
    ai_priority = None
    if request.ai_analysis and isinstance(request.ai_analysis, dict):
        ai_priority = request.ai_analysis.get("priority_score")
    
    if ai_priority is None:
        raise HTTPException(status_code=400, detail="No AI priority score available")
    
    # Set the manual priority score to the AI suggestion
    request.manual_priority_score = float(ai_priority)
    request.updated_datetime = datetime.utcnow()
    
    # Add audit log entry
    audit_entry = RequestAuditLog(
        service_request_id=request.id,
        action="priority_accepted",
        actor_type="staff",
        actor_name=current_user.username,
        old_value=str(request.manual_priority_score) if request.manual_priority_score else None,
        new_value=str(ai_priority)
    )
    db.add(audit_entry)
    
    await db.commit()
    await db.refresh(request)
    
    return {"message": "AI priority accepted", "priority_score": ai_priority}


@router.get("/requests/asset/{asset_id}/related")
async def get_asset_related_requests(
    asset_id: str,
    exclude_request_id: Optional[str] = Query(None, description="Request ID to exclude from results"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get all requests that matched to the same asset (staff only)"""
    from sqlalchemy import text
    
    # Query using PostgreSQL JSON extraction - matched_asset->>'asset_id'
    query = select(ServiceRequest).where(
        ServiceRequest.matched_asset.isnot(None),
        ServiceRequest.deleted_at.is_(None),
        text("matched_asset->>'asset_id' = :asset_id")
    ).params(asset_id=asset_id).order_by(ServiceRequest.requested_datetime.desc())
    
    result = await db.execute(query)
    requests = result.scalars().all()
    
    # Filter out the excluded request and build response
    return [
        {
            "service_request_id": r.service_request_id,
            "service_name": r.service_name,
            "status": r.status,
            "requested_datetime": r.requested_datetime.isoformat() if r.requested_datetime else None,
            "address": r.address,
            "description": r.description[:100] if r.description else None,
        }
        for r in requests
        if r.service_request_id != exclude_request_id
    ]

