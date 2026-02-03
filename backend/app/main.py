from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import os
import sentry_sdk

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

from app.api import auth, users, departments, services, system, open311, gis, map_layers, comments, research, health, audit, setup
from app.db.init_db import seed_database

# Rate limiting setup
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address, default_limits=["500/minute"])


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses for government compliance."""
    
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # Enable XSS protection (legacy browsers)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Content Security Policy (basic)
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        
        # Prevent caching of sensitive data
        if "/api/" in str(request.url):
            response.headers["Cache-Control"] = "no-store, max-age=0"
        
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
                    from datetime import datetime, timedelta
                    from sqlalchemy import delete
                    from app.models import UptimeRecord
                    cutoff = datetime.utcnow() - timedelta(days=30)
                    result = await db.execute(
                        delete(UptimeRecord).where(UptimeRecord.checked_at < cutoff)
                    )
                    await db.commit()
                    deleted = result.rowcount
                    
                    if deleted > 0:
                        print(f"[Uptime Monitor] Health check complete, cleaned up {deleted} old records")
                    else:
                        print(f"[Uptime Monitor] Health check complete at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception as e:
                print(f"[Uptime Monitor] Error: {e}")
            
            # Wait 5 minutes before next check
            await asyncio.sleep(300)
    
    # Startup: Initialize database with default data
    await seed_database()
    
    # Start background uptime monitoring task
    uptime_task = asyncio.create_task(uptime_monitor())
    print("[Uptime Monitor] Started background health monitoring (every 5 minutes)")
    
    yield
    
    # Shutdown: Cancel background task
    uptime_task.cancel()
    try:
        await uptime_task
    except asyncio.CancelledError:
        pass
    print("[Uptime Monitor] Stopped background health monitoring")


app = FastAPI(
    title="Township 311 API",
    description="Open311-compliant civic engagement platform for municipal request management",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Security headers middleware (added first, runs last)
app.add_middleware(SecurityHeadersMiddleware)

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
app.include_router(setup.router, prefix="/api/setup", tags=["Setup Wizard"])

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


@app.get("/api/sentry-debug")
async def sentry_debug():
    """Test endpoint to verify Sentry integration. Raises an intentional error."""
    if not SENTRY_DSN:
        return {"status": "sentry_not_configured", "message": "Set SENTRY_DSN env var to enable"}
    # Intentional error for testing
    raise Exception("Sentry test error - this is intentional!")

