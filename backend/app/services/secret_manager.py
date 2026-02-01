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
    """Get Secret Manager client with database credentials."""
    global _sm_client
    
    if _sm_client:
        return _sm_client
    
    try:
        from google.cloud import secretmanager
        from google.oauth2 import service_account
        import json as json_lib
        
        # Try to load service account from database (Setup Wizard storage)
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
                    logger.info("Secret Manager client initialized with database credentials")
                    return _sm_client
        except Exception as db_err:
            logger.debug(f"Could not load SM credentials from database: {db_err}")
        
        # Fall back to default credentials
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
        if key_name.startswith("ZITADEL_"):
            bundle = _get_secret_from_gcp("secret-zitadel")
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
        if prefix.startswith("ZITADEL"):
            bundle = _get_secret_from_gcp("secret-zitadel")
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
