"""
Encryption utilities for protecting sensitive data at rest.

Uses Fernet symmetric encryption (AES-128-CBC with HMAC) derived from 
the application's SECRET_KEY environment variable.

For PII data (resident email, phone, name), uses Google Cloud KMS
for HSM-backed encryption with full audit logging.

Government compliance: Secrets are encrypted before storage and 
decrypted only when needed by authorized services.
"""

import base64
import hashlib
import logging
import os
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from functools import lru_cache

logger = logging.getLogger(__name__)

# Prefix used to identify encrypted values
ENCRYPTED_PREFIX = "gAAAA"  # Fernet tokens always start with this
KMS_ENCRYPTED_PREFIX = "kms:"  # Google KMS encrypted values


def _derive_key(secret_key: str) -> bytes:
    """
    Derive a Fernet-compatible key from the application's SECRET_KEY.
    
    Uses SHA-256 to hash the secret key, then base64 encodes it to create
    a valid 32-byte Fernet key.
    
    Args:
        secret_key: The application's SECRET_KEY from environment
        
    Returns:
        A base64-encoded 32-byte key suitable for Fernet
    """
    # Hash the secret key to get consistent 32 bytes
    digest = hashlib.sha256(secret_key.encode()).digest()
    # Fernet requires url-safe base64 encoded 32-byte key
    return base64.urlsafe_b64encode(digest)


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """
    Get a cached Fernet instance using the application's SECRET_KEY.
    
    The instance is cached to avoid repeated key derivation.
    """
    from app.core.config import get_settings
    settings = get_settings()
    key = _derive_key(settings.secret_key)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """
    Encrypt a plaintext string.
    
    Args:
        plaintext: The string to encrypt
        
    Returns:
        Base64-encoded encrypted ciphertext
    """
    if not plaintext:
        return plaintext
    
    try:
        fernet = _get_fernet()
        encrypted = fernet.encrypt(plaintext.encode())
        return encrypted.decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise


def decrypt(ciphertext: str) -> str:
    """
    Decrypt an encrypted string.
    
    Args:
        ciphertext: The base64-encoded encrypted string
        
    Returns:
        The decrypted plaintext string
        
    Raises:
        InvalidToken: If decryption fails (wrong key or corrupted data)
    """
    if not ciphertext:
        return ciphertext
    
    try:
        fernet = _get_fernet()
        decrypted = fernet.decrypt(ciphertext.encode())
        return decrypted.decode()
    except InvalidToken:
        logger.warning("Decryption failed - may be legacy unencrypted value")
        raise
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        raise


def is_encrypted(value: Optional[str]) -> bool:
    """
    Check if a value appears to be encrypted (Fernet or KMS format).
    
    This is used during migration to handle both encrypted and 
    legacy unencrypted values.
    
    Args:
        value: The string to check
        
    Returns:
        True if the value appears to be encrypted
    """
    if not value:
        return False
    return value.startswith(ENCRYPTED_PREFIX) or value.startswith(KMS_ENCRYPTED_PREFIX)


def decrypt_safe(ciphertext: str) -> str:
    """
    Safely decrypt a value, returning the original if it's not encrypted.
    
    This handles the migration case where old unencrypted values 
    may still exist in the database.
    
    Args:
        ciphertext: The potentially encrypted string
        
    Returns:
        The decrypted string, or original if not encrypted
    """
    if not ciphertext:
        return ciphertext
    
    # Check if it's KMS encrypted
    if ciphertext.startswith(KMS_ENCRYPTED_PREFIX):
        return decrypt_pii(ciphertext)
    
    # Check if it looks like an encrypted value
    if not is_encrypted(ciphertext):
        # Return as-is (legacy unencrypted value)
        logger.debug("Value not encrypted, returning as-is")
        return ciphertext
    
    try:
        return decrypt(ciphertext)
    except InvalidToken:
        # If decryption fails even though it looks encrypted,
        # log a warning and return empty (security: don't expose corrupted data)
        logger.warning("Failed to decrypt value that appeared encrypted")
        return ""
    except Exception as e:
        logger.error(f"Unexpected decryption error: {e}")
        return ""


# ============================================================================
# Google Cloud KMS - For PII Data (Resident Info)
# ============================================================================

_kms_client = None
_kms_key_name = None


def _get_config_sync(key_name: str) -> Optional[str]:
    """Synchronously get a config value from env var or database."""
    # First check environment variable
    env_value = os.getenv(key_name)
    if env_value:
        return env_value
    
    # Try database
    try:
        from app.db.session import sync_engine
        from sqlalchemy import text
        
        with sync_engine.connect() as conn:
            result = conn.execute(
                text("SELECT key_value FROM system_secrets WHERE key_name = :key"),
                {"key": key_name}
            )
            row = result.fetchone()
            if row and row[0]:
                from app.core.encryption import decrypt
                return decrypt(row[0])
    except Exception:
        pass
    
    return None


def _is_kms_available() -> bool:
    """Check if Google Cloud KMS is available (from env or database)."""
    project = _get_config_sync("GOOGLE_CLOUD_PROJECT")
    return bool(project)


