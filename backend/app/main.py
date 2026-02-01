from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import os

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
    # Startup: Initialize database with default data
    await seed_database()
    yield
    # Shutdown: Cleanup if needed


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

# CORS middleware - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
