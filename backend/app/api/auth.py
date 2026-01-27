from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import secrets
import logging

from app.db.session import get_db
from app.models import User
from app.schemas import Token
from app.core.auth import create_access_token, get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)

# Store state tokens temporarily (in production, use Redis)
_pending_states: dict = {}


@router.get("/login")
async def initiate_login(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    db: AsyncSession = Depends(get_db)
):
    """
    Initiate Auth0 login flow.
    
    Returns the Auth0 authorization URL to redirect the user to.
    """
    from app.services.auth0_service import get_auth0_login_url, get_auth0_status
    
    # Check if Auth0 is configured
    status_info = await get_auth0_status()
    if not status_info["configured"]:
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured. Please configure Auth0 in Admin Console."
        )
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    _pending_states[state] = redirect_uri
    
    # Build callback URL (backend receives the code)
    callback_url = redirect_uri.rsplit("/", 1)[0] + "/api/auth/callback"
    
    auth_url = get_auth0_login_url(callback_url, state)
    if not auth_url:
        raise HTTPException(status_code=503, detail="Failed to generate Auth0 login URL")
    
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
async def auth0_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Auth0 callback endpoint.
    
    Receives the authorization code from Auth0, exchanges it for tokens,
    creates/updates the user in our database, and returns a JWT.
    """
    from app.services.auth0_service import exchange_auth0_code
    
    # Verify state token
    redirect_uri = _pending_states.pop(state, None)
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="Invalid or expired state token")
    
    # Build callback URL (must match what we sent to Auth0)
    callback_url = redirect_uri.rsplit("/", 1)[0] + "/api/auth/callback"
    
    # Exchange code for tokens and user info
    user_info = await exchange_auth0_code(code, callback_url)
    if not user_info:
        raise HTTPException(status_code=401, detail="Authentication failed")
    
    if not user_info.get("email"):
        raise HTTPException(status_code=400, detail="Email not provided by identity provider")
    
    email = user_info["email"].lower()
    
    # Find or create user
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if user:
        # Update user info from provider
        if user_info.get("name") and not user.full_name:
            user.full_name = user_info["name"]
        user.auth0_id = user_info.get("provider_id")
        await db.commit()
    else:
        # Check if this email is pre-authorized (invited)
        # For now, only allow users who already exist in the system
        raise HTTPException(
            status_code=403,
            detail="Account not found. Please contact an administrator to be added to the system."
        )
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")
    
    # Create our own JWT token
    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    
    # Redirect back to frontend with token
    return RedirectResponse(
        url=f"{redirect_uri}?token={access_token}",
        status_code=302
    )


@router.get("/logout")
async def logout(
    return_to: str = Query(..., description="URL to return to after logout")
):
    """
    Get Auth0 logout URL.
    
    Frontend should redirect to this URL to log out of Auth0.
    """
    from app.services.auth0_service import get_auth0_logout_url
    
    logout_url = get_auth0_logout_url(return_to)
    if not logout_url:
        # If Auth0 not configured, just return the return_to URL
        return {"logout_url": return_to}
    
    return {"logout_url": logout_url}


@router.get("/status")
async def auth_status():
    """
    Get authentication configuration status.
    
    Returns whether Auth0 is configured and available.
    """
    from app.services.auth0_service import get_auth0_status
    
    status_info = await get_auth0_status()
    return {
        "auth0_configured": status_info["configured"],
        "provider": "auth0" if status_info["configured"] else None,
        "message": "Ready" if status_info["configured"] else "Auth0 not configured"
    }


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current authenticated user with departments"""
    # Reload user with departments relationship
    result = await db.execute(
        select(User)
        .options(selectinload(User.departments))
        .where(User.id == current_user.id)
    )
    user = result.scalar_one()
    
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "departments": [{"id": d.id, "name": d.name} for d in user.departments] if user.departments else []
    }

