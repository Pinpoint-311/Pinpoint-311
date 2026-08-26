from fastapi import APIRouter, Depends, HTTPException, Query, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from typing import Optional
import secrets
import logging
import os
import urllib.parse

from app.db.session import get_db
from app.models import User
import secrets as pysecrets

from app.core.auth import create_access_token, decode_token, get_current_user
from app.services.auth0_service import Auth0Service
from app.services.audit_service import AuditService
# Login state tokens live in Redis (app/services/login_state.py) so that a
# backend restart mid-login does not invalidate the round-trip already in flight.
from app.services import login_state

router = APIRouter()
logger = logging.getLogger(__name__)

# A strict ceiling on the first-run admin-password endpoints, on top of the
# lockout below. Keyed per caller (app/core/client_ip.py), so one attacker
# cannot spend the whole town's budget.
from slowapi import Limiter
from app.core.client_ip import rate_limit_key

limiter = Limiter(key_func=rate_limit_key)


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


# One-time bootstrap tokens (only work until Auth0 is configured)
_bootstrap_tokens: dict = {}


# ---------------------------------------------------------------------------
# Bootstrap brute-force defence
# ---------------------------------------------------------------------------
#
# /bootstrap and /bootstrap/verify accept a password and mint an ADMIN session
# on a match. The gate is open on any deployment with no identity provider,
# which is every town between install and SSO setup -- and both live demo
# instances right now. The comparison is constant-time and a weak default is
# refused, but nothing bounded how many guesses an anonymous caller could make:
# the endpoint was an unthrottled admin-password oracle answering as fast as the
# process could reply.
#
# Two tiers, pulling deliberately in opposite directions:
#
#   HARD TIER, per caller address. Consecutive failures from one address earn an
#   escalating lockout. It bites hard because an attacker can only ever lock out
#   *themselves*: with the client address now resolved through the trusted-proxy
#   rule (app/core/client_ip.py) it cannot be forged into somebody else's
#   bucket, and a success clears it.
#
#   SOFT TIER, deployment-wide. A distributed attacker spreads guesses across
#   addresses and never trips the hard tier, so failures are also counted across
#   all callers. This tier is CAPPED AND NEVER RE-ARMS: once it engages it makes
#   every attempt cost a fixed short pause and it stops there, expiring on its
#   own. It must not escalate and must not refuse, because anything that did
#   would hand any anonymous caller on the internet a way to lock the town's
#   legitimate administrator out of their own first-run setup -- turning a
#   brute-force defence into a denial-of-service weapon aimed at the one person
#   it exists to protect. Making a distributed attack expensive is worth having;
#   making first-run setup blockable by strangers is not.
#
# In-memory, like `_bootstrap_tokens` above, and for the same reason: a town
# runs one backend process, and bootstrap is a minutes-long window at install
# time. A restart clears the counters, which costs an attacker far more than it
# costs an admin (they would have to be watching for it).

_BOOTSTRAP_FREE_ATTEMPTS = 3       # guesses before the hard tier starts locking
_BOOTSTRAP_BASE_LOCKOUT = 5.0      # seconds, doubling per failure past the free ones
_BOOTSTRAP_MAX_LOCKOUT = 900.0     # 15 minutes; long enough to be useless to a script
_BOOTSTRAP_FAILURE_TTL = 3600.0    # a quiet hour forgets an address entirely

_BOOTSTRAP_GLOBAL_WINDOW = 900.0   # rolling 15 minutes
_BOOTSTRAP_GLOBAL_TRIGGER = 20     # failures across all addresses before the soft tier
_BOOTSTRAP_GLOBAL_PAUSE = 1.0      # fixed, never escalates, never refuses

# address -> (consecutive_failures, locked_until, last_seen)
_bootstrap_failures: dict = {}
# timestamps of recent failures from any address
_bootstrap_global_failures: list = []


def _bootstrap_client(request: Optional[Request]) -> str:
    """Which bucket this attempt counts against."""
    if request is None:
        return "unknown-client"
    from app.core.client_ip import client_ip

    return client_ip(request) or "unknown-client"


