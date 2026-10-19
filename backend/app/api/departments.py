from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.db.session import get_db
from app.models import Department, User
from app.schemas import DepartmentCreate, DepartmentResponse, DepartmentUpdate
from app.core.auth import get_current_admin, get_current_staff
from app.services.admin_audit import record_admin_action

router = APIRouter()


@router.get("/", response_model=List[DepartmentResponse])
async def list_departments(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """List all departments (staff only — routing_email is internal)"""
    result = await db.execute(select(Department).where(Department.is_active == True))
    return result.scalars().all()


@router.post("/", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    dept_data: DepartmentCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Create a new department (admin only)"""
    result = await db.execute(select(Department).where(Department.name == dept_data.name))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Department name already exists"
        )
    
    dept = Department(**dept_data.model_dump())
    db.add(dept)
    await db.commit()
    await db.refresh(dept)
    await record_admin_action(
        db, event_type="department_created", actor=_,
        details={"department_id": dept.id, "name": dept.name},
    )
    return dept


@router.get("/{dept_id}", response_model=DepartmentResponse)
async def get_department(
    dept_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """Get department by ID (staff only)"""
    result = await db.execute(select(Department).where(Department.id == dept_id))
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    return dept


@router.put("/{dept_id}", response_model=DepartmentResponse)
async def update_department(
    dept_id: int,
    dept_data: DepartmentUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Edit a department's name, description or routing email (admin only).

    The admin console has always had an Edit Department form calling this
    route, but the route did not exist, so every edit failed.
    """
    result = await db.execute(select(Department).where(Department.id == dept_id))
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")

    changes = dept_data.model_dump(exclude_unset=True)
    if "name" in changes:
        if not changes["name"]:
            raise HTTPException(status_code=400, detail="A department needs a name.")
        clash = await db.execute(
            select(Department).where(Department.name == changes["name"], Department.id != dept_id))
        if clash.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Department name already exists")
    for field, value in changes.items():
        setattr(dept, field, value)
    await db.commit()
    await db.refresh(dept)
    await record_admin_action(
        db, event_type="department_updated", actor=_,
        details={"department_id": dept.id, "name": dept.name, "fields": sorted(changes)},
    )
    return dept


@router.delete("/{dept_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_department(
    dept_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Delete department (admin only)"""
    result = await db.execute(select(Department).where(Department.id == dept_id))
    dept = result.scalar_one_or_none()
    if not dept:
        raise HTTPException(status_code=404, detail="Department not found")
    
    removed = {"department_id": dept.id, "name": dept.name}
    await db.delete(dept)
    await db.commit()
    # Read before the delete: afterwards there is nothing left to name it by.
    await record_admin_action(db, event_type="department_deleted", actor=_, details=removed)
