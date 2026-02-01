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
from sqlalchemy import text
from typing import Dict, Any
import httpx
import os

from app.db.session import get_db
from app.core.auth import get_current_admin

router = APIRouter()


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



async def check_google_kms() -> Dict[str, Any]:
    """Test Google Cloud KMS for PII encryption"""
    try:
        # Check environment variables
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        key_ring = os.getenv("KMS_KEY_RING")
        key_id = os.getenv("KMS_KEY_ID")
        location = os.getenv("KMS_LOCATION")
        credentials = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        
        if not all([project, key_ring, key_id, location]):
            return {
                "status": "not_configured",
                "message": "KMS environment variables missing",
                "project": project,
                "key_ring": key_ring,
                "key_name": key_id,
                "location": location,
                "credentials_file": credentials
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


async def check_secret_manager() -> Dict[str, Any]:
    """Test Google Secret Manager"""
    try:
        use_sm = os.getenv("USE_SECRET_MANAGER", "").lower() == "true"
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        
        if not use_sm:
            return {
                "status": "disabled",
                "message": "Secret Manager disabled (USE_SECRET_MANAGER not set)",
                "project": project
            }
        
        if not project:
            return {
                "status": "not_configured",
                "message": "GOOGLE_CLOUD_PROJECT not set",
                "project": None
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


async def check_vertex_ai() -> Dict[str, Any]:
    """Test Vertex AI (Gemini)"""
    try:
        project = os.getenv("GOOGLE_VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
        location = os.getenv("GOOGLE_VERTEX_LOCATION", "us-central1")
        
        if not project:
            return {
                "status": "not_configured",
                "message": "Vertex AI not configured (GOOGLE_VERTEX_PROJECT or GOOGLE_CLOUD_PROJECT required)",
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
        "google_kms": await check_google_kms(),
        "google_secret_manager": await check_secret_manager(),
        "vertex_ai": await check_vertex_ai(),
        "translation_api": await check_translation_api(db)
    }
    
    # Calculate overall health
    statuses = [v["status"] for v in results.values()]
    
    if all(s in ["healthy", "configured", "disabled"] for s in statuses):
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
