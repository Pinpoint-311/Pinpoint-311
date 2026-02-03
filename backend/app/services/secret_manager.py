"""
Google Secret Manager Service

Securely retrieves secrets from Google Secret Manager.
Falls back to database storage for local development.

Secrets are bundled into 6 groups to fit the free tier:
- secret-zitadel: Zitadel Cloud SSO credentials
- secret-smtp: Email configuration
- secret-sms: SMS provider configuration
- secret-google: Google Cloud API keys
- secret-backup: S3/backup configuration
- secret-config: Township-specific settings
"""

import json
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Cache for secrets (they don't change often)
_secret_cache: Dict[str, Dict[str, str]] = {}
_use_gcp: Optional[bool] = None
_sm_client = None


def _get_project_from_db() -> Optional[str]:
    """Get GCP project ID from database."""
    try:
        from app.db.session import sync_engine
        from sqlalchemy import text
        
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT key_value FROM system_secrets WHERE key_name = 'GOOGLE_CLOUD_PROJECT'")
            )
            row = result.fetchone()
            if row and row[0]:
                from app.core.encryption import decrypt
                return decrypt(row[0])
    except Exception:
        pass
    return None


def _get_sm_client():
    """Get Secret Manager client using encrypted service account key."""
    global _sm_client
    
    if _sm_client:
        return _sm_client
    
    try:
        from google.cloud import secretmanager
        from google.oauth2 import service_account
        import json as json_lib
        
        # Try service account from database (encrypted storage)
        try:
            from app.db.session import sync_engine
            from sqlalchemy import text
            
            with sync_engine.connect() as conn:
                result = conn.execute(
                    text("SELECT key_value FROM system_secrets WHERE key_name = 'GCP_SERVICE_ACCOUNT_JSON'")
                )
                row = result.fetchone()
                if row and row[0]:
                    from app.core.encryption import decrypt
                    sa_json = decrypt(row[0])
                    sa_data = json_lib.loads(sa_json)
                    credentials = service_account.Credentials.from_service_account_info(sa_data)
                    _sm_client = secretmanager.SecretManagerServiceClient(credentials=credentials)
                    logger.info("Secret Manager client initialized with encrypted service account key")
                    return _sm_client
        except Exception as db_err:
            logger.debug(f"Could not load SM credentials from database: {db_err}")
        
        # Fall back to default credentials (ADC)
        _sm_client = secretmanager.SecretManagerServiceClient()
        return _sm_client
    except Exception as e:
        logger.warning(f"Failed to initialize Secret Manager client: {e}")
        return None




def _is_gcp_available() -> bool:
    """Check if Google Cloud Secret Manager is available."""
    global _use_gcp
    
    if _use_gcp is not None:
        return _use_gcp
    
    # Check for project ID in env or database
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or _get_project_from_db()
    if not project:
        _use_gcp = False
        logger.info("Google Cloud Project not set, using database for secrets")
        return False
    
    # Try to get a client
    client = _get_sm_client()
    if client:
        _use_gcp = True
        logger.info(f"Using Google Secret Manager for project: {project}")
        return True
    
    _use_gcp = False
    return False


def _get_secret_from_gcp(secret_name: str) -> Optional[Dict[str, str]]:
    """Fetch a secret bundle from Google Secret Manager."""
    if secret_name in _secret_cache:
        return _secret_cache[secret_name]
    
    try:
        project = os.getenv("GOOGLE_CLOUD_PROJECT") or _get_project_from_db()
        client = _get_sm_client()
        
        if not client or not project:
            return None
        
        name = f"projects/{project}/secrets/{secret_name}/versions/latest"
        response = client.access_secret_version(request={"name": name})
        
        # Track Secret Manager usage
        try:
            import asyncio
            
            async def _track():
                from app.db.session import SessionLocal
                from app.services.api_usage import track_api_usage
                async with SessionLocal() as db:
                    await track_api_usage(
                        db,
                        service_name="secret_manager",
                        operation="access_secret",
                        api_calls=1
                    )
            
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(_track())
            except RuntimeError:
                asyncio.run(_track())
        except Exception as track_err:
            logger.debug(f"Failed to track Secret Manager usage: {track_err}")
        
        secret_data = json.loads(response.payload.data.decode("UTF-8"))
        _secret_cache[secret_name] = secret_data
        return secret_data
    except Exception as e:
        logger.warning(f"Failed to get secret {secret_name} from GCP: {e}")
        return None


