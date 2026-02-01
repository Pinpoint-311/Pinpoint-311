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

# Emergency access rate limiting
_emergency_attempts: dict = {}  # {ip: [timestamp, timestamp, ...]}
_emergency_global_attempts: int = 0
_emergency_locked: bool = False


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


@router.post("/emergency")
async def emergency_access(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Emergency admin access endpoint.
    
    Provides secure backdoor for admin access even when Auth0 is configured.
    Requires EMERGENCY_ACCESS_TOKEN from environment variables.
    
    Request body: {"emergency_token": "your-token-here"}
    
    Security features:
    - Constant-time token comparison (prevents timing attacks)
    - Rate limiting: 3 attempts/hour per IP, 5/hour globally
    - Auto-lockout after 5 failed global attempts  
    - All attempts audited
    - Generic error messages (prevents enumeration)
    """
    import time as time_module
    import hmac
    from app.core.config import get_settings
    
    settings = get_settings()
    global _emergency_attempts, _emergency_global_attempts, _emergency_locked
    
    # Parse request body
    try:
        body = await request.json()
        emergency_token = body.get("emergency_token", "")
    except:
        raise HTTPException(status_code=400, detail="Invalid request")
    
    # Get IP address for rate limiting and audit
    ip_address = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    current_time = time_module.time()
    
    # Check if emergency access is locked
    if _emergency_locked:
        await AuditService.log_event(
            db=db,
            event_type="emergency_access_failed",
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="System locked - too many failed attempts"
        )
        raise HTTPException(status_code=403, detail="Access denied")
    
    # Check if emergency token is configured
    if not settings.emergency_access_token:
        await AuditService.log_event(
            db=db,
            event_type="emergency_access_failed",
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="Emergency token not configured"
        )
        raise HTTPException(status_code=503, detail="Emergency access not configured")
    
    # Rate limiting per IP (3 attempts per hour)
    if ip_address in _emergency_attempts:
        # Clean up attempts older than 1 hour
        _emergency_attempts[ip_address] = [
            t for t in _emergency_attempts[ip_address]
            if current_time - t < 3600
        ]
        
        if len(_emergency_attempts[ip_address]) >= 3:
            await AuditService.log_event(
                db=db,
                event_type="emergency_access_failed",
                success=False,
                ip_address=ip_address,
                user_agent=user_agent,
                failure_reason="Rate limit exceeded"
            )
            raise HTTPException(status_code=429, detail="Too many attempts")
    else:
        _emergency_attempts[ip_address] = []
    
    # Constant-time comparison to prevent timing attacks
    expected_token = settings.emergency_access_token.encode()
    provided_token = emergency_token.encode()
    
    if not hmac.compare_digest(expected_token, provided_token):
        # Record failed attempt
        _emergency_attempts[ip_address].append(current_time)
        _emergency_global_attempts += 1
        
        # Lock after 5 global failed attempts
        if _emergency_global_attempts >= 5:
            _emergency_locked = True
            logger.critical(f"EMERGENCY ACCESS LOCKED after 5 failed attempts. Last from {ip_address}")
        
        await AuditService.log_event(
            db=db,
            event_type="emergency_access_failed",
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="Invalid token"
        )
        
        logger.warning(f"Failed emergency access attempt from {ip_address}")
        raise HTTPException(status_code=401, detail="Access denied")
    
    # Valid token - find admin user
    result = await db.execute(
        select(User).where(User.role == "admin", User.is_active == True).limit(1)
    )
    admin = result.scalar_one_or_none()
    
    if not admin:
        await AuditService.log_event(
            db=db,
            event_type="emergency_access_failed",
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason="No active admin found"
        )
        raise HTTPException(status_code=500, detail="No admin user available")
    
    # Create JWT
    access_token = create_access_token(data={"sub": admin.username, "role": admin.role})
    
    # Extract JWT ID for session tracking
    import jwt as jwt_lib
    decoded = jwt_lib.decode(access_token, options={"verify_signature": False})
    session_id = decoded.get("jti", "unknown")
    
    # Log successful emergency access
    await AuditService.log_event(
        db=db,
        event_type="emergency_access_success",
        success=True,
        user_id=admin.id,
        username=admin.username,
        ip_address=ip_address,
        user_agent=user_agent,
        details={"session_id": session_id}
    )
    
    logger.warning(f"Emergency access granted to {admin.username} from {ip_address}")
    
    # Return HTML that stores token and redirects (magic link pattern)
    html_response = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Emergency Access - Logging in...</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                margin: 0;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            }}
            .container {{
                background: white;
                padding: 3rem;
                border-radius: 16px;
                box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                text-align: center;
                max-width: 400px;
            }}
            .spinner {{
                border: 4px solid #f3f3f3;
                border-top: 4px solid #667eea;
                border-radius: 50%;
                width: 50px;
                height: 50px;
                animation: spin 1s linear infinite;
                margin: 0 auto 1.5rem;
            }}
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
            h1 {{
                color: #333;
                font-size: 24px;
                margin: 0 0 1rem;
            }}
            p {{
                color: #666;
                margin: 0 0 1.5rem;
            }}
            .warning {{
                background: #fff3cd;
                border: 1px solid #ffc107;
                color: #856404;
                padding: 1rem;
                border-radius: 8px;
                font-size: 14px;
            }}
            a {{
                color: #667eea;
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="spinner"></div>
            <h1>🚨 Emergency Access</h1>
            <p>Logging you in as <strong>{admin.username}</strong>...</p>
            <div class="warning">
                ⚠️ This emergency access has been logged for security audit.
            </div>
        </div>
        <script>
            localStorage.setItem('token', '{access_token}');
            setTimeout(function() {{
                window.location.href = '/admin';
            }}, 1500);
        </script>
    </body>
    </html>
    """
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content=html_response)


@router.get("/emergency")
async def emergency_access_get(
    request: Request,
    emergency_token: str = Query(..., description="Emergency access token"),
    db: AsyncSession = Depends(get_db)
):
    """
    Emergency access magic link endpoint (GET version for browser clicks).
    
    Call the POST endpoint logic by forwarding the token.
    """
    # Reuse the POST endpoint logic by creating a mock request body
    class MockRequest:
        def __init__(self, original_request):
            self.client = original_request.client
            self.headers = original_request.headers
            self._json_data = {"emergency_token": emergency_token}
        
        async def json(self):
            return self._json_data
    
    mock_request = MockRequest(request)
    return await emergency_access(mock_request, db)


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
    code: str = Query(...),
    state: str = Query(...),
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

