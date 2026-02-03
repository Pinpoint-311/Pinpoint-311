"""
System Health Check API

Tests all integrations and provides detailed status for:
- Auth0 SSO
- Google Cloud KMS (PII Encryption)
- Google Secret Manager
- Vertex AI (Gemini)
- Translation API
- Database
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, Integer
from typing import Dict, Any, Optional
import httpx
import os

from app.db.session import get_db
from app.core.auth import get_current_admin
from app.models import SystemSecret
from app.core.encryption import decrypt_safe

router = APIRouter()


async def get_config_value(db: AsyncSession, key_name: str, env_name: Optional[str] = None) -> Optional[str]:
    """
    Get a configuration value from environment variable OR database secret.
    Prioritizes env var if set, falls back to database.
    """
    # Check environment variable first
    env_key = env_name or key_name
    env_value = os.getenv(env_key)
    if env_value:
        return env_value
    
    # Fallback to database secret
    try:
        result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == key_name)
        )
        secret = result.scalar_one_or_none()
        if secret and secret.is_configured and secret.key_value:
            return decrypt_safe(secret.key_value)
    except Exception:
        pass
    
    return None


async def check_database(db: AsyncSession) -> Dict[str, Any]:
    """Test database connectivity"""
    try:
        result = await db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Database error: {str(e)}"
        }


async def check_auth0(db: AsyncSession) -> Dict[str, Any]:
    """Test Auth0 SSO configuration"""
    from app.services.auth0_service import Auth0Service
    
    try:
        status_info = await Auth0Service.check_status(db)
        return status_info
    except Exception as e:
        return {
            "status": "error",
            "message": f"Auth0 check failed: {str(e)}"
        }



async def check_google_kms(db: AsyncSession) -> Dict[str, Any]:
    """Test Google Cloud KMS for PII encryption"""
    try:
        # Check environment variables OR database secrets
        project = await get_config_value(db, "GOOGLE_CLOUD_PROJECT")
        key_ring = await get_config_value(db, "KMS_KEY_RING")
        key_id = await get_config_value(db, "KMS_KEY_ID")
        location = await get_config_value(db, "KMS_LOCATION") or "us-central1"
        
        if not project:
            return {
                "status": "not_configured",
                "message": "GCP project not configured (run Setup Wizard)",
                "project": None
            }
        
        # If project is set but specific KMS vars aren't, show as fallback mode
        if not all([key_ring, key_id]):
            return {
                "status": "fallback",
                "message": "Using Fernet encryption (KMS keyring not configured)",
                "project": project,
                "note": "Fernet encryption is secure; KMS is optional for enhanced key management"
            }
        
        # Try to encrypt/decrypt test data
        from app.core.encryption import encrypt_pii, decrypt_pii
        
        test_data = "health_check_test@example.com"
        encrypted = encrypt_pii(test_data)
        
        if not encrypted.startswith("kms:"):
            return {
                "status": "fallback",
                "message": "KMS not available, using Fernet fallback encryption",
                "project": project,
                "key_ring": key_ring,
                "key_name": key_id,
                "location": location
            }
        
        decrypted = decrypt_pii(encrypted)
        
        if decrypted == test_data:
            return {
                "status": "healthy",
                "message": "KMS encryption working correctly",
                "project": project,
                "key_ring": key_ring,
                "key_name": key_id,
                "location": location,
                "test_passed": True
            }
        else:
            return {
                "status": "error",
                "message": "KMS decrypt returned incorrect data",
                "project": project,
                "key_ring": key_ring,
                "key_name": key_id,
                "location": location
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": f"KMS check failed: {str(e)}",
            "project": os.getenv("GOOGLE_CLOUD_PROJECT"),
            "error_details": str(e)[:200]
        }


async def check_secret_manager(db: AsyncSession) -> Dict[str, Any]:
    """Test Google Secret Manager"""
    try:
        # Check for GCP project (from env OR database via Setup Wizard)
        project = await get_config_value(db, "GOOGLE_CLOUD_PROJECT")
        use_sm = os.getenv("USE_SECRET_MANAGER", "").lower() == "true"
        
        # If GCP is configured via wizard, Secret Manager is available
        has_gcp_credentials = await get_config_value(db, "GCP_SERVICE_ACCOUNT_JSON") is not None
        
        if not project:
            return {
                "status": "not_configured",
                "message": "GCP project not configured (run Setup Wizard)",
                "project": None
            }
        
        # If credentials exist from wizard, SM is available even if USE_SECRET_MANAGER not set
        if has_gcp_credentials:
            return {
                "status": "configured",
                "message": "Secret Manager available via service account",
                "project": project,
                "note": "Credentials stored in database (encrypted)"
            }
        
        from app.services.secret_manager import get_secrets_bundle
        
        # Try to fetch any secrets
        secrets = await get_secrets_bundle("TEST_")
        
        return {
            "status": "healthy",
            "message": "Secret Manager accessible",
            "project": project,
            "test_query": "SUCCESS"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Secret Manager check failed: {str(e)}",
            "project": os.getenv("GOOGLE_CLOUD_PROJECT"),
            "error_details": str(e)[:200]
        }


async def check_vertex_ai(db: AsyncSession) -> Dict[str, Any]:
    """Test Vertex AI (Gemini)"""
    try:
        project = os.getenv("GOOGLE_VERTEX_PROJECT") or await get_config_value(db, "GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_VERTEX_LOCATION", "us-central1")
        
        if not project:
            return {
                "status": "not_configured",
                "message": "GCP project not configured (run Setup Wizard)",
                "project": None,
                "location": location
            }
        
        # Try a simple test call
        from app.services.vertex_ai_service import analyze_with_gemini
        
        # Don't actually call the API to save costs, just check if it's importable
        return {
            "status": "configured",
            "message": "Vertex AI configured (not tested to save API costs)",
            "project": project,
            "location": location,
            "model": "gemini-2.0-flash-exp"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Vertex AI check failed: {str(e)}",
            "project": os.getenv("GOOGLE_VERTEX_PROJECT"),
            "error_details": str(e)[:200]
        }


async def check_translation_api(db: AsyncSession) -> Dict[str, Any]:
    """Test Google Translation API"""
    try:
        from app.services.secret_manager import get_secret
        from app.services.translation import translate_text
        
        # Check if API key is configured
        api_key = await get_secret("GOOGLE_MAPS_API_KEY")
        
        if not api_key:
            return {
                "status": "not_configured",
                "message": "Google Maps API key not configured (used for translation)",
                "has_key": False
            }
        
        # Don't actually call the API to save costs
        return {
            "status": "configured",
            "message": "Translation API configured (not tested to save API costs)",
            "has_key": True
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"Translation API check failed: {str(e)}",
            "error_details": str(e)[:200]
        }


async def check_gcp_auth(db: AsyncSession) -> Dict[str, Any]:
    """Test GCP authentication status using encrypted service account key"""
    try:
        # Check if there's an encrypted service account key
        result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == "GCP_SERVICE_ACCOUNT_JSON")
        )
        sa_secret = result.scalar_one_or_none()
        
        if sa_secret and sa_secret.is_configured:
            return {
                "status": "healthy",
                "message": "GCP service account configured (encrypted)",
                "storage": "Fernet encrypted in database"
            }
        
        return {
            "status": "not_configured",
            "message": "Not configured — upload GCP service account to enable"
        }
        
    except Exception as e:
        return {
            "status": "error",
            "message": f"GCP auth check failed: {str(e)}"
        }

@router.get("/")
async def health_check(
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_admin)
):
    """
    Comprehensive health check of all system integrations.
    
    Admin only endpoint.
    """
    
    # Run all checks
    results = {
        "database": await check_database(db),
        "auth0": await check_auth0(db),
        "gcp_auth": await check_gcp_auth(db),
        "google_kms": await check_google_kms(db),
        "google_secret_manager": await check_secret_manager(db),
        "vertex_ai": await check_vertex_ai(db),
        "translation_api": await check_translation_api(db)
    }
    
    # Calculate overall health
    statuses = [v["status"] for v in results.values()]
    
    if all(s in ["healthy", "configured", "disabled", "fallback"] for s in statuses):
        overall = "healthy"
    elif any(s == "error" for s in statuses):
        overall = "degraded"
    else:
        overall = "partial"
    
    return {
        "overall_status": overall,
        "checks": results,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }


@router.get("/quick")
async def quick_health_check():
    """
    Quick health check for monitoring (no auth required).
    
    Just checks if the API is responding.
    """
    return {
        "status": "ok",
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }


# ==================== UPTIME MONITORING ====================

from datetime import datetime, timedelta
from sqlalchemy import desc, and_
from app.models import UptimeRecord


@router.get("/uptime/history")
async def get_uptime_history(
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_admin),
    hours: int = 24
):
    """
    Get uptime history for all services over the specified time period.
    
    Args:
        hours: Number of hours to look back (default 24, max 168 = 7 days)
    """
    hours = min(hours, 168)  # Cap at 7 days
    since = datetime.utcnow() - timedelta(hours=hours)
    
    result = await db.execute(
        select(UptimeRecord)
        .where(UptimeRecord.checked_at >= since)
        .order_by(desc(UptimeRecord.checked_at))
    )
    records = result.scalars().all()
    
    # Group by service
    history = {}
    for record in records:
        if record.service_name not in history:
            history[record.service_name] = []
        history[record.service_name].append({
            "status": record.status,
            "response_time_ms": record.response_time_ms,
            "error": record.error_message,
            "checked_at": record.checked_at.isoformat() if record.checked_at else None
        })
    
    return {
        "period_hours": hours,
        "since": since.isoformat(),
        "services": history
    }


@router.get("/uptime/stats")
async def get_uptime_stats(
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_admin)
):
    """
    Get aggregated uptime statistics (24h, 7d, 30d percentages).
    """
    from sqlalchemy import func as sql_func
    
    stats = {}
    periods = {"24h": 24, "7d": 168, "30d": 720}
    
    for period_name, hours in periods.items():
        since = datetime.utcnow() - timedelta(hours=hours)
        
        # Get total checks and healthy checks per service
        result = await db.execute(
            select(
                UptimeRecord.service_name,
                sql_func.count(UptimeRecord.id).label("total"),
                sql_func.sum(
                    sql_func.cast(UptimeRecord.status == "healthy", Integer)
                ).label("healthy_count")
            )
            .where(UptimeRecord.checked_at >= since)
            .group_by(UptimeRecord.service_name)
        )
        rows = result.all()
        
        for service_name, total, healthy_count in rows:
            if service_name not in stats:
                stats[service_name] = {}
            uptime_pct = (healthy_count / total * 100) if total > 0 else 0
            stats[service_name][period_name] = {
                "uptime_percent": round(uptime_pct, 2),
                "checks": total,
                "healthy": healthy_count or 0
            }
    
    return {"services": stats}


async def record_uptime_check(
    db: AsyncSession,
    service_name: str,
    status: str,
    response_time_ms: Optional[int] = None,
    error_message: Optional[str] = None
):
    """
    Record a health check result for a service.
    Called internally after health checks.
    """
    record = UptimeRecord(
        service_name=service_name,
        status=status,
        response_time_ms=response_time_ms,
        error_message=error_message[:500] if error_message else None
    )
    db.add(record)
    await db.commit()


@router.post("/uptime/check-now")
async def trigger_uptime_check(
    db: AsyncSession = Depends(get_db),
    _: Any = Depends(get_current_admin)
):
    """
    Manually trigger an uptime check for all services and record results.
    """
    import time
    
    services_to_check = [
        ("database", check_database),
        ("auth0", check_auth0),
        ("google_kms", check_google_kms),
        ("secret_manager", check_secret_manager),
        ("vertex_ai", check_vertex_ai),
        ("translation_api", check_translation_api),
    ]
    
    results = {}
    for service_name, check_func in services_to_check:
        start = time.time()
        try:
            check_result = await check_func(db)
            response_time = int((time.time() - start) * 1000)
            status = "healthy" if check_result["status"] in ["healthy", "configured", "fallback"] else "down"
            error = None if status == "healthy" else check_result.get("message")
        except Exception as e:
            response_time = int((time.time() - start) * 1000)
            status = "down"
            error = str(e)
        
        await record_uptime_check(db, service_name, status, response_time, error)
        results[service_name] = {"status": status, "response_time_ms": response_time}
    
    return {"checked": len(results), "results": results}
