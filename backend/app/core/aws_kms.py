"""AWS KMS key-wrapping (boto3).

Third KMS backend alongside Google Cloud KMS and Azure Key Vault for wrapping
the PII data-encryption key (see pii_crypto). Only ever encrypts/decrypts the
32-byte DEK — never the PII itself — so the ~4KB KMS payload limit is irrelevant
and one call per process (cached) is all it costs. boto3 is already a dependency.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _cfg(key: str) -> Optional[str]:
    val = os.getenv(key)
    if val:
        return val
    try:
        from app.core.encryption import _get_config_sync
        return _get_config_sync(key)
    except Exception:
        return None


def is_configured() -> bool:
    return bool(_cfg("AWS_KMS_KEY_ID") and _cfg("AWS_REGION"))


def _client():
    try:
        import boto3
    except Exception as e:  # pragma: no cover
        logger.error(f"boto3 unavailable for AWS KMS: {e}")
        return None
    region = _cfg("AWS_REGION")
    if not region:
        return None
    kwargs = {"region_name": region}
    access_key = _cfg("AWS_ACCESS_KEY_ID")
    secret_key = _cfg("AWS_SECRET_ACCESS_KEY")
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
        session_token = _cfg("AWS_SESSION_TOKEN")
        if session_token:
            kwargs["aws_session_token"] = session_token
    try:
        return boto3.client("kms", **kwargs)
    except Exception as e:
        logger.error(f"Could not build AWS KMS client: {e}")
        return None


def encrypt(dek: bytes) -> bytes:
    """Wrap the DEK with the configured KMS key. Returns the ciphertext blob."""
    client = _client()
    key_id = _cfg("AWS_KMS_KEY_ID")
    if not client or not key_id:
        raise RuntimeError("AWS KMS not configured")
    resp = client.encrypt(KeyId=key_id, Plaintext=dek)
    return resp["CiphertextBlob"]


def decrypt(blob: bytes) -> bytes:
    """Unwrap the DEK. KeyId is passed for symmetric-key clarity but the blob
    already identifies the key."""
    client = _client()
    key_id = _cfg("AWS_KMS_KEY_ID")
    if not client:
        raise RuntimeError("AWS KMS not configured")
    kwargs = {"CiphertextBlob": blob}
    if key_id:
        kwargs["KeyId"] = key_id
    resp = client.decrypt(**kwargs)
    return resp["Plaintext"]