def _bootstrap_prune(now: float) -> None:
    for key, (_fails, _until, last_seen) in list(_bootstrap_failures.items()):
        if now - last_seen > _BOOTSTRAP_FAILURE_TTL:
            _bootstrap_failures.pop(key, None)
    cutoff = now - _BOOTSTRAP_GLOBAL_WINDOW
    while _bootstrap_global_failures and _bootstrap_global_failures[0] < cutoff:
        _bootstrap_global_failures.pop(0)


def bootstrap_lockout_seconds(client: str, now: Optional[float] = None) -> float:
    """Seconds this address must wait, or 0. Pure read — never records."""
    import time as _time

    now = _time.time() if now is None else now
    _bootstrap_prune(now)
    entry = _bootstrap_failures.get(client)
    if not entry:
        return 0.0
    _fails, locked_until, _last = entry
    return max(0.0, locked_until - now)


def note_bootstrap_failure(client: str, now: Optional[float] = None) -> None:
    """Record one wrong password and extend this address's lockout."""
    import time as _time

    now = _time.time() if now is None else now
    _bootstrap_prune(now)
    fails, _locked_until, _last = _bootstrap_failures.get(client, (0, 0.0, now))
    fails += 1
    if fails > _BOOTSTRAP_FREE_ATTEMPTS:
        penalty = min(
            _BOOTSTRAP_BASE_LOCKOUT * (2 ** (fails - _BOOTSTRAP_FREE_ATTEMPTS - 1)),
            _BOOTSTRAP_MAX_LOCKOUT,
        )
    else:
        penalty = 0.0
    _bootstrap_failures[client] = (fails, now + penalty, now)
    _bootstrap_global_failures.append(now)


def note_bootstrap_success(client: str) -> None:
    """A correct password clears this address. The soft tier is left alone."""
    _bootstrap_failures.pop(client, None)


def bootstrap_global_pause(now: Optional[float] = None) -> float:
    """The soft tier's fixed pause, or 0. Capped by construction."""
    import time as _time

    now = _time.time() if now is None else now
    _bootstrap_prune(now)
    if len(_bootstrap_global_failures) >= _BOOTSTRAP_GLOBAL_TRIGGER:
        return _BOOTSTRAP_GLOBAL_PAUSE
    return 0.0


def _reset_bootstrap_throttle() -> None:
    """Test hook. Nothing in the request path calls this."""
    _bootstrap_failures.clear()
    _bootstrap_global_failures.clear()


async def _guard_bootstrap_attempt(request: Optional[Request]) -> str:
    """Raise 429 if this address is locked out; apply the capped global pause.

    Returns the caller key so the handler can record the outcome.
    """
    import asyncio

    client = _bootstrap_client(request)
    wait = bootstrap_lockout_seconds(client)
    if wait > 0:
        from app.core.sanitize import sanitize_for_log

        logger.warning(
            "Bootstrap attempt refused, address locked out: %s",
            sanitize_for_log(client),
        )
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many incorrect setup passwords from this address. "
                f"Try again in {int(wait) + 1} seconds."
            ),
            headers={"Retry-After": str(int(wait) + 1)},
        )
    pause = bootstrap_global_pause()
    if pause:
        await asyncio.sleep(pause)
    return client


async def _bootstrap_gate_open(db: AsyncSession) -> bool:
    """Bootstrap is permitted ONLY when NO identity provider is configured
    (Auth0, Entra, Okta, or generic OIDC).

    Fail-closed: gates on the *presence* of identity config, not its
    reachability, so an IdP outage cannot re-open passwordless admin access.
    """
    return not await Auth0Service.is_identity_configured(db)


def _verify_bootstrap_password(supplied: str) -> None:
    """Require the deploy-time INITIAL_ADMIN_PASSWORD to authorize bootstrap.

    Rejects the known default so a deployment that never set it cannot be
    bootstrapped by an anonymous caller. Constant-time comparison.
    """
    from app.core.config import get_settings, INSECURE_SECRET_KEYS  # noqa
    settings = get_settings()
    expected = settings.initial_admin_password or ""
    if not expected or expected == "admin123":
        raise HTTPException(
            status_code=403,
            detail="Bootstrap is disabled: set a strong INITIAL_ADMIN_PASSWORD in the environment to enable first-run admin access.",
        )
    if not supplied or not secrets.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=401, detail="Invalid bootstrap password.")


