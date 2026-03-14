from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import selectinload
from typing import List

from app.db.session import get_db
from app.models import ServiceDefinition, Department, User
from app.schemas import ServiceCreate, ServiceResponse, ServiceUpdate
from app.core.auth import get_current_admin

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
        .order_by(ServiceDefinition.display_order, ServiceDefinition.service_name)
    )
    services = result.scalars().all()
    
    # Get target language from header
    accept_language = request.headers.get('Accept-Language', 'en')
    target_lang = accept_language.split(',')[0].split('-')[0].strip()
    
    # If not English, translate the response (not the database objects)
    if target_lang != 'en':
        from app.services.translation import translate_service_response
        translated_services = []
        for service in services:
            # Convert to dict, translate, add back
            service_dict = {
                "id": service.id,
                "service_code": service.service_code,
                "service_name": service.service_name,
                "description": service.description,
                "icon": service.icon,
                "is_active": service.is_active,
                "routing_mode": service.routing_mode,
                "routing_config": service.routing_config,
                "assigned_department_id": service.assigned_department_id,
                "departments": [{"id": d.id, "name": d.name, "description": d.description, "is_active": d.is_active, "routing_email": d.routing_email} for d in service.departments],
                "assigned_department": {"id": service.assigned_department.id, "name": service.assigned_department.name, "description": service.assigned_department.description, "is_active": service.assigned_department.is_active, "routing_email": service.assigned_department.routing_email} if service.assigned_department else None
            }
            translated = await translate_service_response(service_dict, target_lang)
            translated_services.append(translated)
        return translated_services
    
    return services




@router.get("/all", response_model=List[ServiceResponse])
async def list_all_services(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all service categories including inactive (admin only)"""
    result = await db.execute(
        select(ServiceDefinition)
        .options(selectinload(ServiceDefinition.departments))
        .order_by(ServiceDefinition.display_order, ServiceDefinition.service_name)
    )
    return result.scalars().all()


@router.post("/", response_model=ServiceResponse, status_code=status.HTTP_201_CREATED)
async def create_service(
    service_data: ServiceCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Create a new service category (admin only)"""
    # Check for duplicate service code
    result = await db.execute(
        select(ServiceDefinition).where(ServiceDefinition.service_code == service_data.service_code)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Service code already exists"
        )
    
    # Get departments for relationship
    departments = []
    if service_data.department_ids:
        for dept_id in service_data.department_ids:
            result = await db.execute(select(Department).where(Department.id == dept_id))
            dept = result.scalar_one_or_none()
            if dept:
                departments.append(dept)
    
    # Get the highest display_order to place new service at end
    max_order_result = await db.execute(
        select(sa_func.coalesce(sa_func.max(ServiceDefinition.display_order), -1))
    )
    max_order = max_order_result.scalar() or 0
    
    service = ServiceDefinition(
        service_code=service_data.service_code,
        service_name=service_data.service_name,
        description=service_data.description,
        icon=service_data.icon,
        display_order=service_data.display_order if service_data.display_order else max_order + 1
    )
    service.departments = departments
    
    db.add(service)
    await db.commit()
    await db.refresh(service)
    
    # Reload with relationships
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service.id)
        .options(selectinload(ServiceDefinition.departments))
    )
    return result.scalar_one()


@router.get("/{service_id}", response_model=ServiceResponse)
async def get_service(service_id: int, db: AsyncSession = Depends(get_db)):
    """Get service by ID"""
    result = await db.execute(
        select(ServiceDefinition)
        .where(ServiceDefinition.id == service_id)
        .options(selectinload(ServiceDefinition.departments))
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
    
    # Update basic fields
    if service_data.service_name is not None:
        service.service_name = service_data.service_name
    if service_data.description is not None:
        service.description = service_data.description
    if service_data.icon is not None:
        service.icon = service_data.icon
    if service_data.is_active is not None:
        service.is_active = service_data.is_active
    
    # Update routing configuration
    if service_data.routing_mode is not None:
        service.routing_mode = service_data.routing_mode
    if service_data.routing_config is not None:
        service.routing_config = service_data.routing_config
    if service_data.assigned_department_id is not None:
        service.assigned_department_id = service_data.assigned_department_id
    if service_data.display_order is not None:
        service.display_order = service_data.display_order
    
    # Update departments
    if service_data.department_ids is not None:
        departments = []
        for dept_id in service_data.department_ids:
            result = await db.execute(select(Department).where(Department.id == dept_id))
            dept = result.scalar_one_or_none()
            if dept:
                departments.append(dept)
        service.departments = departments
    
    await db.commit()
    
    # Reload with relationships
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
    
    await db.delete(service)
    await db.commit()


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
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    service.is_active = not service.is_active
    await db.commit()
    await db.refresh(service)
    return service


@router.put("/reorder")
async def reorder_services(
    order: List[dict],
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Reorder service categories (admin only). Accepts list of {id, display_order}."""
    for item in order:
        service_id = item.get("id")
        display_order = item.get("display_order")
        if service_id is not None and display_order is not None:
            result = await db.execute(
                select(ServiceDefinition).where(ServiceDefinition.id == service_id)
            )
            service = result.scalar_one_or_none()
            if service:
                service.display_order = display_order
    await db.commit()
    return {"status": "updated", "count": len(order)}
