"""Azure Key Vault client (secrets + key crypto) over the REST API.

Used to offer Azure as an alternative to Google for the two host-managed
capabilities: PII key management (KMS-equivalent) and the secret store. Uses
plain httpx (sync) + AAD client-credentials — no azure SDK dependency, and
fully mockable. Works against commercial and Azure Government by configuring
the authority + vault scope.

All functions are synchronous because the PII encrypt/decrypt path
(models.py setters) is synchronous, matching the existing Google KMS usage.
"""

import base64
import logging
import os
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# cache: (tenant, client_id, scope) -> (token, expiry_epoch)
_token_cache: dict = {}


def _cfg(key: str) -> Optional[str]:
    """Read Azure Key Vault config from env, then DB secrets (same resolver the
    Google KMS path uses)."""
    val = os.getenv(key)
    if val:
        return val
    try:
        from app.core.encryption import _get_config_sync
        return _get_config_sync(key)
    except Exception:
        return None


def _b64url_nopad(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def is_configured() -> bool:
    return bool(_cfg("AZURE_TENANT_ID") and _cfg("AZURE_KEYVAULT_CLIENT_ID")
                and _cfg("AZURE_KEYVAULT_CLIENT_SECRET") and _cfg("AZURE_KEYVAULT_URL"))


def _get_token() -> Optional[str]:
    tenant = _cfg("AZURE_TENANT_ID")
    client_id = _cfg("AZURE_KEYVAULT_CLIENT_ID")
    client_secret = _cfg("AZURE_KEYVAULT_CLIENT_SECRET")
    authority = _cfg("AZURE_AUTHORITY") or "login.microsoftonline.com"
    scope = _cfg("AZURE_KEYVAULT_SCOPE") or "https://vault.azure.net"
    if not all([tenant, client_id, client_secret]):
        return None

    cache_key = (tenant, client_id, scope)
    cached = _token_cache.get(cache_key)
    if cached and cached[1] - 60 > time.time():
        return cached[0]

    resp = httpx.post(
        f"https://{authority}/{tenant}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": f"{scope}/.default",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15.0,
    )
    resp.raise_for_status()
    body = resp.json()
    token = body["access_token"]
    _token_cache[cache_key] = (token, time.time() + int(body.get("expires_in", 3600)))
    return token


def _vault_url() -> str:
    return (_cfg("AZURE_KEYVAULT_URL") or "").rstrip("/")


def _api_version() -> str:
    return _cfg("AZURE_KEYVAULT_API_VERSION") or "7.4"


# ---- Key crypto (KMS-equivalent) ----

def encrypt(plaintext: str) -> str:
    """Encrypt with the configured Key Vault key (RSA-OAEP-256). Returns the
    base64url ciphertext. Suitable for small values (PII fields)."""
    token = _get_token()
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not token or not key_name:
        raise RuntimeError("Azure Key Vault key crypto not configured")
    url = f"{_vault_url()}/keys/{key_name}/encrypt?api-version={_api_version()}"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"alg": "RSA-OAEP-256", "value": _b64url_nopad(plaintext.encode("utf-8"))},
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()["value"]


def decrypt(ciphertext_b64url: str) -> str:
    token = _get_token()
    key_name = _cfg("AZURE_KEYVAULT_KEY")
    if not token or not key_name:
        raise RuntimeError("Azure Key Vault key crypto not configured")
    url = f"{_vault_url()}/keys/{key_name}/decrypt?api-version={_api_version()}"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"alg": "RSA-OAEP-256", "value": ciphertext_b64url},
        timeout=15.0,
    )
    resp.raise_for_status()
    return _b64url_decode(resp.json()["value"]).decode("utf-8")


# ---- Secret store ----

def _secret_id(name: str) -> str:
    # Key Vault secret names allow only alphanumerics and dashes
    return name.replace("_", "-").lower()


def get_secret(name: str) -> Optional[str]:
    token = _get_token()
    if not token:
        return None
    url = f"{_vault_url()}/secrets/{_secret_id(name)}?api-version={_api_version()}"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15.0)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json().get("value")


def set_secret(name: str, value: str) -> bool:
    token = _get_token()
    if not token:
        return False
    url = f"{_vault_url()}/secrets/{_secret_id(name)}?api-version={_api_version()}"
    resp = httpx.put(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"value": value},
        timeout=15.0,
    )
    resp.raise_for_status()
    return True