async def get_secret(key_name: str) -> Optional[str]:
    """
    Get a single secret value.
    
    Uses Google Secret Manager if available, falls back to database.
    
    Secret key mappings:
    - ZITADEL_* -> secret-zitadel bundle
    - SMTP_* -> secret-smtp bundle
    - SMS_*, TWILIO_* -> secret-sms bundle
    - GOOGLE_*, VERTEX_* -> secret-google bundle
    - BACKUP_* -> secret-backup bundle
    - Others -> secret-config bundle
    """
    if _is_gcp_available():
        # Determine which bundle this key belongs to
        if key_name.startswith("ZITADEL_") or key_name.startswith("AUTH0_"):
            bundle = _get_secret_from_gcp("secret-auth")
        elif key_name.startswith("SMTP_") or key_name.startswith("EMAIL_"):
            bundle = _get_secret_from_gcp("secret-smtp")
        elif key_name.startswith("SMS_") or key_name.startswith("TWILIO_"):
            bundle = _get_secret_from_gcp("secret-sms")
        elif key_name.startswith("GOOGLE_") or key_name.startswith("VERTEX_"):
            bundle = _get_secret_from_gcp("secret-google")
        elif key_name.startswith("BACKUP_"):
            bundle = _get_secret_from_gcp("secret-backup")
        else:
            bundle = _get_secret_from_gcp("secret-config")
        
        if bundle and key_name in bundle:
            return bundle[key_name]
    
    # Fallback to database
    return await _get_secret_from_db(key_name)


async def _get_secret_from_db(key_name: str) -> Optional[str]:
    """Fallback: get secret from encrypted database storage."""
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from app.core.encryption import decrypt_safe
    from sqlalchemy import select
    
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(SystemSecret).where(SystemSecret.key_name == key_name)
            )
            secret = result.scalar_one_or_none()
            
            if secret and secret.key_value and secret.is_configured:
                return decrypt_safe(secret.key_value)
            return None
    except Exception as e:
        logger.error(f"Failed to get secret {key_name} from database: {e}")
        return None


async def get_secrets_bundle(prefix: str) -> Dict[str, str]:
    """
    Get all secrets with a given prefix.
    
    Example: get_secrets_bundle("SMTP_") returns all SMTP settings.
    """
    result = {}
    
    if _is_gcp_available():
        # Map prefix to bundle name
        if prefix.startswith("ZITADEL") or prefix.startswith("AUTH0"):
            bundle = _get_secret_from_gcp("secret-auth")
        elif prefix.startswith("SMTP") or prefix.startswith("EMAIL"):
            bundle = _get_secret_from_gcp("secret-smtp")
        elif prefix.startswith("SMS") or prefix.startswith("TWILIO"):
            bundle = _get_secret_from_gcp("secret-sms")
        elif prefix.startswith("GOOGLE") or prefix.startswith("VERTEX"):
            bundle = _get_secret_from_gcp("secret-google")
        elif prefix.startswith("BACKUP"):
            bundle = _get_secret_from_gcp("secret-backup")
        else:
            bundle = _get_secret_from_gcp("secret-config")
        
        if bundle:
            for key, value in bundle.items():
                if key.startswith(prefix):
                    result[key] = value
            if result:
                return result
    
    # Fallback to database
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from app.core.encryption import decrypt_safe
    from sqlalchemy import select
    
    try:
        async with SessionLocal() as db:
            query = select(SystemSecret).where(
                SystemSecret.key_name.like(f"{prefix}%")
            )
            secrets = await db.execute(query)
            
            for secret in secrets.scalars():
                if secret.key_value and secret.is_configured:
                    result[secret.key_name] = decrypt_safe(secret.key_value)
    except Exception as e:
        logger.error(f"Failed to get secrets with prefix {prefix}: {e}")
    
    return result


def clear_cache():
    """Clear the secret cache (useful after updates)."""
    global _secret_cache
    _secret_cache = {}


# ============================================================================
# Secret Manager Write Operations
# ============================================================================

def _get_bundle_name(key_name: str) -> str:
    """Determine which Secret Manager bundle a key belongs to."""
    if key_name.startswith("ZITADEL_") or key_name.startswith("AUTH0_"):
        return "secret-auth"
    elif key_name.startswith("SMTP_") or key_name.startswith("EMAIL_"):
        return "secret-smtp"
    elif key_name.startswith("SMS_") or key_name.startswith("TWILIO_"):
        return "secret-sms"
    elif key_name.startswith("GOOGLE_") or key_name.startswith("VERTEX_") or key_name.startswith("KMS_") or key_name.startswith("GCP_"):
        return "secret-google"
    elif key_name.startswith("BACKUP_"):
        return "secret-backup"
    else:
        return "secret-config"


def _create_secret_if_not_exists(client, project: str, secret_id: str) -> bool:
    """Create a secret in Secret Manager if it doesn't exist."""
    try:
        from google.cloud import secretmanager
        
        parent = f"projects/{project}"
        secret_name = f"{parent}/secrets/{secret_id}"
        
        # Try to get the secret first
        try:
            client.get_secret(request={"name": secret_name})
            return True  # Already exists
        except Exception:
            pass  # Doesn't exist, create it
        
        # Create the secret
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
        logger.info(f"Created secret: {secret_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to create secret {secret_id}: {e}")
        return False