@router.post("/bootstrap")
@limiter.limit("5/minute")
async def generate_bootstrap_token(
    request: Request,
    password: str = Form(..., description="INITIAL_ADMIN_PASSWORD to authorize bootstrap"),
    db: AsyncSession = Depends(get_db)
):
    """
    Generate a one-time magic link for admin access.

    ONLY works when Auth0 is NOT configured. This allows the initial admin
    to log in and configure Auth0. Once Auth0 is configured, this endpoint
    returns an error.

    Requires the INITIAL_ADMIN_PASSWORD from environment to authorize.

    The password is a FORM FIELD, not a query parameter. It was a query
    parameter, which put the deployment's admin password in plaintext in every
    uvicorn access line, in the proxy's log, and in anything that ships those
    logs onward -- a secret that has to be rotated after anyone reads a log
    file. Its sibling /bootstrap/verify already took a form field; this now
    matches it.
    """
    client = await _guard_bootstrap_attempt(request)
    # Fail-closed: only when Auth0 has never been configured
    if not await _bootstrap_gate_open(db):
        raise HTTPException(
            status_code=403,
            detail="Bootstrap access disabled - Auth0 is already configured. Use SSO to log in."
        )
    try:
        _verify_bootstrap_password(password)
    except HTTPException:
        note_bootstrap_failure(client)
        raise
    note_bootstrap_success(client)

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


def _bootstrap_html_message(title: str, body_html: str, status_code: int):
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        content=f"""<!DOCTYPE html><html><head><title>{title}</title></head>
        <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#151929;color:white;text-align:center">
        <div style="max-width:24rem">{body_html}</div></body></html>""",
        status_code=status_code,
    )


@router.get("/bootstrap/auto")
async def auto_bootstrap(
    db: AsyncSession = Depends(get_db)
):
    """
    Browser-based first-run bootstrap. Renders a password prompt (the
    INITIAL_ADMIN_PASSWORD) which POSTs to /bootstrap/verify.

    ONLY works when Auth0 is NOT configured. This is the recommended way for
    first-time setup. The login page links here.
    """
    if not await _bootstrap_gate_open(db):
        return _bootstrap_html_message(
            "Setup Complete",
            '<h2>Auth0 is already configured</h2><p>Use SSO to log in.</p>'
            '<a href="/login" style="color:#6366f1">Go to Login</a>',
            403,
        )

    # Render a password form — no token is minted without the deploy-time secret.
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="""<!DOCTYPE html>
    <html>
    <head><title>First-run setup</title></head>
    <body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#151929;color:white;text-align:center">
        <form method="POST" action="/api/auth/bootstrap/verify" style="max-width:22rem">
            <div style="font-size:2rem;margin-bottom:1rem">✦</div>
            <h2 style="margin:0 0 .5rem">Welcome to Pinpoint 311</h2>
            <p style="color:rgba(255,255,255,.6);margin-bottom:1rem">Enter the setup password (<code>INITIAL_ADMIN_PASSWORD</code>) to create your admin session.</p>
            <input type="password" name="password" required autofocus placeholder="Setup password"
                style="width:100%;padding:.6rem;border-radius:.5rem;border:1px solid #333;background:#0f1220;color:white;margin-bottom:.75rem" />
            <button type="submit" style="width:100%;padding:.6rem;border-radius:.5rem;border:0;background:#6366f1;color:white;font-weight:600;cursor:pointer">Continue</button>
        </form>
    </body>
    </html>""")


