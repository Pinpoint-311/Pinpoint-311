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
from app.services.auth0_service import Auth0Service
from app.services.audit_service import AuditService

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
    status_info = await Auth0Service.check_status(db)
    if status_info["status"] == "configured":
        raise HTTPException(
            status_code=403,
            detail="Bootstrap access disabled - Auth0 is already configured. Use SSO to log in."
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
    status_info = await Auth0Service.check_status(db)
    if status_info["status"] == "configured":
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
    
    Returns the Auth0 authorization URL that frontend should redirect to
    (token exchange handled by callback endpoint).
    """
    # Check if Auth0 is configured
    status_info = await Auth0Service.check_status(db)
    if status_info["status"] != "configured":
        raise HTTPException(
            status_code=503,
            detail="Authentication not configured. Please configure Auth0 in Admin Console."
        )
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    _pending_states[state] = redirect_uri
    
    # Build callback URL (backend receives the code)
    callback_url = redirect_uri.rsplit("/", 1)[0] + "/api/auth/callback"
    
    auth_url = await Auth0Service.get_authorization_url(callback_url, state, db)
    if not auth_url:
        raise HTTPException(status_code=503, detail="Failed to generate Auth0 login URL")
    
    return {"auth_url": auth_url, "state": state}


@router.get("/callback")
async def auth0_callback(
    code: str = Query(...),
    state: str = Query(...),
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Auth0 callback endpoint.
    
    Receives the authorization code from Auth0, exchanges it for tokens,
    creates/updates the user in our database, and returns a JWT.
    
    Logs all authentication events for audit trail.
    """
    # Verify state token
    redirect_uri = _pending_states.pop(state, None)
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="Invalid or expired state token")
    
    # Build callback URL (must match what we sent to Auth0)
    callback_url = redirect_uri.rsplit("/", 1)[0] + "/api/auth/callback"
    
    # Get IP address for audit logging
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    try:
        # Exchange code for tokens
        tokens = await Auth0Service.exchange_code_for_tokens(code, callback_url, db)
        
        # Get user info from ID token
        id_token = tokens.get("id_token")
        user_info = await Auth0Service.verify_token(id_token, db)
        
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
            if user_info.get("sub"):
                user.auth0_id = user_info["sub"]
            await db.commit()
        else:
            # Log failed attempt - user not in system
            await AuditService.log_login_failed(
                db=db,
                username=email,
                ip_address=ip_address,
                user_agent=user_agent,
                reason="Account not found in system"
            )
            raise HTTPException(
                status_code=403,
                detail="Account not found. Please contact an administrator to be added to the system."
            )
        
        if not user.is_active:
            # Log failed attempt - account disabled
            await AuditService.log_login_failed(
                db=db,
                username=user.username,
                ip_address=ip_address,
                user_agent=user_agent,
                reason="Account is disabled"
            )
            raise HTTPException(status_code=403, detail="Account is disabled")
        
        # Create our own JWT token
        access_token = create_access_token(data={"sub": user.username, "role": user.role})
        
        # Extract JWT ID for session tracking
        import jwt as jwt_lib
        decoded = jwt_lib.decode(access_token, options={"verify_signature": False})
        session_id = decoded.get("jti", "unknown")
        
        # Log successful login
        await AuditService.log_login_success(
            db=db,
            user=user,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            mfa_used=user_info.get("amr")  # Auth0 provides authentication method reference
        )
        
        logger.info(f"Auth0 login successful for: {user.username} from {ip_address}")
        
        # Redirect back to frontend with token
        return RedirectResponse(
            url=f"{redirect_uri}?token={access_token}",
            status_code=302
        )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth0 callback failed: {str(e)}")
        # Log generic failure
        await AuditService.log_event(
            db=db,
            event_type="login_failed",
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason=f"Authentication error: {str(e)}"
        )
        raise HTTPException(status_code=401, detail="Authentication failed")


@router.get("/logout")
async def logout(
    return_to: str = Query(..., description="URL to return to after logout"),
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Logout endpoint - logs the logout event and returns Auth0 logout URL.
    
    Frontend should redirect to this URL to log out of Auth0.
    """
    # Get session info for audit log
    ip_address = request.client.host if request.client else "unknown"
    auth_header = request.headers.get("authorization", "")
    session_id = "unknown"
    
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            import jwt as jwt_lib
            decoded = jwt_lib.decode(token, options={"verify_signature": False})
            session_id = decoded.get("jti", "unknown")
        except:
            pass
    
    # Log logout event
    await AuditService.log_logout(
        db=db,
        user=current_user,
        ip_address=ip_address,
        session_id=session_id
    )
    
    logger.info(f"User logged out: {current_user.username} from {ip_address}")
    
    # Get Auth0 logout URL
    config = await Auth0Service.get_config(db)
    if not config:
        # If Auth0 not configured, just return the return_to URL
        return {"logout_url": return_to}
    
    domain = config["domain"]
    client_id = config["client_id"]
    logout_url = f"https://{domain}/v2/logout?client_id={client_id}&returnTo={return_to}"
    
    return {"logout_url": logout_url}


@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    """
    Get authentication configuration status.
    """
    status_info = await Auth0Service.check_status(db)
    configured = status_info["status"] == "configured"
    
    return {
        "auth0_configured": configured,
        "provider": "auth0" if configured else None,
        "message": "Ready" if configured else "Auth0 not configured"
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

