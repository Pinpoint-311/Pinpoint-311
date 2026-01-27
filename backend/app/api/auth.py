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

# One-time bootstrap tokens (only work until Auth0 is configured)
_bootstrap_tokens: dict = {}


@router.post("/bootstrap")
async def generate_bootstrap_token(
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a one-time magic link for admin access.
    
    ONLY works when Auth0 is NOT configured. This allows the initial admin
    to log in and configure Auth0. Once Auth0 is configured, this endpoint
    returns an error.
    
    Requires the INITIAL_ADMIN_PASSWORD from environment to authorize.
    """
    from app.services.zitadel_service import get_zitadel_status
    from app.core.config import get_settings
    from fastapi import Header
    
    settings = get_settings()
    
    # Check if Auth0 is already configured
    status_info = await get_zitadel_status()
    if status_info["configured"]:
        raise HTTPException(
            status_code=403,
            detail="Bootstrap access disabled - Zitadel SSO is already configured. Use SSO to log in."
        )
    
    # Find admin user
    result = await db.execute(
        select(User).where(User.role == "admin", User.is_active == True).limit(1)
    )
    admin = result.scalar_one_or_none()
    
    if not admin:
        raise HTTPException(status_code=404, detail="No admin user found")
    
    # Generate one-time token
    token = secrets.token_urlsafe(48)
    _bootstrap_tokens[token] = {
        "user_id": admin.id,
        "username": admin.username,
        "expires": __import__("time").time() + 3600  # 1 hour expiry
    }
    
    logger.info(f"Bootstrap token generated for admin: {admin.username}")
    
    return {
        "message": "Bootstrap token generated",
        "token": token,
        "expires_in_seconds": 3600,
        "login_url": f"/api/auth/bootstrap/{token}",
        "warning": "This token will be invalidated once Auth0 is configured"
    }


@router.get("/bootstrap/{token}")
async def use_bootstrap_token(
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Use a bootstrap token to get a JWT for admin access.
    
    ONLY works when Auth0 is NOT configured.
    """
    from app.services.zitadel_service import get_zitadel_status
    import time as time_module
    
    # Check if SSO is already configured
    status_info = await get_zitadel_status()
    if status_info["configured"]:
        # Clear all bootstrap tokens since Auth0 is now configured
        _bootstrap_tokens.clear()
        raise HTTPException(
            status_code=403,
            detail="Bootstrap access disabled - Auth0 is configured. Use SSO to log in."
        )
    
    # Verify token
    token_data = _bootstrap_tokens.pop(token, None)
    if not token_data:
        raise HTTPException(status_code=401, detail="Invalid or expired bootstrap token")
    
    # Check expiry
    if time_module.time() > token_data["expires"]:
        raise HTTPException(status_code=401, detail="Bootstrap token has expired")
    
    # Get user
    result = await db.execute(select(User).where(User.id == token_data["user_id"]))
    user = result.scalar_one_or_none()
    
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    
    # Create JWT
    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    
    logger.info(f"Bootstrap login successful for: {user.username}")
    
    # Return HTML that stores token and redirects
    html_response = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Logging in...</title></head>
    <body>
        <script>
            localStorage.setItem('token', '{access_token}');
            window.location.href = '/admin';
        </script>
        <p>Logging in... If not redirected, <a href="/admin">click here</a></p>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_response)


@router.get("/login")
async def initiate_login(
    redirect_uri: str = Query(..., description="Frontend callback URL"),
    db: AsyncSession = Depends(get_db)
):
    """
    Initiate Auth0 login flow.
    
    Returns the Auth0 authorization    (token exchange handled by callback endpoint).
    """
    from app.services.zitadel_service import get_zitadel_login_url, get_zitadel_status
    
    # Check if Zitadel is configured
    status_info = await get_zitadel_status()
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
    
    auth_url = await get_zitadel_login_url(callback_url, state)
    if not auth_url:
        raise HTTPException(status_code=503, detail="Failed to generate Zitadel login URL")
    
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
    from app.services.zitadel_service import exchange_zitadel_code
    
    # Verify state token
    redirect_uri = _pending_states.pop(state, None)
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="Invalid or expired state token")
    
    # Build callback URL (must match what we sent to Auth0)
    callback_url = redirect_uri.rsplit("/", 1)[0] + "/api/auth/callback"
    
    # Exchange code for tokens and user info
    user_info = await exchange_zitadel_code(code, callback_url)
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
    from app.services.zitadel_service import get_zitadel_logout_url
    
    logout_url = await get_zitadel_logout_url(return_to)
    if not logout_url:
        # If Auth0 not configured, just return the return_to URL
        return {"logout_url": return_to}
    
    return {"logout_url": logout_url}


@router.get("/status")
async def auth_status():
    """
    Get authentication configuration status.
    
    Clear all session data and optionally redirect to Zitadel logout.
    """
    from app.services.zitadel_service import get_zitadel_status
    
    status_info = await get_zitadel_status()
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

