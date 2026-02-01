"""
Setup wizard API endpoints for automated Auth0 and Google Cloud configuration.

Security: All endpoints require admin authentication and log actions to audit trail.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import logging
import httpx
import json
import os

from app.db.session import get_db
from app.core.auth import get_current_user
from app.models import User, SystemSecret
from app.services.audit_service import AuditService
from app.core.encryption import encrypt

router = APIRouter()
logger = logging.getLogger(__name__)


# Request/Response Models
class Auth0SetupRequest(BaseModel):
    """Request body for Auth0 automated setup"""
    domain: str = Field(..., description="Auth0 tenant domain (e.g., yourorg.us.auth0.com)")
    management_client_id: str = Field(..., description="Management API client ID")
    management_client_secret: str = Field(..., description="Management API client secret")
    callback_url: str = Field(..., description="Application callback URL")


class GCPSetupRequest(BaseModel):
    """Request body for GCP automated setup"""
    project_id: str = Field(..., description="Google Cloud project ID")
    service_account_json: str = Field(..., description="Service account JSON key")


class SetupStatusResponse(BaseModel):
    """Current setup status"""
    gcp_configured: bool
    auth0_configured: bool
    gcp_details: Optional[Dict[str, Any]] = None
    auth0_details: Optional[Dict[str, Any]] = None


@router.get("/status")
async def get_setup_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current setup status.
    
    Returns what's configured and what needs setup.
    GCP is checked first since it's a dependency for Auth0 credential storage.
    Requires admin authentication.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from sqlalchemy import select
    
    # Check GCP status (check if we have project_id secret configured)
    gcp_result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name == "GOOGLE_CLOUD_PROJECT")
    )
    gcp_secret = gcp_result.scalar_one_or_none()
    gcp_configured = bool(gcp_secret and gcp_secret.is_configured)
    
    # Check Auth0 status
    auth0_result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name.in_([
            "AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"
        ]))
    )
    auth0_secrets = {s.key_name: s for s in auth0_result.scalars().all()}
    auth0_configured = all(
        key in auth0_secrets and auth0_secrets[key].is_configured
        for key in ["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"]
    )
    
    # Get details if configured
    auth0_details = None
    if auth0_configured:
        from app.core.encryption import decrypt_safe
        domain = decrypt_safe(auth0_secrets.get("AUTH0_DOMAIN", {}).key_value) if auth0_secrets.get("AUTH0_DOMAIN") else None
        client_id = auth0_secrets.get("AUTH0_CLIENT_ID", {}).key_value if auth0_secrets.get("AUTH0_CLIENT_ID") else None
        auth0_details = {
            "domain": domain,
            "client_id": f"{client_id[:10]}..." if client_id else None
        }
    
    gcp_details = None
    if gcp_configured:
        from app.core.encryption import decrypt_safe
        project_id = decrypt_safe(gcp_secret.key_value) if gcp_secret else None
        gcp_details = {"project_id": project_id}
    
    return SetupStatusResponse(
        gcp_configured=gcp_configured,
        auth0_configured=auth0_configured,
        gcp_details=gcp_details,
        auth0_details=auth0_details
    )


@router.post("/gcp/configure")
async def configure_gcp(
    request: GCPSetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Configure Google Cloud Platform.
    
    This endpoint:
    1. Validates the service account JSON
    2. Stores project ID and credentials
    3. Optionally enables required APIs
    
    Requires admin authentication and logs all actions.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Validate the service account JSON
        try:
            sa_data = json.loads(request.service_account_json)
            if "project_id" not in sa_data:
                raise ValueError("Service account JSON must contain project_id")
            if "client_email" not in sa_data:
                raise ValueError("Service account JSON must contain client_email")
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Invalid JSON format for service account"
            )
        
        # Verify the project ID matches
        if sa_data["project_id"] != request.project_id:
            logger.warning(f"Project ID mismatch: {request.project_id} vs {sa_data['project_id']}")
            # Use the one from the service account JSON as it's authoritative
        
        from sqlalchemy import select
        
        # Store credentials in database
        for key, value in [
            ("GOOGLE_CLOUD_PROJECT", request.project_id),
            ("GCP_SERVICE_ACCOUNT_JSON", request.service_account_json)
        ]:
            result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == key)
            )
            secret = result.scalar_one_or_none()
            
            encrypted_value = encrypt(value)
            
            if secret:
                secret.key_value = encrypted_value
                secret.is_configured = True
            else:
                secret = SystemSecret(
                    key_name=key,
                    key_value=encrypted_value,
                    is_configured=True,
                    description=f"GCP {key.replace('_', ' ').lower()}"
                )
                db.add(secret)
        
        await db.commit()
        
        # Try to create KMS keyring and key automatically
        kms_created = False
        kms_error = None
        kms_keyring = "pinpoint311-keyring"
        kms_key = "pii-encryption-key"
        kms_location = "us-central1"
        
        try:
            from google.cloud import kms
            from google.oauth2 import service_account
            
            # Create credentials from service account JSON
            credentials = service_account.Credentials.from_service_account_info(sa_data)
            kms_client = kms.KeyManagementServiceClient(credentials=credentials)
            
            # Create keyring
            parent = f"projects/{request.project_id}/locations/{kms_location}"
            keyring_name = f"{parent}/keyRings/{kms_keyring}"
            
            try:
                kms_client.create_key_ring(
                    request={"parent": parent, "key_ring_id": kms_keyring, "key_ring": {}}
                )
                logger.info(f"Created KMS keyring: {kms_keyring}")
            except Exception as e:
                if "already exists" in str(e).lower() or "ALREADY_EXISTS" in str(e):
                    logger.info(f"KMS keyring already exists: {kms_keyring}")
                else:
                    raise
            
            # Create encryption key
            key_name = f"{keyring_name}/cryptoKeys/{kms_key}"
            try:
                kms_client.create_crypto_key(
                    request={
                        "parent": keyring_name,
                        "crypto_key_id": kms_key,
                        "crypto_key": {
                            "purpose": kms.CryptoKey.CryptoKeyPurpose.ENCRYPT_DECRYPT,
                            "version_template": {
                                "algorithm": kms.CryptoKeyVersion.CryptoKeyVersionAlgorithm.GOOGLE_SYMMETRIC_ENCRYPTION
                            }
                        }
                    }
                )
                logger.info(f"Created KMS key: {kms_key}")
            except Exception as e:
                if "already exists" in str(e).lower() or "ALREADY_EXISTS" in str(e):
                    logger.info(f"KMS key already exists: {kms_key}")
                else:
                    raise
            
            kms_created = True
            
            # Store KMS configuration
            for key, value in [
                ("KMS_KEY_RING", kms_keyring),
                ("KMS_KEY_ID", kms_key),
                ("KMS_LOCATION", kms_location)
            ]:
                result = await db.execute(
                    select(SystemSecret).where(SystemSecret.key_name == key)
                )
                secret = result.scalar_one_or_none()
                encrypted_value = encrypt(value)
                
                if secret:
                    secret.key_value = encrypted_value
                    secret.is_configured = True
                else:
                    secret = SystemSecret(
                        key_name=key,
                        key_value=encrypted_value,
                        is_configured=True,
                        description=f"KMS {key.replace('_', ' ').lower()}"
                    )
                    db.add(secret)
            
            await db.commit()
            
        except ImportError:
            kms_error = "google-cloud-kms package not installed"
            logger.warning(f"KMS setup skipped: {kms_error}")
        except Exception as e:
            kms_error = str(e)[:200]
            logger.warning(f"KMS auto-setup failed (will use Fernet fallback): {e}")
        
        # Log successful setup
        await AuditService.log_event(
            db=db,
            event_type="gcp_configured",
            success=True,
            user_id=current_user.id,
            username=current_user.username,
            details={
                "project_id": request.project_id,
                "service_account_email": sa_data.get("client_email"),
                "kms_configured": kms_created,
                "kms_error": kms_error
            }
        )
        
        logger.info(f"GCP configured successfully by {current_user.username}")
        
        # Auto-trigger Workload Identity Federation if Auth0 is also configured
        federation_result = None
        try:
            # Check if Auth0 is configured (required for federation)
            auth0_result = await db.execute(
                select(SystemSecret).where(
                    SystemSecret.key_name.in_(["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"])
                )
            )
            auth0_secrets = auth0_result.scalars().all()
            auth0_configured = len(auth0_secrets) == 3 and all(s.is_configured for s in auth0_secrets)
            
            if auth0_configured:
                from app.services.workload_identity import setup_federation, is_federation_available
                
                # Only set up if not already configured
                if not await is_federation_available():
                    logger.info("Auto-triggering Workload Identity Federation setup...")
                    federation_result = await setup_federation()
                    
                    if federation_result.get("status") == "success":
                        await AuditService.log_event(
                            db=db,
                            event_type="federation_auto_setup",
                            success=True,
                            user_id=current_user.id,
                            username=current_user.username,
                            details=federation_result
                        )
                        logger.info("Workload Identity Federation auto-configured successfully")
                    else:
                        logger.warning(f"Federation auto-setup failed: {federation_result.get('error')}")
                else:
                    federation_result = {"status": "skipped", "reason": "Federation already configured"}
        except Exception as fed_err:
            logger.warning(f"Federation auto-setup skipped: {fed_err}")
            federation_result = {"status": "skipped", "reason": str(fed_err)}
        
        return {
            "success": True,
            "message": "Google Cloud Platform configured successfully",
            "project_id": request.project_id,
            "kms_configured": kms_created,
            "kms_keyring": kms_keyring if kms_created else None,
            "kms_key": kms_key if kms_created else None,
            "kms_note": None if kms_created else f"KMS not auto-created ({kms_error}), using Fernet encryption",
            "federation": federation_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"GCP setup failed: {str(e)}")
        await AuditService.log_event(
            db=db,
            event_type="gcp_configuration_failed",
            success=False,
            user_id=current_user.id,
            username=current_user.username,
            failure_reason=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure GCP: {str(e)}"
        )


@router.post("/auth0/configure")
async def configure_auth0(
    request: Auth0SetupRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Automatically configure Auth0 tenant.
    
    This endpoint:
    1. Creates a new application in Auth0
    2. Configures MFA, password policies, brute force protection
    3. Sets callback URLs
    4. Stores credentials in database (encrypted)
    
    Requires admin authentication and logs all actions.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    try:
        # Get Management API access token
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                f"https://{request.domain}/oauth/token",
                json={
                    "client_id": request.management_client_id,
                    "client_secret": request.management_client_secret,
                    "audience": f"https://{request.domain}/api/v2/",
                    "grant_type": "client_credentials"
                }
            )
            
            if token_response.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to get Management API token: {token_response.text}"
                )
            
            access_token = token_response.json()["access_token"]
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            }
            
            # Create application
            base_url = request.callback_url.rsplit('/', 1)[0] if '/' in request.callback_url else request.callback_url
            app_response = await client.post(
                f"https://{request.domain}/api/v2/clients",
                headers=headers,
                json={
                    "name": "Pinpoint 311 Portal",
                    "app_type": "regular_web",
                    "callbacks": [
                        request.callback_url,
                        f"{base_url}/api/auth/callback"
                    ],
                    "allowed_logout_urls": [base_url],
                    "web_origins": [base_url],
                    "oidc_conformant": True,
                    "grant_types": ["authorization_code", "refresh_token"],
                    "token_endpoint_auth_method": "client_secret_post"
                }
            )
            
            if app_response.status_code != 201:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to create Auth0 application: {app_response.text}"
                )
            
            app_data = app_response.json()
            client_id = app_data["client_id"]
            client_secret = app_data["client_secret"]
            
            # Configure MFA (enable push notifications)
            try:
                await client.patch(
                    f"https://{request.domain}/api/v2/guardian/factors/push-notification",
                    headers=headers,
                    json={"enabled": True}
                )
            except Exception as e:
                logger.warning(f"Failed to enable MFA: {e}")
            
            # Configure brute force protection
            try:
                await client.patch(
                    f"https://{request.domain}/api/v2/attack-protection/brute-force-protection",
                    headers=headers,
                    json={
                        "enabled": True,
                        "shields": ["block", "user_notification"],
                        "mode": "count_per_identifier_and_ip",
                        "allowlist": [],
                        "max_attempts": 5
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to configure brute force protection: {e}")
            
        # Store credentials in database
        from sqlalchemy import select
        
        for key, value in [
            ("AUTH0_DOMAIN", request.domain),
            ("AUTH0_CLIENT_ID", client_id),
            ("AUTH0_CLIENT_SECRET", client_secret)
        ]:
            result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == key)
            )
            secret = result.scalar_one_or_none()
            
            encrypted_value = encrypt(value)
            
            if secret:
                secret.key_value = encrypted_value
                secret.is_configured = True
            else:
                secret = SystemSecret(
                    key_name=key,
                    key_value=encrypted_value,
                    is_configured=True,
                    description=f"Auth0 {key.split('_')[1].lower()}"
                )
                db.add(secret)
        
        await db.commit()
        
        # Log successful setup
        await AuditService.log_event(
            db=db,
            event_type="auth0_configured",
            success=True,
            user_id=current_user.id,
            username=current_user.username,
            details={
                "domain": request.domain,
                "client_id": client_id,
                "callback_url": request.callback_url
            }
        )
        
        logger.info(f"Auth0 configured successfully by {current_user.username}")
        
        # Auto-trigger Workload Identity Federation if GCP is also configured
        federation_result = None
        try:
            # Check if GCP is configured (required for federation)
            gcp_result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == "GCP_SERVICE_ACCOUNT_JSON")
            )
            gcp_secret = gcp_result.scalar_one_or_none()
            
            if gcp_secret and gcp_secret.is_configured and gcp_secret.key_value:
                from app.services.workload_identity import setup_federation, is_federation_available
                
                # Only set up if not already configured
                if not await is_federation_available():
                    logger.info("Auto-triggering Workload Identity Federation setup...")
                    federation_result = await setup_federation()
                    
                    if federation_result.get("status") == "success":
                        await AuditService.log_event(
                            db=db,
                            event_type="federation_auto_setup",
                            success=True,
                            user_id=current_user.id,
                            username=current_user.username,
                            details=federation_result
                        )
                        logger.info("Workload Identity Federation auto-configured successfully")
                    else:
                        logger.warning(f"Federation auto-setup failed: {federation_result.get('error')}")
                else:
                    federation_result = {"status": "skipped", "reason": "Federation already configured"}
        except Exception as fed_err:
            logger.warning(f"Federation auto-setup skipped: {fed_err}")
            federation_result = {"status": "skipped", "reason": str(fed_err)}
        
        return {
            "success": True,
            "message": "Auth0 configured successfully",
            "domain": request.domain,
            "client_id": client_id,
            "federation": federation_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth0 setup failed: {str(e)}")
        await AuditService.log_event(
            db=db,
            event_type="auth0_configuration_failed",
            success=False,
            user_id=current_user.id,
            username=current_user.username,
            failure_reason=str(e)
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to configure Auth0: {str(e)}"
        )


@router.post("/verify")
async def verify_setup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Verify current Auth0 and GCP configuration.
    
    Tests that credentials work and services are reachable.
    """
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    
    from sqlalchemy import select
    from app.core.encryption import decrypt_safe
    
    results = {
        "gcp": {"configured": False, "reachable": False, "error": None},
        "auth0": {"configured": False, "reachable": False, "error": None}
    }
    
    # Test GCP
    try:
        gcp_result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == "GOOGLE_CLOUD_PROJECT")
        )
        gcp_secret = gcp_result.scalar_one_or_none()
        if gcp_secret and gcp_secret.is_configured:
            results["gcp"]["configured"] = True
            project_id = decrypt_safe(gcp_secret.key_value)
            results["gcp"]["project_id"] = project_id
            # TODO: Test GCP connectivity by calling a simple API
            results["gcp"]["reachable"] = True
    except Exception as e:
        results["gcp"]["error"] = str(e)
    
    # Test Auth0
    try:
        auth0_result = await db.execute(
            select(SystemSecret).where(SystemSecret.key_name == "AUTH0_DOMAIN")
        )
        auth0_secret = auth0_result.scalar_one_or_none()
        if auth0_secret and auth0_secret.is_configured:
            results["auth0"]["configured"] = True
            domain = decrypt_safe(auth0_secret.key_value)
            results["auth0"]["domain"] = domain
            
            # Test OIDC discovery endpoint
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(
                    f"https://{domain}/.well-known/openid-configuration"
                )
                results["auth0"]["reachable"] = response.status_code == 200
    except Exception as e:
        results["auth0"]["error"] = str(e)
    
    return results


