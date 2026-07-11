"""AWS Secrets Manager store (boto3).

Third host-managed secret store option alongside Google Secret Manager and
Azure Key Vault, for jurisdictions authorized on AWS GovCloud. Mirrors the
azure_keyvault interface (is_configured / get_secret / set_secret) so the
secret_manager façade can treat all three the same. boto3 is already a
dependency (Bedrock), so no new package is needed.

Each logical key is stored as its own Secrets Manager secret, namespaced under
a prefix (default "pinpoint/") to keep them grouped in the console. Credentials
resolve via explicit keys when provided, otherwise boto3's default chain
(instance role / env), which is the norm on GovCloud.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _cfg(key: str) -> Optional[str]:
    """Read config from env, then DB secrets — same resolver the other stores use."""
    val = os.getenv(key)
    if val:
        return val
    try:
        from app.core.encryption import _get_config_sync
        return _get_config_sync(key)
    except Exception:
        return None


def is_configured() -> bool:
    # A region is the minimum; credentials may come from the default chain
    # (instance profile) so we don't require explicit keys.
    return bool(_cfg("AWS_REGION"))


def _prefix() -> str:
    return _cfg("AWS_SECRETS_PREFIX") or "pinpoint/"


def _secret_id(name: str) -> str:
    return f"{_prefix()}{name}"


def _client():
    try:
        import boto3
    except Exception as e:  # pragma: no cover - boto3 always installed
        logger.error(f"boto3 unavailable for AWS Secrets Manager: {e}")
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
        return boto3.client("secretsmanager", **kwargs)
    except Exception as e:
        logger.error(f"Could not build AWS Secrets Manager client: {e}")
        return None


def get_secret(name: str) -> Optional[str]:
    client = _client()
    if not client:
        return None
    try:
        resp = client.get_secret_value(SecretId=_secret_id(name))
        return resp.get("SecretString")
    except Exception as e:
        # ResourceNotFoundException is the common, expected path for unset keys.
        if e.__class__.__name__ != "ResourceNotFoundException":
            logger.warning(f"AWS Secrets Manager read failed for {name}: {e}")
        return None


def set_secret(name: str, value: str) -> bool:
    client = _client()
    if not client:
        return False
    sid = _secret_id(name)
    try:
        client.put_secret_value(SecretId=sid, SecretString=value)
        return True
    except Exception as e:
        if e.__class__.__name__ == "ResourceNotFoundException":
            try:
                client.create_secret(Name=sid, SecretString=value)
                return True
            except Exception as e2:
                logger.error(f"AWS Secrets Manager create failed for {name}: {e2}")
                return False
        logger.error(f"AWS Secrets Manager write failed for {name}: {e}")
        return False
