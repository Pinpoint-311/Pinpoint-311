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
    """A vault URL, plus some way to prove who we are.

    The second half used to require a client secret. On an Azure VM, App Service
    or Container App there is a managed identity attached to the compute, and
    using it is both less work -- nothing to enter -- and better: the token is
    issued minutes at a time and rotated by the platform, so no long-lived
    secret exists to leak, and none expires on a date nobody wrote down.
    Requiring a client secret meant a town on Azure had to create the worst
    credential of the three clouds while the platform was already offering it
    the best one.
    """
    if not _cfg("AZURE_KEYVAULT_URL"):
        return False
    if _managed_identity_endpoint():
        return True
    return bool(_cfg("AZURE_TENANT_ID") and _cfg("AZURE_KEYVAULT_CLIENT_ID")
                and _cfg("AZURE_KEYVAULT_CLIENT_SECRET"))


def _managed_identity_endpoint() -> Optional[str]:
    """Where to ask for a token, if this host has an identity of its own.

    App Service and Container Apps inject IDENTITY_ENDPOINT with a matching
    header secret; VMs and scale sets use the link-local IMDS address. Both are
    reachable only from inside Azure, so their presence is the detection.
    """
    return os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT")


def _managed_identity_token(scope: str):
    """(token, ttl_seconds) from the attached identity, or None."""
    endpoint = _managed_identity_endpoint()
    header_secret = os.getenv("IDENTITY_HEADER") or os.getenv("MSI_SECRET")
    try:
        if endpoint:
            resp = httpx.get(
                endpoint,
                params={"api-version": "2019-08-01", "resource": scope},
                headers={"X-IDENTITY-HEADER": header_secret} if header_secret else {},
                timeout=15.0,
            )
        else:
            resp = httpx.get(
                "http://169.254.169.254/metadata/identity/oauth2/token",
                params={"api-version": "2018-02-01", "resource": scope},
                headers={"Metadata": "true"},
                timeout=15.0,
            )
        resp.raise_for_status()
        body = resp.json()
        return body["access_token"], int(body.get("expires_in", 3600))
    except Exception as e:
        logger.debug(f"Managed identity token request failed: {e}")
        return None


def _get_token() -> Optional[str]:
    tenant = _cfg("AZURE_TENANT_ID")
    client_id = _cfg("AZURE_KEYVAULT_CLIENT_ID")
    client_secret = _cfg("AZURE_KEYVAULT_CLIENT_SECRET")
    authority = _cfg("AZURE_AUTHORITY") or "login.microsoftonline.com"
    scope = _cfg("AZURE_KEYVAULT_SCOPE") or "https://vault.azure.net"

    # The attached identity wins when there is one, rather than serving as a
    # fallback. A town with both keeps working after the client secret expires,
    # which is the failure this is most useful against.
    if _managed_identity_endpoint():
        cache_key = ("managed", scope)
        cached = _token_cache.get(cache_key)
        if cached and cached[1] - 60 > time.time():
            return cached[0]
        result = _managed_identity_token(scope)
        if result:
            token, ttl = result
            _token_cache[cache_key] = (token, time.time() + ttl)
            return token

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