@router.post("/bootstrap/verify")
@limiter.limit("5/minute")
async def verify_bootstrap(
    request: Request,
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """Validate the setup password and mint the initial admin session."""
    try:
        client = await _guard_bootstrap_attempt(request)
    except HTTPException as e:
        # This path renders HTML: the form at /bootstrap/auto posts here from a
        # browser, and a JSON body would be shown to a human as raw text.
        return _bootstrap_html_message(
            "Too many attempts",
            f'<h2>Too many attempts</h2><p>{e.detail}</p>',
            e.status_code,
        )
    if not await _bootstrap_gate_open(db):
        return _bootstrap_html_message(
            "Setup Complete",
            '<h2>Auth0 is already configured</h2><a href="/login" style="color:#6366f1">Go to Login</a>',
            403,
        )
    try:
        _verify_bootstrap_password(password)
    except HTTPException as e:
        note_bootstrap_failure(client)
        return _bootstrap_html_message(
            "Setup",
            f'<h2>Could not continue</h2><p>{e.detail}</p>'
            '<a href="/api/auth/bootstrap/auto" style="color:#6366f1">Try again</a>',
            e.status_code,
        )
    note_bootstrap_success(client)

    result = await db.execute(
        select(User).where(User.role == "admin", User.is_active == True).limit(1)
    )
    admin = result.scalar_one_or_none()
    if not admin:
        return _bootstrap_html_message(
            "Setup Error",
            '<h2>No admin user found</h2><p>The database may not be initialized yet.</p>',
            404,
        )

    access_token = create_access_token(data={"sub": admin.username, "role": admin.role})
    logger.info(f"Bootstrap login successful for: {admin.username}")

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
    
    # Fail-closed: only when Auth0 has never been configured
    if not await _bootstrap_gate_open(db):
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
            detail="Authentication not configured. Please configure your identity provider in the Admin Console."
        )
    
    # Generate state token for CSRF protection
    state = secrets.token_urlsafe(32)
    await login_state.remember(state, redirect_uri)
    
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
    redirect_uri = await login_state.consume(state)
    if not redirect_uri:
        raise HTTPException(
            status_code=400,
            detail="This sign-in link is no longer valid. Please start signing in again."
        )
        
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
        
        # Create our own JWT token. Mint the session id up front rather than
        # decoding the token we just signed -- the old code read `jti` back out
        # of a token that never carried one, so every login_success row logged
        # session_id="unknown".
        session_id = pysecrets.token_hex(16)
        access_token = create_access_token(
            data={"sub": user.username, "role": user.role, "jti": session_id}
        )
        
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
            # Verify the signature: this token came from the client, and an
            # unverified decode would let a caller write any session id they
            # liked into the audit trail.
            session_id = decode_token(token).get("jti", "unknown")
        except Exception:
            pass  # Invalid/expired token, session_id stays "unknown"
    
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


# ============ Onboarding link redemption (managed hosting, plan A4) ============

_ONBOARDING_JTI_PREFIX = "ONBOARDING_JTI_"


@router.post("/onboarding/redeem")
async def redeem_onboarding_token(
    token: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a one-time onboarding link (minted by the provisioning API)
    for a normal short-lived admin session.

    The link token carries purpose="onboarding" so it is useless against the
    API directly (get_current_user rejects it); redeeming burns its jti, so
    the link works exactly once.
    """
    from app.core.auth import decode_token
    from app.models import SystemSecret

    payload = decode_token(token)  # 401 on bad signature / expiry
    if payload.get("purpose") != "onboarding" or not payload.get("jti"):
        raise HTTPException(status_code=401, detail="Not an onboarding token")

    jti_key = f"{_ONBOARDING_JTI_PREFIX}{payload['jti']}"
    result = await db.execute(select(SystemSecret).where(SystemSecret.key_name == jti_key))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=401, detail="Onboarding link already used")

    result = await db.execute(select(User).where(User.username == payload.get("sub")))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Onboarding account unavailable")

    # Burn the jti (single use), then issue a normal session token.
    db.add(SystemSecret(key_name=jti_key, key_value=None, is_configured=True,
                        description="Redeemed onboarding link"))
    await db.commit()

    session_token = create_access_token(data={"sub": user.username})
    await AuditService.log_event(
        db,
        event_type="onboarding_redeemed",
        success=True,
        username=user.username,
        user_id=user.id,
        details={"jti": payload["jti"]},
    )
    return {
        "access_token": session_token,
        "token_type": "bearer",
        "username": user.username,
        "role": user.role,
    }


@router.get("/status")
async def auth_status(db: AsyncSession = Depends(get_db)):
    """
    Get authentication configuration status.
    """
    from app.services.identity import IDENTITY_CATALOG

    status_info = await Auth0Service.check_status(db)
    configured = status_info["status"] == "configured"

    # `provider` was the literal "auth0" regardless of what was configured, so
    # a town on Entra was still told -- and still showed staff -- Auth0.
    provider = status_info.get("provider") or "auth0"
    label = IDENTITY_CATALOG.get(provider, {}).get("name", provider)

    return {
        # Kept under its original name: the login page and older clients read it.
        "auth0_configured": configured,
        "provider": provider if configured else None,
        "provider_name": label if configured else None,
        "message": "Ready" if configured else f"{label} not configured"
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
