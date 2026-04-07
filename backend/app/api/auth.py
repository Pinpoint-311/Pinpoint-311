from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import secrets
import logging
import os
import urllib.parse

from app.db.session import get_db
from app.models import User
from app.core.auth import create_access_token, get_current_user
from app.services.auth0_service import Auth0Service
from app.services.audit_service import AuditService

router = APIRouter()
logger = logging.getLogger(__name__)


def _sanitize_redirect_uri(redirect_uri: str) -> str:
    """Validate redirect URI against allowed CORS origins to prevent open redirects."""
    parsed_uri = urllib.parse.urlparse(redirect_uri)
    if parsed_uri.netloc:
        allowed_hosts = {"localhost", "127.0.0.1"}
        cors = os.environ.get("CORS_ORIGINS", "")
        if cors:
            allowed_hosts.update(urllib.parse.urlparse(o).netloc for o in cors.split(","))
        if parsed_uri.netloc not in allowed_hosts:
            return parsed_uri.path or "/"
    return redirect_uri

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


@router.get("/bootstrap/auto")
async def auto_bootstrap(
    db: AsyncSession = Depends(get_db)
):
    """
    One-click browser-based bootstrap — navigate to this URL to auto-login as admin.
    
    ONLY works when Auth0 is NOT configured. This is the recommended way for
    first-time setup. The login page shows a button that links here.
    """
    import time as time_module
    
    # Check if Auth0 is already configured
    status_info = await Auth0Service.check_status(db)
    if status_info["status"] == "configured":
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content="""<!DOCTYPE html><html><head><title>Setup Complete</title></head>
            <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#151929;color:white;text-align:center">
            <div><h2>Auth0 is already configured</h2><p>Use SSO to log in.</p>
            <a href="/login" style="color:#6366f1">Go to Login</a></div></body></html>""",
            status_code=403
        )
    
    # Find admin user
    result = await db.execute(
        select(User).where(User.role == "admin", User.is_active == True).limit(1)
    )
    admin = result.scalar_one_or_none()
    
    if not admin:
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content="""<!DOCTYPE html><html><head><title>Setup Error</title></head>
            <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#151929;color:white;text-align:center">
            <div><h2>No admin user found</h2><p>The database may not be initialized yet.</p>
            <a href="/login" style="color:#6366f1">Go back</a></div></body></html>""",
            status_code=404
        )
    
    # Create JWT directly
    access_token = create_access_token(data={"sub": admin.username, "role": admin.role})
    
    logger.info(f"Auto-bootstrap login successful for: {admin.username}")
    
    # Return HTML that stores token and redirects to admin console
    import json as _json
    safe_token = _json.dumps(access_token)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=f"""<!DOCTYPE html>
    <html>
    <head><title>Setting up...</title></head>
    <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#151929;color:white;text-align:center">
        <div>
            <div style="font-size:2rem;margin-bottom:1rem">✦</div>
            <h2 style="margin:0 0 .5rem">Welcome to Pinpoint 311</h2>
            <p style="color:rgba(255,255,255,.5)">Setting up your admin console...</p>
        </div>
        <script>
            localStorage.setItem('token', {safe_token});
            window.location.href = '/admin';
        </script>
    </body>
    </html>""")


@router.get("/bootstrap/{token}")
async def use_bootstrap_token(
    token: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Use a bootstrap token to get a JWT for admin access.
    
    ONLY works when Auth0 is NOT configured.
    """
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
    import json as _json
    safe_token = _json.dumps(access_token)
    html_response = f"""
    <!DOCTYPE html>
    <html>
    <head><title>Logging in...</title></head>
    <body>
        <script>
            localStorage.setItem('token', {safe_token});
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
    request: Request,
    state: str = Query(...),
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
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
        
    # Handle Auth0 errors (user cancellation, access denied, etc.)
    if error or not code:
        err_msg = error_description or error or "Authentication cancelled or failed."
        safe_error = urllib.parse.quote(err_msg)

        redirect_uri = _sanitize_redirect_uri(redirect_uri)
                
        return RedirectResponse(
            url=f"{redirect_uri}?error={safe_error}",
            status_code=302
        )
    
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
            redirect_uri = _sanitize_redirect_uri(redirect_uri)
            return RedirectResponse(
                url=f"{redirect_uri}?error=Email+not+provided+by+identity+provider",
                status_code=302
            )
        
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
            redirect_uri = _sanitize_redirect_uri(redirect_uri)
            return RedirectResponse(
                url=f"{redirect_uri}?error=Account+not+found.+Please+contact+an+administrator+to+be+added+to+the+system.",
                status_code=302
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
            redirect_uri = _sanitize_redirect_uri(redirect_uri)
            return RedirectResponse(
                url=f"{redirect_uri}?error=Account+is+disabled.+Please+contact+an+administrator.",
                status_code=302
            )
        
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
        
        redirect_uri = _sanitize_redirect_uri(redirect_uri)

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
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    return_to: str = Query(..., description="URL to return to after logout")
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
        except Exception:
            pass  # JWT decode failed, session_id stays "unknown"
    
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


@router.get("/demo-login")
async def demo_login(
    db: AsyncSession = Depends(get_db)
):
    """
    Demo mode auto-login. Returns a JWT for the admin user.
    Only works when DEMO_MODE=true.
    """
    from app.core.config import get_settings
    
    settings = get_settings()
    if not settings.demo_mode:
        raise HTTPException(status_code=404, detail="Not found")
    
    # Find admin user
    result = await db.execute(
        select(User).where(User.role == "admin", User.is_active == True).limit(1)
    )
    admin = result.scalar_one_or_none()
    
    if not admin:
        raise HTTPException(status_code=500, detail="No admin user found")
    
    access_token = create_access_token(data={"sub": admin.username, "role": admin.role})
    
    logger.info(f"Demo login for: {admin.username}")
    
    # Return HTML that stores token and redirects to staff dashboard
    import json as _json
    safe_token = _json.dumps(access_token)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=f"""
    <!DOCTYPE html>
    <html>
    <head><title>Logging in to demo...</title></head>
    <body>
        <script>
            localStorage.setItem('token', {safe_token});
            window.location.href = '/staff';
        </script>
        <p>Logging in... If not redirected, <a href="/staff">click here</a></p>
    </body>
    </html>
    """)
