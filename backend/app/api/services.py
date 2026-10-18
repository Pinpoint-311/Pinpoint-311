from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import selectinload
from typing import List

from app.db.session import get_db
from app.models import ServiceDefinition, Department, User
from app.schemas import ServiceCreate, ServiceResponse, ServiceUpdate, ServiceReorderRequest
from app.core.auth import get_current_admin, get_current_staff
from app.services.admin_audit import record_admin_action
from app.services import location_policy

router = APIRouter()


@router.get("/", response_model=List[ServiceResponse])
async def list_services(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """List all active service categories (public)"""
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.is_active == True)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
        .order_by(ServiceDefinition.display_order, ServiceDefinition.service_name)
    )
    services = result.scalars().all()
    
    # Serialised here, while every relationship is loaded, rather than handing
    # ORM objects to FastAPI to read after the endpoint returns -- that read is
    # outside the async context, so any attribute needing a load raised
    # MissingGreenlet ("assigned_department") and the resident got a 500.
    payload = [ServiceResponse.model_validate(service).model_dump() for service in services]

    # Get target language from header
    accept_language = request.headers.get('Accept-Language', 'en')
    target_lang = accept_language.split(',')[0].split('-')[0].strip()

    # If not English, translate the response (not the database objects). It
    # starts from the full payload: the hand-built dict this replaced left out
    # display_order, location_mode and hidden_from_public, so a resident
    # browsing in Spanish saw a hidden category as public and a location-
    # required one as optional.
    if target_lang != 'en':
        from app.services.translation import translate_service_response
        return [await translate_service_response(item, target_lang) for item in payload]

    return payload