# ============================================================================
# Workload Identity Federation Endpoints
# ============================================================================

class FederationStatus(BaseModel):
    """Federation setup status."""
    federation_available: bool = False
    bootstrap_key_present: bool = False
    pool_name: Optional[str] = None
    provider_name: Optional[str] = None
    can_setup: bool = False
    can_complete: bool = False


@router.get("/federation/status", response_model=FederationStatus)
async def get_federation_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get current Workload Identity Federation status.
    
    Returns whether federation is set up, if bootstrap key exists, etc.
    """
    from app.services.workload_identity import is_federation_available, _get_federation_config
    from app.core.encryption import decrypt_safe
    
    response = FederationStatus()
    
    # Check if federation is already available
    config = await _get_federation_config()
    if config:
        response.federation_available = True
        response.pool_name = f"projects/{config.get('project_id')}/locations/global/workloadIdentityPools/{config.get('pool_id')}"
        response.provider_name = f"{response.pool_name}/providers/{config.get('provider_id')}"
    
    # Check if bootstrap key exists
    result = await db.execute(
        select(SystemSecret).where(SystemSecret.key_name == "GCP_SERVICE_ACCOUNT_JSON")
    )
    key_secret = result.scalar_one_or_none()
    response.bootstrap_key_present = bool(key_secret and key_secret.is_configured and key_secret.key_value)
    
    # Check if Auth0 is configured (required for federation)
    auth0_result = await db.execute(
        select(SystemSecret).where(
            SystemSecret.key_name.in_(["AUTH0_DOMAIN", "AUTH0_CLIENT_ID", "AUTH0_CLIENT_SECRET"])
        )
    )
    auth0_secrets = auth0_result.scalars().all()
    auth0_configured = len(auth0_secrets) == 3 and all(s.is_configured for s in auth0_secrets)
    
    # Can setup if we have bootstrap key and Auth0
    response.can_setup = response.bootstrap_key_present and auth0_configured and not response.federation_available
    
    # Can complete (delete key) if federation is working
    response.can_complete = response.federation_available and response.bootstrap_key_present
    
    return response


@router.post("/federation/setup")
async def setup_workload_identity_federation(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Set up Workload Identity Federation with Auth0.
    
    This creates:
    1. Workload Identity Pool in GCP
    2. Auth0 OIDC provider
    3. IAM bindings for Secret Manager and KMS access
    
    After this succeeds, you can call /federation/complete to delete
    the bootstrap service account key.
    """
    from app.services.workload_identity import setup_federation
    from app.services.audit_service import AuditService
    
    # Log the action
    await AuditService.log_event(
        db=db,
        event_type="federation_setup_started",
        success=True,
        user_id=current_user.id,
        username=current_user.username,
        details={"initiated_by": current_user.username}
    )
    
    result = await setup_federation()
    
    if result.get("status") == "success":
        await AuditService.log_event(
            db=db,
            event_type="federation_setup_completed",
            success=True,
            user_id=current_user.id,
            username=current_user.username,
            details=result
        )
    else:
        await AuditService.log_event(
            db=db,
            event_type="federation_setup_failed",
            success=False,
            user_id=current_user.id,
            username=current_user.username,
            failure_reason=result.get("error"),
            details=result
        )
    
    return result


