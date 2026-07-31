"""
System Health Check API

Tests all integrations and provides detailed status for:
- Auth0 SSO
- Key management for PII encryption (Google Cloud KMS, Azure Key Vault, AWS KMS,
  or the application key)
- The configured secret store (Google Secret Manager, Azure Key Vault, AWS
  Secrets Manager, or the encrypted database)
- Vertex AI (Gemini)
- Translation API
- Database
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, Integer
from typing import Dict, Any, Optional
import os

from app.db.session import get_db
from app.core.auth import get_current_admin
from app.models import SystemSecret
from app.core.encryption import decrypt_safe

router = APIRouter()


@router.get("/proactive")
async def proactive_health(
    db: AsyncSession = Depends(get_db),
    _=Depends(get_current_admin),
):
    """Leading-indicator health for admins: per-check status, values, and the
    suggested action — shown alongside the restart/diagnose runbooks. Admin-only."""
    from app.services.proactive_health import evaluate
    return await evaluate(db)


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
        pass  # Database secret not available, return None
    
    return None


async def check_database(db: AsyncSession) -> Dict[str, Any]:
    """Test database connectivity"""
    try:
        await db.execute(text("SELECT 1"))
        return {
            "status": "healthy",
            "message": "Database connection successful"
        }
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Database health check failed: {e}")
        return {
            "status": "error",
            "message": "Database connection failed"
        }


async def check_auth0(db: AsyncSession) -> Dict[str, Any]:
    """Test Auth0 SSO configuration"""
    from app.services.auth0_service import Auth0Service
    
    try:
        status_info = await Auth0Service.check_status(db)
        return status_info
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Auth0 health check failed: {e}")
        return {
            "status": "error",
            "message": "Auth0 check failed"
        }



# Names kept provider-neutral on purpose. These used to be check_google_kms and
# "Test Google Secret Manager", and both were written as a list of Google
# config variables to look for -- so a town running Azure Key Vault or AWS KMS,
# with envelope encryption working perfectly, saw "GCP project not configured"
# on its health dashboard. A health check that reports a false problem on a
# supported configuration is worse than not having one.
#
# Both now test the thing itself rather than the shape of somebody's config:
# the KMS check does a real encrypt/decrypt round trip and reports which key
# manager actually wrapped the data key, and the store check asks the same
# reachability question the migration gates on.

async def check_kms(db: AsyncSession) -> Dict[str, Any]:
    """Round-trip PII encryption and report which key manager did the wrapping.

    The selected provider is not the answer; what wrapped the key is. Those
    differ in exactly the case worth surfacing -- a KMS chosen but unreachable
    falls back to the application key silently, and this is where that shows.
    """
    try:
        from app.core.encryption import encrypt_pii, decrypt_pii, PII_V2_PREFIX, _kms_provider
        from app.core import pii_crypto

        selected = _kms_provider()

        test_data = "health_check_test@example.com"
        encrypted = encrypt_pii(test_data)
        if decrypt_pii(encrypted) != test_data:
            return {
                "status": "error",
                "message": "PII encryption round-trip returned incorrect data",
                "selected_provider": selected,
            }

        if encrypted.startswith(PII_V2_PREFIX):
            backend = pii_crypto.active_backend()
        elif encrypted.startswith("kms:"):
            backend = "google"
        elif encrypted.startswith("akv:"):
            backend = "azure"
        else:
            backend = "local"

        label = {"google": "Google Cloud KMS", "azure": "Azure Key Vault",
                 "aws": "AWS KMS"}.get(backend)

        details: Dict[str, Any] = {
            "kms_backend": backend,
            "selected_provider": selected,
            "test_passed": True,
        }
        # Only the fields that mean something for the backend in use. Reporting
        # a key ring to a town on AWS is how the Google shape leaked out before.
        if backend == "google":
            details["project"] = await get_config_value(db, "GOOGLE_CLOUD_PROJECT")
            details["key_ring"] = await get_config_value(db, "KMS_KEY_RING")
            details["key_name"] = await get_config_value(db, "KMS_KEY_ID")
            details["location"] = await get_config_value(db, "KMS_LOCATION") or "us-central1"
        elif backend == "azure":
            details["vault"] = await get_config_value(db, "AZURE_KEYVAULT_URL")
            details["key_name"] = await get_config_value(db, "AZURE_KEYVAULT_KEY")
        elif backend == "aws":
            details["key_name"] = await get_config_value(db, "AWS_KMS_KEY_ID")
            details["region"] = await get_config_value(db, "AWS_REGION")

        if label:
            return {"status": "healthy",
                    "message": f"Envelope encryption working (data key wrapped by {label})",
                    **details}

        # Local wrapping. Expected on a self-hosted install with no cloud
        # account, and a real warning when a KMS was selected and is not being
        # used -- which is silent everywhere else.
        if selected in ("google", "azure", "aws"):
            return {
                "status": "fallback",
                "message": (
                    f"PII is encrypted, but with the application key — the selected "
                    f"key manager ({selected}) is not reachable, so it is not being used."
                ),
                **details,
            }
        return {
            "status": "fallback",
            "message": "PII encryption working with a local application-key-wrapped data key (no cloud KMS configured)",
            **details,
        }

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"KMS health check failed: {e}")
        return {"status": "error", "message": "KMS check failed"}


async def check_secret_manager(db: AsyncSession) -> Dict[str, Any]:
    """Whether the configured secret store -- whichever one -- can be reached."""
    try:
        from app.services.secret_manager import _secrets_provider
        from app.services.storage_maintenance import store_reachable

        provider = _secrets_provider()
        label = {"azure": "Azure Key Vault", "aws": "AWS Secrets Manager"}.get(
            provider, "Google Secret Manager")

        if store_reachable():
            details: Dict[str, Any] = {"status": "healthy", "store": provider,
                                       "message": f"{label} accessible"}
            if provider == "google":
                details["project"] = await get_config_value(db, "GOOGLE_CLOUD_PROJECT")
            elif provider == "azure":
                details["vault"] = await get_config_value(db, "AZURE_KEYVAULT_URL")
            elif provider == "aws":
                details["region"] = await get_config_value(db, "AWS_REGION")
            return details

        # Not an error. The encrypted database is a supported store, and this is
        # the normal state of a small self-hosted install.
        return {
            "status": "not_configured",
            "store": provider,
            "message": (
                f"{label} is not reachable — secrets are held in the encrypted "
                f"database. They move across on their own once it is configured."
            ),
        }

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Secret store health check failed: {e}")
        return {"status": "error", "message": "Secret store check failed"}


async def check_vertex_ai(db: AsyncSession) -> Dict[str, Any]:
    """Test Vertex AI (Gemini)"""
    try:
        project = os.getenv("GOOGLE_VERTEX_PROJECT") or await get_config_value(db, "GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_VERTEX_LOCATION", "us-central1")
        
        if not project:
            return {
                "status": "not_configured",
                "message": "GCP project not configured (see Admin Console → Setup & Integration)",
                "project": None,
                "location": location
            }
        
        # Try a simple test call
        
        # Don't actually call the API to save costs, just check if it's importable
        return {
            "status": "configured",
            "message": "Vertex AI configured (not tested to save API costs)",
            "project": project,
            "location": location,
            "model": "gemini-3.1-flash-lite"
        }
        
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Vertex AI health check failed: {e}")
        return {
            "status": "error",
            "message": "Vertex AI check failed",
            "project": os.getenv("GOOGLE_VERTEX_PROJECT")
        }


async def check_translation_api(db: AsyncSession) -> Dict[str, Any]:
    """Test Google Translation API"""
    try:
        from app.services.secret_manager import get_secret
        
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
        import logging
        logging.getLogger(__name__).error(f"Translation API health check failed: {e}")
        return {
            "status": "error",
            "message": "Translation API check failed"
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
        import logging
        logging.getLogger(__name__).error(f"GCP auth check failed: {e}")
        return {
            "status": "error",
            "message": "GCP auth check failed"
        }

# Only the database is truly critical — without it nothing works, so a failure
# there is loud (overall "critical"). Everything else is an *optional* provider:
# if it's down the app keeps working and simply skips that feature (AI triage,
# translation, external secret store, etc.), surfaced as a non-blocking warning
# in the admin console. (PII encryption fails loud separately, at write time,
# when REQUIRE_KMS is set — see app/core/pii_crypto.py.)
CRITICAL_CHECKS = {"database"}
_OK_STATUSES = {"healthy", "configured", "disabled", "fallback"}


def classify_health(results: dict) -> dict:
    """Split check results into non-blocking warnings (optional providers that
    are down — the app still works) vs critical failures (a core dependency is
    down). Pure function so the policy is unit-testable."""
    for name, res in results.items():
        res["critical"] = name in CRITICAL_CHECKS

    critical_failures = [
        {"check": n, **results[n]}
        for n in CRITICAL_CHECKS
        if n in results and results[n].get("status") not in _OK_STATUSES
    ]
    warnings = [
        {"check": n, "detail": res.get("detail") or res.get("message") or res.get("status")}
        for n, res in results.items()
        if n not in CRITICAL_CHECKS and res.get("status") not in _OK_STATUSES
    ]

    if critical_failures:
        overall = "critical"      # loud: a core dependency is down
    elif warnings:
        overall = "degraded"      # optional provider(s) skipped, app still works
    else:
        overall = "healthy"

    return {
        "overall_status": overall,
        "checks": results,
        "warnings": warnings,
        "critical_failures": critical_failures,
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
        # Renamed from google_kms / google_secret_manager. The old keys named a
        # vendor for a slot that has four options, and the dashboard rendered
        # them under Google headings whatever the town was actually running.
        # Not aliased alongside the new keys: classify_health derives the
        # overall status from this dict, so a duplicated entry would weight
        # these two checks twice.
        "kms": await check_kms(db),
        "secret_store": await check_secret_manager(db),
        "vertex_ai": await check_vertex_ai(db),
        "translation_api": await check_translation_api(db)
    }

    classified = classify_health(results)
    return {**classified, "timestamp": __import__("datetime").datetime.now().isoformat()}


@router.get("/quick")
async def quick_health_check(db: AsyncSession = Depends(get_db)):
    """
    Quick health check for monitoring (no auth required).

    Carries the build/migration stamp (ORCHESTRATOR_PLAN.md A3) so the
    orchestrator can gate canary rollouts on version + DB-revision
    compatibility. Fields are null when the deployment doesn't set them.
    """
    from app.core.config import get_settings

    settings = get_settings()
    db_revision = None
    try:
        result = await db.execute(text("SELECT version_num FROM alembic_version"))
        db_revision = result.scalar_one_or_none()
    except Exception:
        pass  # no alembic_version table (fresh or non-migrated DB)

    return {
        "status": "ok",
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "db_revision": db_revision,
        "min_db_revision": settings.min_db_revision,
        "timestamp": __import__("datetime").datetime.now().isoformat()
    }


@router.get("/version")
async def version_info(db: AsyncSession = Depends(get_db)):
    """Build + schema version stamp for the orchestrator/control plane.

    Metadata only (no resident data) — the panel polls this fleet-wide to
    detect version drift and gate canary rollouts on DB-migration compatibility.
    """
    from app.core.config import get_settings
    from sqlalchemy import text
    settings = get_settings()
    db_revision = None
    try:
        db_revision = (await db.execute(text("SELECT version_num FROM alembic_version LIMIT 1"))).scalar()
    except Exception:
        db_revision = None  # alembic table absent (fresh DB) — panel treats as unmigrated
    return {
        "version": settings.app_version,
        "git_sha": settings.git_sha,
        "app_name": settings.app_name,
        "managed_mode": settings.managed_mode,
        "db_revision": db_revision,
    }


# ==================== UPTIME MONITORING ====================

from datetime import datetime, timedelta
from sqlalchemy import desc
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

    from app.services.uptime import describe, summarise

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
            # Denominator is time, not rows.
            #
            # The sampler runs inside the backend, so a backend outage produces
            # no rows rather than rows saying "down" -- and healthy/total over
            # the rows that exist returns a *higher* figure the worse the
            # outage was. Twelve samples in a day is about an hour of uptime and
            # the old arithmetic called it 100%.
            summary = summarise(total=total, healthy=healthy_count or 0, hours=hours)
            summary["summary"] = describe(summary)
            stats[service_name][period_name] = summary
    
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
        # Series names, not display names -- see the note in main.py.
        ("kms", check_kms),
        ("secret_store", check_secret_manager),
        ("vertex_ai", check_vertex_ai),
        ("translation_api", check_translation_api),
    ]
    
    from app.services.uptime import uptime_status

    results = {}
    for service_name, check_func in services_to_check:
        start = time.time()
        try:
            check_result = await check_func(db)
            response_time = int((time.time() - start) * 1000)
            status = uptime_status(check_result["status"])
            error = None if status == "healthy" else check_result.get("message")
        except Exception as e:
            response_time = int((time.time() - start) * 1000)
            status = "down"
            error = str(e)
        
        await record_uptime_check(db, service_name, status, response_time, error)
        results[service_name] = {"status": status, "response_time_ms": response_time}
    
    return {"checked": len(results), "results": results}
