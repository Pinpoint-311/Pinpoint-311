from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import os
import logging
import sentry_sdk

logger = logging.getLogger(__name__)

# Initialize Sentry for error tracking (optional - set SENTRY_DSN env var)
SENTRY_DSN = os.environ.get("SENTRY_DSN")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=0.1,  # 10% of requests for performance monitoring
        profiles_sample_rate=0.1,
        environment=os.environ.get("ENVIRONMENT", "production"),
        send_default_pii=False,  # Don't send personally identifiable info
    )

from app.api import auth, users, departments, services, system, open311, gis, map_layers, comments, research, health, audit, setup, api_usage, data_export, integrations, provisioning, telemetry
from app.db.init_db import seed_database

# Rate limiting setup
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Tighter rate limits in demo mode to protect shared API keys
_demo_mode = os.environ.get("DEMO_MODE", "").lower() in ("true", "1", "yes")
_default_limit = "100/minute" if _demo_mode else "500/minute"
limiter = Limiter(key_func=get_remote_address, default_limits=[_default_limit])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses for government compliance."""
    
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Skip security headers for developer docs pages (they need CDN resources)
        request_path = request.url.path
        if request_path in ["/api/docs", "/api/redoc"]:
            return response
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Enable XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Content Security Policy
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"

        # Force HTTPS for a year on this host and its subdomains (HSTS). Sent on
        # every response; browsers only honor it over TLS, so it's harmless on
        # plain HTTP. Both demo hosts serve over HTTPS behind the proxy.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Restrict powerful browser features to only what the app uses
        # (geolocation for the map picker); deny the rest.
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=(), payment=(), usb=()"

        # Prevent caching of sensitive data
        if "/api/" in request_path:
            response.headers["Cache-Control"] = "no-store, max-age=0"
        
        return response


class DemoModeMiddleware(BaseHTTPMiddleware):
    """In DEMO_MODE, block mutating requests to admin/system routes.
    
    Resident portal submissions are allowed.
    Staff dashboard reads are allowed.
    Admin config changes are blocked.
    """
    
    # Routes where mutations ARE allowed in demo mode
    ALLOWED_MUTATION_PREFIXES = [
        "/api/open311/",        # Public request submissions
        "/api/auth/",           # Auth flows (demo-login, bootstrap)
        "/api/gis/",            # Geocoding lookups
        "/api/system/upload/",  # Image uploads for requests
        "/api/system/translate/",  # Translation requests
        "/api/research/",       # Research suite
        "/api/system/analytics-chat", # AI Analytics Advisor
        "/api/services/reorder",  # Service category reordering
        "/api/system/client-errors",  # Frontend error reporting
        "/api/system/update",          # Admin code update (admin-auth protected)
    ]
    
    async def dispatch(self, request: Request, call_next):
        from app.core.config import get_settings
        settings = get_settings()
        
        if not settings.demo_mode:
            return await call_next(request)
        
        method = request.method.upper()
        path = request.url.path
        
        # Allow all GET/HEAD/OPTIONS requests
        if method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        
        # Allow mutations on whitelisted routes
        for prefix in self.ALLOWED_MUTATION_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        
        # Block all other mutations
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=403,
            content={"detail": "Demo mode — this action is disabled. Deploy your own instance to configure settings."},
        )


class ManagedModeMiddleware(BaseHTTPMiddleware):
    """Managed-hosting hooks that run on every request (ORCHESTRATOR_PLAN.md).

    - Counts responses by status class for the PII-free telemetry endpoint (A5).
    - Honors the panel-set suspended state (A7): everything except health and
      the provisioning surface answers 503 until the state resumes the town.
    """

    SUSPEND_EXEMPT_PREFIXES = ("/api/health", "/api/provisioning")

    async def dispatch(self, request: Request, call_next):
        from app.core.managed import get_lifecycle_state

        path = request.url.path
        if (
            get_lifecycle_state() == "suspended"
            and path.startswith("/api")
            and not path.startswith(self.SUSPEND_EXEMPT_PREFIXES)
        ):
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=503,
                content={"detail": "This instance has been suspended by your state. Contact your state program administrator."},
            )

        response = await call_next(request)
        if path.startswith("/api"):
            from app.api.telemetry import record_request
            record_request(response.status_code)
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle manager"""
    import asyncio
    from app.db.session import SessionLocal
    from app.api.health import (
        check_database, check_auth0, check_google_kms,
        check_secret_manager, check_vertex_ai, check_translation_api,
        record_uptime_check
    )
    import time
    
    # Background task for uptime monitoring
    async def uptime_monitor():
        """Run health checks every 5 minutes and record results."""
        while True:
            try:
                async with SessionLocal() as db:
                    services_to_check = [
                        ("database", check_database),
                        ("auth0", check_auth0),
                        ("google_kms", check_google_kms),
                        ("secret_manager", check_secret_manager),
                        ("vertex_ai", check_vertex_ai),
                        ("translation_api", check_translation_api),
                    ]
                    
                    for service_name, check_func in services_to_check:
                        start = time.time()
                        try:
                            check_result = await check_func(db)
                            response_time = int((time.time() - start) * 1000)
                            status = "healthy" if check_result["status"] in ["healthy", "configured", "fallback", "disabled"] else "down"
                            error = None if status == "healthy" else check_result.get("message")
                        except Exception as e:
                            response_time = int((time.time() - start) * 1000)
                            status = "down"
                            error = str(e)
                        
                        await record_uptime_check(db, service_name, status, response_time, error)
                    
                    # Cleanup: Delete records older than 30 days
                    from datetime import datetime, timedelta, timezone
                    from sqlalchemy import delete
                    from app.models import UptimeRecord
                    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                    result = await db.execute(
                        delete(UptimeRecord).where(UptimeRecord.checked_at < cutoff)
                    )
                    await db.commit()
                    deleted = result.rowcount
                    
                    if deleted > 0:
                        logger.info(f"[Uptime Monitor] Health check complete, cleaned up {deleted} old records")
                    else:
                        logger.debug(f"[Uptime Monitor] Health check complete at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                logger.error(f"[Uptime Monitor] Error: {e}")
            
            # Wait 5 minutes before next check
            await asyncio.sleep(300)
    
    # Fail closed on insecure security configuration (default SECRET_KEY, etc.)
    from app.core.config import get_settings as _get_settings
    _settings = _get_settings()
    _security_problems = _settings.validate_security()
    if _security_problems:
        _msg = "Insecure security configuration:\n  - " + "\n  - ".join(_security_problems)
        if _settings.debug:
            logger.warning(f"[Security] {_msg}\n[Security] Continuing because debug=True — DO NOT run like this in production.")
        else:
            logger.critical(f"[Security] {_msg}")
            raise RuntimeError(
                "Refusing to start with insecure security configuration. "
                "Set a strong SECRET_KEY (or set DEBUG=true for local development only). " + _msg
            )

    # Startup: Initialize database with default data
    await seed_database()

    # Load the panel-set lifecycle state (managed hosting suspend/resume)
    from app.core.managed import load_lifecycle_state
    async with SessionLocal() as _lifecycle_db:
        _state = await load_lifecycle_state(_lifecycle_db)
    if _state == "suspended":
        logger.warning("[Managed] Instance is SUSPENDED — API serves 503 until the state resumes it")

    # Start background uptime monitoring task
    uptime_task = asyncio.create_task(uptime_monitor())
    logger.info("[Uptime Monitor] Started background health monitoring (every 5 minutes)")
    
    yield
    
    # Shutdown: Cancel background task
    uptime_task.cancel()
    try:
        await uptime_task
    except asyncio.CancelledError:
        pass  # Expected during shutdown
    logger.info("[Uptime Monitor] Stopped background health monitoring")


# Only expose the API schema/docs when debug is on. In production these
# would hand an attacker a full map of every route and model.
from app.core.config import get_settings as _get_settings_for_docs
_docs_enabled = _get_settings_for_docs().debug

app = FastAPI(
    title="Township 311 API",
    description="Open311-compliant civic engagement platform for municipal request management",
    version="1.0.0",
    docs_url=None,  # Disable default - we serve custom below (debug only)
    redoc_url="/api/redoc" if _docs_enabled else None,
    openapi_url="/api/openapi.json" if _docs_enabled else None,
    lifespan=lifespan
)


from fastapi.responses import HTMLResponse

@app.get("/api/docs", include_in_schema=False)
async def custom_swagger_ui():
    """Custom Swagger UI that explicitly loads all required JS/CSS. Debug only."""
    if not _docs_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
<title>Township 311 API - Swagger UI</title>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
<script>
SwaggerUIBundle({
    url: '/api/openapi.json',
    dom_id: '#swagger-ui',
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
    layout: 'StandaloneLayout'
});
</script>
</body>
</html>
""")

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers middleware (added first, runs last)
app.add_middleware(SecurityHeadersMiddleware)

# Demo mode middleware — block admin mutations
app.add_middleware(DemoModeMiddleware)

# Managed hosting: suspend gate + telemetry request counters
app.add_middleware(ManagedModeMiddleware)

# CORS middleware - use environment-based origins for production security
# In production, set CORS_ORIGINS environment variable (comma-separated)
import os
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "").split(",") if os.environ.get("CORS_ORIGINS") else []

# If no origins specified, allow localhost for development only
if not CORS_ORIGINS or CORS_ORIGINS == ['']:
    CORS_ORIGINS = [
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Alternative dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/users", tags=["Users"])
app.include_router(departments.router, prefix="/api/departments", tags=["Departments"])
app.include_router(services.router, prefix="/api/services", tags=["Services"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(open311.router, prefix="/api/open311/v2", tags=["Open311"])
app.include_router(gis.router, prefix="/api/gis", tags=["GIS"])
app.include_router(map_layers.router, prefix="/api/map-layers", tags=["Map Layers"])
app.include_router(comments.router, tags=["Comments"])
app.include_router(research.router, prefix="/api/research", tags=["Research Suite"])
app.include_router(health.router, prefix="/api/health", tags=["Health Check"])
app.include_router(audit.router, prefix="/api/audit", tags=["Audit Logs"])
app.include_router(setup.router, prefix="/api/setup", tags=["Setup"])
app.include_router(provisioning.router, prefix="/api/provisioning", tags=["Provisioning (orchestrator)"])
app.include_router(telemetry.router, prefix="/api/telemetry", tags=["Telemetry (orchestrator)"])
app.include_router(api_usage.router, prefix="/api/system/api-usage", tags=["API Usage"])

app.include_router(data_export.router, prefix="/api", tags=["Data Export"])
app.include_router(integrations.router, prefix="/api/integrations", tags=["GovTech Integrations"])

# Built-in practice vendor so integrations can be verified without any real
# platform account (see app/api/integration_sandbox.py). The "Practice Sandbox"
# connector card advertises "no account needed — try it now", so this MUST be
# available in every deployment or the connection check 404s.
#
# It is safe to mount unconditionally: the endpoints only ever read/write an
# ephemeral, process-local, size-bounded in-memory store — they never touch the
# real request database. Records only reach the live pipeline when authenticated
# staff explicitly configure and enable the Practice Sandbox connector, which
# then pulls from here like any other vendor. Operators who want it gone can set
# DISABLE_INTEGRATION_SANDBOX=true.
_sandbox_disabled = os.environ.get("DISABLE_INTEGRATION_SANDBOX", "").lower() in ("true", "1", "yes")
if not _sandbox_disabled:
    from app.api import integration_sandbox
    app.include_router(integration_sandbox.router, prefix="/api/integrations/sandbox-vendor", tags=["Integration Sandbox"])
    logger.info("[Integrations] Practice sandbox vendor mounted")

# Mount uploads directory for serving uploaded files
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/project/uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": "1.0.0"}


@app.get("/")
async def root():
    """Root endpoint - redirect info"""
    return {
        "message": "Township 311 API",
        "docs": "/api/docs",
        "health": "/api/health"
    }


@app.get("/api/demo/info")
async def demo_info():
    """Returns demo mode status and configuration for the frontend."""
    from app.core.config import get_settings
    settings = get_settings()
    return {
        "demo_mode": settings.demo_mode,
        "message": "Welcome to the Pinpoint 311 demo! Explore the system freely." if settings.demo_mode else None,
    }


@app.get("/api/sentry-debug")
async def sentry_debug():
    """Test endpoint to verify Sentry integration. Only available in debug mode."""
    from app.core.config import get_settings
    if not get_settings().debug:
        raise HTTPException(status_code=404, detail="Not found")
    if not SENTRY_DSN:
        return {"status": "sentry_not_configured", "message": "Set SENTRY_DSN env var to enable"}
    # Intentional error for testing
    raise Exception("Sentry test error - this is intentional!")


# Client error logging endpoint
from pydantic import BaseModel
from typing import Optional
import logging

client_error_logger = logging.getLogger("client_errors")

class ClientError(BaseModel):
    type: str
    message: str
    stack: Optional[str] = None
    componentStack: Optional[str] = None
    source: Optional[str] = None
    lineno: Optional[int] = None
    colno: Optional[int] = None
    url: Optional[str] = None
    timestamp: Optional[str] = None
    userAgent: Optional[str] = None

@app.post("/api/system/client-errors", status_code=204)
async def log_client_error(error: ClientError):
    """Log frontend errors for monitoring."""
    import re
    def sanitize(text):
        if not text: return text
        return re.sub(r'[\r\n]+', ' ', str(text))

    client_error_logger.error(
        f"[CLIENT {sanitize(error.type)}] {sanitize(error.message)} | url={sanitize(error.url)} | "
        f"source={sanitize(error.source)}:{error.lineno}:{error.colno} | "
        f"ua={sanitize(error.userAgent)[:60] if error.userAgent else 'unknown'}"
    )
    if error.stack:
        client_error_logger.debug(f"Stack: {sanitize(error.stack)[:500]}")
    return Response(status_code=204)