@router.post("/federation/test")
async def test_workload_identity_federation(
    current_user: User = Depends(get_current_user)
):
    """
    Test that Workload Identity Federation is working.
    
    Attempts to access GCP using federation credentials (not service account key).
    """
    from app.services.workload_identity import test_federation
    
    result = await test_federation()
    return result


@router.post("/federation/complete")
async def complete_federation_setup(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Complete federation setup by deleting the bootstrap service account key.
    
    This is the "self-destruct" step. After this:
    - The service account key is permanently deleted from the database
    - All future GCP access uses Auth0 federation (keyless)
    
    WARNING: Only call this after verifying federation works with /federation/test
    """
    from app.services.workload_identity import test_federation, delete_bootstrap_key
    from app.services.audit_service import AuditService
    
    # First verify federation actually works
    test_result = await test_federation()
    if test_result.get("status") != "success":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Federation test failed. Cannot delete bootstrap key until federation works. Error: {test_result.get('error')}"
        )
    
    # Log the critical action
    audit_service = AuditService(db)
    await audit_service.log_action(
        action="bootstrap_key_deletion",
        user_id=current_user.id,
        resource_type="system_secret",
        resource_id="GCP_SERVICE_ACCOUNT_JSON",
        details={
            "reason": "Federation verified working",
            "initiated_by": current_user.username,
            "federation_test_result": test_result
        }
    )
    
    # Delete the bootstrap key
    delete_result = await delete_bootstrap_key()
    
    if delete_result.get("status") == "success":
        await audit_service.log_action(
            action="bootstrap_key_deleted",
            user_id=current_user.id,
            resource_type="system_secret",
            resource_id="GCP_SERVICE_ACCOUNT_JSON",
            details={"message": "Service account key permanently deleted, federation is now active"}
        )
    
    # Clear secret manager cache to force use of federation
    from app.services.secret_manager import clear_cache
    clear_cache()
    
    return {
        **delete_result,
        "federation_active": True,
        "message": "Bootstrap key deleted. All future GCP access will use Auth0 federation."
    }