def _get_kms_key_name() -> Optional[str]:
    """Get the KMS key resource name from env vars or database."""
    global _kms_key_name
    
    if _kms_key_name:
        return _kms_key_name
    
    project = _get_config_sync("GOOGLE_CLOUD_PROJECT")
    if not project:
        return None
    
    # Key location and ring from env or database (Setup Wizard stores these)
    location = _get_config_sync("KMS_LOCATION") or "us-central1"
    key_ring = _get_config_sync("KMS_KEY_RING") or "pinpoint311-keyring"
    key_id = _get_config_sync("KMS_KEY_ID") or "pii-encryption-key"
    
    _kms_key_name = f"projects/{project}/locations/{location}/keyRings/{key_ring}/cryptoKeys/{key_id}"
    return _kms_key_name


def _get_kms_client():
    """Get a cached KMS client.
    
    Loads credentials from:
    1. Database (GCP_SERVICE_ACCOUNT_JSON stored by Setup Wizard)
    2. Falls back to default application credentials
    """
    global _kms_client
    
    if _kms_client:
        return _kms_client
    
    try:
        from google.cloud import kms
        from google.oauth2 import service_account
        import json
        
        # First try to load from database (Setup Wizard storage)
        try:
            from app.db.session import sync_engine
            from sqlalchemy import text
            
            with sync_engine.connect() as conn:
                result = conn.execute(
                    text("SELECT key_value FROM system_secrets WHERE key_name = 'GCP_SERVICE_ACCOUNT_JSON'")
                )
                row = result.fetchone()
                if row and row[0]:
                    # Decrypt the stored value
                    from app.core.encryption import decrypt
                    sa_json = decrypt(row[0])
                    sa_data = json.loads(sa_json)
                    credentials = service_account.Credentials.from_service_account_info(sa_data)
                    _kms_client = kms.KeyManagementServiceClient(credentials=credentials)
                    logger.info("KMS client initialized with database credentials")
                    return _kms_client
        except Exception as db_err:
            logger.debug(f"Could not load KMS credentials from database: {db_err}")
        
        # Fall back to default credentials (env GOOGLE_APPLICATION_CREDENTIALS)
        _kms_client = kms.KeyManagementServiceClient()
        return _kms_client
    except Exception as e:
        logger.warning(f"Failed to initialize KMS client: {e}")
        return None


def encrypt_pii(plaintext: str) -> str:
    """
    Encrypt PII data (resident email, phone, name) using Google Cloud KMS.
    
    Falls back to Fernet encryption if KMS is not available (local dev).
    
    Args:
        plaintext: The PII data to encrypt
        
    Returns:
        Encrypted string prefixed with "kms:" or Fernet encrypted
    """
    if not plaintext:
        return plaintext
    
    if not _is_kms_available():
        # Fallback to Fernet for local development
        return encrypt(plaintext)
    
    try:
        client = _get_kms_client()
        key_name = _get_kms_key_name()
        
        if not client or not key_name:
            return encrypt(plaintext)
        
        # Encrypt the plaintext
        response = client.encrypt(
            request={
                "name": key_name,
                "plaintext": plaintext.encode("utf-8")
            }
        )
        
        # Track KMS usage
        try:
            import asyncio
            from app.db.session import async_session_maker
            from app.services.api_usage import track_api_usage
            
            async def _track():
                async with async_session_maker() as db:
                    await track_api_usage(
                        db,
                        service_name="kms",
                        operation="encrypt",
                        api_calls=1
                    )
            
            try:
                loop = asyncio.get_running_loop()
                asyncio.create_task(_track())
            except RuntimeError:
                asyncio.run(_track())
        except Exception as track_err:
            logger.debug(f"Failed to track KMS encrypt usage: {track_err}")
        
        # Base64 encode and add prefix
        encrypted_b64 = base64.b64encode(response.ciphertext).decode("utf-8")
        return f"{KMS_ENCRYPTED_PREFIX}{encrypted_b64}"
        
    except Exception as e:
        logger.error(f"KMS encryption failed, falling back to Fernet: {e}")
        return encrypt(plaintext)


def decrypt_pii(ciphertext: str) -> str:
    """
    Decrypt PII data encrypted with Google Cloud KMS.
    
    Args:
        ciphertext: The encrypted string (with "kms:" prefix)
        
    Returns:
        Decrypted plaintext
    """
    if not ciphertext:
        return ciphertext
    
    # Handle non-KMS encrypted values
    if not ciphertext.startswith(KMS_ENCRYPTED_PREFIX):
        return decrypt_safe(ciphertext)
    
    if not _is_kms_available():
        logger.error("KMS encrypted data but KMS not available")
        return ""
    
    try:
        client = _get_kms_client()
        key_name = _get_kms_key_name()
        
        if not client or not key_name:
            logger.error("KMS client or key not available")
            return ""
        
        # Remove prefix and decode
        encrypted_b64 = ciphertext[len(KMS_ENCRYPTED_PREFIX):]
        encrypted_bytes = base64.b64decode(encrypted_b64)
        
        # Decrypt
        response = client.decrypt(
            request={
                "name": key_name,
                "ciphertext": encrypted_bytes
            }
        )
        
        return response.plaintext.decode("utf-8")
        
    except Exception as e:
        logger.error(f"KMS decryption failed: {e}")
        return ""

        return ""