@router.get("/all", response_model=List[ServiceResponse])
async def list_all_services(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all service categories including inactive (admin only)"""
    result = await db.execute(
        select(ServiceDefinition)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
        .order_by(ServiceDefinition.display_order, ServiceDefinition.service_name)
    )
    return [ServiceResponse.model_validate(service).model_dump() for service in result.scalars().all()]


# NOTE: /reorder MUST be defined BEFORE /{service_id} routes,
# otherwise FastAPI matches "reorder" as a service_id int and returns 422.
@router.put("/reorder")
async def reorder_services(
    body: ServiceReorderRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Reorder service categories (admin only). Accepts {order: [{id, display_order}]}."""
    for item in body.order:
        result = await db.execute(
            select(ServiceDefinition).where(ServiceDefinition.id == item.id)
        )
        service = result.scalar_one_or_none()
        if service:
            service.display_order = item.display_order
    await db.commit()
    return {"status": "updated", "count": len(body.order)}


@router.post("/", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    service_data: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Create a new service category (admin only)"""
    result = await db.execute(
        select(ServiceDefinition).where(ServiceDefinition.service_code == service_data.service_code)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service code already exists"
        )
    
    try:
        location_policy.validate_routing(service_data.location_mode, service_data.routing_mode)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    departments = []
    if service_data.department_ids:
        for dept_id in service_data.department_ids:
            result = await db.execute(select(Department).where(Department.id == dept_id))
            dept = result.scalar_one_or_none()
            if dept:
                departments.append(dept)
    
    max_order_result = await db.execute(
        select(sa_func.coalesce(sa_func.max(ServiceDefinition.display_order), -1))
    )
    max_order = max_order_result.scalar() or 0
    
    service = ServiceDefinition(
        service_code=service_data.service_code,
        service_name=service_data.service_name,
        description=service_data.description,
        icon=service_data.icon,
        sla_hours=service_data.sla_hours,
        location_mode=service_data.location_mode,
        hidden_from_public=service_data.hidden_from_public,
        display_order=service_data.display_order if service_data.display_order else max_order + 1
    )
    service.departments = departments
    
    db.add(service)
    await db.commit()
    await db.refresh(service)
    await record_admin_action(
        db, event_type="service_created", actor=_,
        details={"service_code": service.service_code, "service_name": service.service_name},
    )

    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service.id)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
    )
    return result.scalar_one()


@router.get("/sla-performance")
async def sla_performance(
    days: int = 90,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff),
):
    """SLA performance per service category (staff only).

    Only categories with an SLA configured are reported — categories without one
    are listed separately so admins can see what isn't covered yet, but they are
    never counted as failing.
    """
    from datetime import datetime, timedelta, timezone
    from app.models import ServiceRequest
    from app.services.sla import summarize_category, overall_summary

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=max(1, min(days, 730)))

    services_result = await db.execute(select(ServiceDefinition))
    services = services_result.scalars().all()

    rows_result = await db.execute(
        select(
            ServiceRequest.service_code,
            ServiceRequest.requested_datetime,
            ServiceRequest.closed_datetime,
        ).where(
            ServiceRequest.deleted_at.is_(None),
            ServiceRequest.requested_datetime >= since,
        )
    )
    by_code: dict = {}
    for code, requested, closed in rows_result.all():
        by_code.setdefault(code, []).append(
            {"requested_datetime": requested, "closed_datetime": closed}
        )

    categories = []
    without_sla = []
    for svc in services:
        if svc.sla_hours:
            categories.append(
                summarize_category(
                    svc.service_code, svc.service_name, svc.sla_hours,
                    by_code.get(svc.service_code, []), now,
                )
            )
        elif svc.is_active is not False:
            without_sla.append({"service_code": svc.service_code, "service_name": svc.service_name})

    # Worst compliance first so the categories needing attention lead.
    categories.sort(key=lambda c: (c["compliance_rate"] is None, c["compliance_rate"] or 0))

    return {
        "period_days": days,
        "generated_at": now.isoformat(),
        "overall": overall_summary(categories),
        "categories": categories,
        "categories_without_sla": without_sla,
    }


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(service_id: int, db: AsyncSession = Depends(get_db)):
    """Get service by ID (only returns active services for public access)"""
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service_id, ServiceDefinition.is_active == True)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.put("/{service_id}", response_model=ServiceResponse)
async def update_service(
    service_id: int,
    service_data: ServiceUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Update service category with routing configuration (admin only)"""
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service_id)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    old_name = service.service_name
    _tracked = ("service_name", "description", "icon", "is_active", "routing_mode", "routing_config",
                "assigned_department_id", "display_order", "sla_hours", "location_mode", "hidden_from_public")
    before = {f: getattr(service, f, None) for f in _tracked}
    if service_data.service_name is not None:
        service.service_name = service_data.service_name.strip()
    if service_data.description is not None:
        service.description = service_data.description
    if service_data.icon is not None:
        service.icon = service_data.icon
    if service_data.is_active is not None:
        service.is_active = service_data.is_active
    if service_data.routing_mode is not None:
        service.routing_mode = service_data.routing_mode
    if service_data.routing_config is not None:
        service.routing_config = service_data.routing_config
    if service_data.assigned_department_id is not None:
        service.assigned_department_id = service_data.assigned_department_id
    if service_data.display_order is not None:
        service.display_order = service_data.display_order
    if service_data.sla_hours is not None:
        # 0 explicitly clears the SLA back to "none"; omitting the field leaves it.
        service.sla_hours = service_data.sla_hours or None
    if service_data.location_mode is not None:
        service.location_mode = service_data.location_mode
    visibility_changed = (
        service_data.hidden_from_public is not None
        and bool(service_data.hidden_from_public) != bool(service.hidden_from_public)
    )
    if service_data.hidden_from_public is not None:
        service.hidden_from_public = service_data.hidden_from_public
    # Checked on the resulting state, so switching routing to road-based on a
    # category that hides location is refused as well as the reverse.
    try:
        location_policy.validate_routing(service.location_mode, service.routing_mode)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    if service_data.department_ids is not None:
        departments = []
        for dept_id in service_data.department_ids:
            result = await db.execute(select(Department).where(Department.id == dept_id))
            dept = result.scalar_one_or_none()
            if dept:
                departments.append(dept)
        service.departments = departments
    
    # Reports carry the category name they were filed under, for lists and the
    # public map. A rename is a correction to the label, so it follows through
    # to them; the category itself (service_code) is unchanged.
    if service.service_name != old_name:
        from sqlalchemy import update as sa_update
        from app.models import ServiceRequest
        await db.execute(
            sa_update(ServiceRequest)
            .where(ServiceRequest.service_code == service.service_code)
            .values(service_name=service.service_name)
        )

    await db.commit()

    # What actually changed, not what the form sent (it sends everything).
    changed_fields = sorted(f for f in _tracked if getattr(service, f, None) != before[f])
    if changed_fields:
        await record_admin_action(
            db, event_type="service_updated", actor=_,
            details={"service_code": service.service_code, "service_name": service.service_name,
                     "fields": changed_fields},
        )

    # Its own audit event: taking a whole category off the public map is a
    # records decision someone may later need to show was made, and by whom.
    if visibility_changed:
        await record_admin_action(
            db, event_type="service_public_visibility", actor=_,
            details={"service_code": service.service_code, "service_name": service.service_name,
                     "hidden_from_public": bool(service.hidden_from_public)},
        )
    
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service_id)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
    )
    return result.scalar_one()


@router.delete("/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Delete service category (admin only)"""
    result = await db.execute(
        select(ServiceDefinition).where(ServiceDefinition.id == service_id)
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    removed = {"service_code": service.service_code, "service_name": service.service_name}
    await db.delete(service)
    await db.commit()
    await record_admin_action(db, event_type="service_deleted", actor=_, details=removed)


@router.patch("/{service_id}/toggle", response_model=ServiceResponse)
async def toggle_service(
    service_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Toggle service active status (admin only)"""
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service_id)
        .options(selectinload(ServiceDefinition.departments))
        .options(selectinload(ServiceDefinition.assigned_department))
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    service.is_active = not service.is_active
    await db.commit()
    await db.refresh(service)
    # Turning a category off removes it from the resident portal, so this is a
    # change to what the public can report, not a cosmetic toggle.
    await record_admin_action(
        db, event_type="service_toggled", actor=_,
        details={"service_code": service.service_code, "is_active": service.is_active},
    )
    return service