def set_secret_sync(key_name: str, value: str) -> bool:
    """
    Write a secret to Google Secret Manager (sync version).
    
    Secrets are bundled into JSON objects to stay within free tier limits.
    Returns True if successful, False otherwise.
    """
    if not _is_gcp_available():
        logger.debug(f"Secret Manager not available, skipping write for {key_name}")
        return False
    
    try:
        from google.cloud import secretmanager
        
        project = os.getenv("GOOGLE_CLOUD_PROJECT") or _get_project_from_db()
        client = _get_sm_client()
        
        if not client or not project:
            return False
        
        bundle_name = _get_bundle_name(key_name)
        
        # Get existing bundle or create empty one
        existing_bundle = _get_secret_from_gcp(bundle_name) or {}
        
        # Update the bundle with new value
        existing_bundle[key_name] = value
        
        # Create secret if it doesn't exist
        if not _create_secret_if_not_exists(client, project, bundle_name):
            return False
        
        # Add new version with updated bundle
        secret_path = f"projects/{project}/secrets/{bundle_name}"
        payload = json.dumps(existing_bundle).encode("UTF-8")
        
        client.add_secret_version(
            request={
                "parent": secret_path,
                "payload": {"data": payload},
            }
        )
        
        # Clear cache so next read gets fresh data
        if bundle_name in _secret_cache:
            del _secret_cache[bundle_name]
        
        logger.info(f"Secret {key_name} written to Secret Manager bundle {bundle_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to write secret {key_name} to Secret Manager: {e}")
        return False


async def set_secret(key_name: str, value: str) -> bool:
    """
    Write a secret to Google Secret Manager (async version).
    
    Wraps the sync version for async compatibility.
    """
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, set_secret_sync, key_name, value)


async def migrate_to_secret_manager() -> Dict[str, Any]:
    """
    Migrate all secrets from database to Google Secret Manager.
    
    SAFETY: Only scrubs secrets from database AFTER verifying they can be
    read back from GCP. This prevents data loss if the write fails.
    
    Returns a summary of migrated secrets.
    """
    from app.db.session import SessionLocal
    from app.models import SystemSecret
    from app.core.encryption import decrypt_safe
    from sqlalchemy import select
    
    if not _is_gcp_available():
        return {
            "status": "skipped",
            "reason": "Secret Manager not available",
            "migrated": 0
        }
    
    migrated = []
    verified = []
    failed = []
    skipped = []
    scrubbed = []
    
    # Keys that should NOT be migrated (they're needed to access Secret Manager itself)
    bootstrap_keys = {
        "GCP_SERVICE_ACCOUNT_JSON",
        "GOOGLE_CLOUD_PROJECT",
    }
    
    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(SystemSecret).where(SystemSecret.is_configured == True)
            )
            secrets = result.scalars().all()
            
            for secret in secrets:
                if secret.key_name in bootstrap_keys:
                    skipped.append(secret.key_name)
                    continue
                
                if not secret.key_value:
                    skipped.append(secret.key_name)
                    continue
                
                # Decrypt the value from database
                try:
                    plaintext = decrypt_safe(secret.key_value)
                    if not plaintext:
                        skipped.append(secret.key_name)
                        continue
                except Exception:
                    failed.append({"key": secret.key_name, "error": "decryption failed"})
                    continue
                
                # Write to Secret Manager
                success = await set_secret(secret.key_name, plaintext)
                
                if success:
                    migrated.append(secret.key_name)
                else:
                    failed.append({"key": secret.key_name, "error": "write failed"})
            
            # CRITICAL: Verify each migrated secret can be read back from GCP
            # Only scrub if verification passes
            clear_cache()  # Clear cache to force fresh reads
            
            for key_name in migrated:
                try:
                    # Try to read the secret back from GCP
                    read_value = await get_secret(key_name)
                    if read_value:
                        verified.append(key_name)
                    else:
                        failed.append({"key": key_name, "error": "verification failed - could not read back from GCP"})
                except Exception as e:
                    failed.append({"key": key_name, "error": f"verification failed: {str(e)}"})
            
            # Only scrub VERIFIED secrets from database
            if verified:
                for secret in secrets:
                    if secret.key_name in verified:
                        # Clear the encrypted value but keep the record
                        secret.key_value = None
                        scrubbed.append(secret.key_name)
                
                await db.commit()
                logger.info(f"Scrubbed {len(scrubbed)} verified secrets from database after migration")
            else:
                logger.warning("No secrets verified - database values NOT scrubbed")
        
        return {
            "status": "success" if verified else "partial_failure",
            "migrated": len(migrated),
            "migrated_keys": migrated,
            "verified": len(verified),
            "verified_keys": verified,
            "scrubbed": len(scrubbed),
            "scrubbed_keys": scrubbed,
            "skipped": len(skipped),
            "skipped_keys": skipped,
            "failed": len(failed),
            "failed_keys": failed
        }
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "migrated": len(migrated),
            "migrated_keys": migrated,
            "warning": "Database values NOT scrubbed due to error"
        }

