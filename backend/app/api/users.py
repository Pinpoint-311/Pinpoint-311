from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import List

from app.db.session import get_db
from app.models import User, Department
from app.schemas import UserCreate, UserResponse, UserUpdate
from app.core.auth import get_password_hash, get_current_admin, get_current_staff

router = APIRouter()


# Minimal response schema for staff assignment dropdown
from pydantic import BaseModel
from typing import Optional

class DepartmentMinimal(BaseModel):
    id: int
    name: str
    
    class Config:
        from_attributes = True

class StaffMemberResponse(BaseModel):
    id: int
    username: str
    full_name: str | None
    role: str
    departments: Optional[list[DepartmentMinimal]] = None
    
    class Config:
        from_attributes = True


@router.get("/staff", response_model=List[StaffMemberResponse])
async def list_staff_members(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_staff)
):
    """List staff and admin users for assignment (accessible by any staff user)"""
    result = await db.execute(
        select(User)
        .options(selectinload(User.departments))
        .where(User.role.in_(['staff', 'admin']), User.is_active == True)
        .order_by(User.full_name, User.username)
    )
    return result.scalars().all()


# GET /users/staff/public is deliberately gone.
#
# It served the full roster of every active staff and admin account --
# username, full name, and role -- to anyone who asked, with no auth. Its only
# caller was the resident portal, which loaded it to populate the "Assigned
# Staff" checkboxes on the public map, and its docstring said so: "for public
# filters".
#
# That filter is now staff-only, so the endpoint has no remaining purpose and
# is pure exposure. A username list is the first half of a credential-stuffing
# attempt, and `role` labelled which of those usernames were administrators.
#
# The staff map reads the authenticated /users/staff instead. If something ever
# genuinely needs to show residents who works for the town -- a "contact your
# department" page -- that wants names and job titles chosen for publication,
# not a dump of the login table.


@router.get("/", response_model=List[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """List all users (admin only)"""
    result = await db.execute(
        select(User)
        .options(selectinload(User.departments))
        .order_by(User.created_at.desc())
    )
    return result.scalars().all()


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """
    Create a new user (admin only).
    
    Users are created with email as their identifier. They will log in via 
    Auth0 SSO using their email address. No password is required as 
    authentication is handled by Auth0.
    """
    from app.models import Department
    
    # Check for existing username
    result = await db.execute(select(User).where(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists"
        )
    
    # Check for existing email
    result = await db.execute(select(User).where(User.email == user_data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists"
        )
    
    # Create user without password - they'll authenticate via SSO
    user = User(
        username=user_data.username,
        email=user_data.email,
        full_name=user_data.full_name,
        hashed_password=None,  # No password for SSO users
        role=user_data.role.value,
        is_active=True
    )
    
    # Assign departments if provided
    if user_data.department_ids:
        result = await db.execute(
            select(Department).where(Department.id.in_(user_data.department_ids))
        )
        departments = result.scalars().all()
        user.departments = list(departments)
    
    db.add(user)
    await db.commit()
    
    # Reload with departments relationship for response
    result = await db.execute(
        select(User)
        .where(User.id == user.id)
        .options(selectinload(User.departments))
    )
    return result.scalar_one()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Get user by ID (admin only)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Update user (admin only)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = user_data.model_dump(exclude_unset=True)

    # Departments are a many-to-many relationship, not a column. The loop below
    # used to setattr "department_ids" straight onto the ORM object, which binds
    # a stray Python attribute and never touches the join table -- the request
    # returned 200 with the user's old departments and the edit silently
    # vanished. create_user always did this correctly; update_user did not.
    department_ids = update_data.pop("department_ids", None)
    if department_ids is not None:
        result = await db.execute(
            select(Department).where(Department.id.in_(department_ids))
        )
        found = list(result.scalars().all())
        if len(found) != len(set(department_ids)):
            raise HTTPException(status_code=400, detail="One or more departments do not exist")
        # Assigned wholesale, so an empty list genuinely clears them.
        user.departments = found

    for field, value in update_data.items():
        if value is not None:
            if field == "role":
                value = value.value
            setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin)
):
    """Delete user (admin only)"""
    if current_user.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself"
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    await db.delete(user)
    await db.commit()


@router.post("/{user_id}/reset-password", response_model=UserResponse)
async def reset_password(
    user_id: int,
    new_password: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Reset user password (admin only)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.hashed_password = get_password_hash(new_password)
    await db.commit()
    await db.refresh(user)
    return user


from pydantic import BaseModel

class PasswordResetRequest(BaseModel):
    new_password: str


@router.post("/{user_id}/reset-password-json", response_model=UserResponse)
async def reset_password_json(
    user_id: int,
    data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin)
):
    """Reset user password via JSON body (admin only)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    user.hashed_password = get_password_hash(data.new_password)
    await db.commit()
    await db.refresh(user)
    return user


# ============ Notification Preferences ============
from app.schemas import NotificationPreferencesUpdate


class NotificationPreferencesResponse(BaseModel):
    email_new_requests: bool = True
    email_status_changes: bool = True
    email_comments: bool = True
    email_assigned_only: bool = False
    sms_new_requests: bool = False
    sms_status_changes: bool = False
    phone: Optional[str] = None
    
    class Config:
        from_attributes = True


@router.get("/me/notification-preferences", response_model=NotificationPreferencesResponse)
async def get_my_notification_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Get current user's notification preferences"""
    prefs = current_user.notification_preferences or {}
    return NotificationPreferencesResponse(
        email_new_requests=prefs.get("email_new_requests", True),
        email_status_changes=prefs.get("email_status_changes", True),
        email_comments=prefs.get("email_comments", True),
        email_assigned_only=prefs.get("email_assigned_only", False),
        sms_new_requests=prefs.get("sms_new_requests", False),
        sms_status_changes=prefs.get("sms_status_changes", False),
        phone=current_user.phone
    )


@router.put("/me/notification-preferences", response_model=NotificationPreferencesResponse)
async def update_my_notification_preferences(
    prefs: NotificationPreferencesUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_staff)
):
    """Update current user's notification preferences"""
    # Get current preferences or initialize empty
    current_prefs = current_user.notification_preferences or {}
    
    # Update only the fields that were provided
    update_data = prefs.model_dump(exclude_unset=True, exclude={"phone"})
    for key, value in update_data.items():
        if value is not None:
            current_prefs[key] = value
    
    current_user.notification_preferences = current_prefs
    
    # Update phone if provided
    if prefs.phone is not None:
        current_user.phone = prefs.phone
    
    await db.commit()
    await db.refresh(current_user)
    
    return NotificationPreferencesResponse(
        email_new_requests=current_prefs.get("email_new_requests", True),
        email_status_changes=current_prefs.get("email_status_changes", True),
        email_comments=current_prefs.get("email_comments", True),
        email_assigned_only=current_prefs.get("email_assigned_only", False),
        sms_new_requests=current_prefs.get("sms_new_requests", False),
        sms_status_changes=current_prefs.get("sms_status_changes", False),
        phone=current_user.phone
    )


